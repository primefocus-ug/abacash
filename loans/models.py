"""
loans/models.py
===============

Models
------
LoanProduct     – a type of loan with its rules (interest rate, max term, etc.)
Loan            – a specific loan issued to a client
LoanSchedule    – one row per repayment period in the amortization table
Guarantor       – a person who guarantees a loan
LoanGuarantee   – tracks guarantees provided for loans
LoanFee         – fees charged on a loan
LoanRestructure – history of loan restructuring
LoanRenewal     – tracks loan renewals/roll-overs

Design notes
------------
* All monetary fields are DecimalField(max_digits=15, decimal_places=2).
  Never use FloatField for money — floating-point arithmetic causes
  rounding errors that accumulate over a loan lifetime.

* Interest calculation methods:
    FLAT_RATE        – interest = principal × rate × term (simple interest,
                       divided equally across all periods)
    REDUCING_BALANCE – interest per period calculated on outstanding balance
                       (true amortisation, higher total interest)

* Loan approval limits enforced in views/services (not model-level):
    Manager  → can approve loans ≤ UGX 5,000,000
    CEO      → can approve any amount

* LoanSchedule rows are created when the loan moves to APPROVED status.
  Each row tracks whether a payment has been received against it.
"""

import uuid
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from django.db import transaction


class LoanProduct(models.Model):
    """
    A loan product defines the rules for a category of loans.
    Example products: "Salary Loan", "Business Loan", "Emergency Loan".

    The CEO configures these; staff cannot change them during loan application.
    """

    class InterestMethod(models.TextChoices):
        FLAT_RATE        = "FLAT",     _("Flat Rate")
        REDUCING_BALANCE = "REDUCING", _("Reducing Balance")

    class RepaymentFrequency(models.TextChoices):
        DAILY     = "DAILY",     _("Daily")
        WEEKLY    = "WEEKLY",    _("Weekly")
        BIWEEKLY  = "BIWEEKLY",  _("Bi-Weekly (Every 2 Weeks)")
        MONTHLY   = "MONTHLY",   _("Monthly")

    name        = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    # Interest rate stored as percentage, e.g. 5.00 means 5% per month
    interest_rate_monthly = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01")), MaxValueValidator(Decimal("99.99"))],
        help_text=_("Monthly interest rate as a percentage, e.g. 5.00 for 5% per month."),
    )

    interest_method = models.CharField(
        max_length=10,
        choices=InterestMethod.choices,
        default=InterestMethod.FLAT_RATE,
    )

    default_repayment_frequency = models.CharField(
        max_length=10,
        choices=RepaymentFrequency.choices,
        default=RepaymentFrequency.MONTHLY,
    )

    # Loan amount limits in UGX
    min_amount = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal("100000"),
        help_text=_("Minimum loan amount in UGX."),
    )
    max_amount = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal("10000000"),
        help_text=_("Maximum loan amount in UGX."),
    )

    # Term limits in months
    min_term_months = models.PositiveSmallIntegerField(default=1)
    max_term_months = models.PositiveSmallIntegerField(default=12)

    # Late payment penalty as a percentage of overdue amount per month
    penalty_rate_monthly = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("2.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("99.99"))],
        help_text=_("Monthly penalty rate on overdue amounts, e.g. 2.00 for 2%."),
    )

    # Processing fee (percentage of loan amount)
    processing_fee_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("1.00"),
        help_text=_("Processing fee as a percentage of loan amount."),
    )

    requires_guarantor = models.BooleanField(
        default=True,
        help_text=_("If True, client must have at least one guarantor before approval."),
    )

    max_guarantor_liability_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("100.00"),
        help_text=_("Maximum liability of guarantor as percentage of loan (100 = full guarantee)."),
    )

    min_guarantor_count = models.PositiveSmallIntegerField(
        default=1,
        help_text=_("Minimum number of guarantors required."),
    )

    allows_early_repayment = models.BooleanField(
        default=True,
        help_text=_("If True, clients can repay early (may have penalty)."),
    )

    early_repayment_penalty_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text=_("Penalty for early repayment as percentage of outstanding balance."),
    )

    allows_restructuring = models.BooleanField(
        default=True,
        help_text=_("If True, loan terms can be restructured after approval."),
    )

    allows_renewal = models.BooleanField(
        default=True,
        help_text=_("If True, this loan can be renewed/rolled over."),
    )

    # Risk settings
    max_debt_to_income_ratio = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("40.00"),
        help_text=_("Maximum debt-to-income ratio as percentage (e.g., 40 = 40%)."),
    )

    is_active = models.BooleanField(
        default=True,
        help_text=_("Inactive products cannot be selected for new loan applications."),
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="created_loan_products",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.interest_rate_monthly}%/month {self.get_interest_method_display()})"

    class Meta:
        verbose_name = _("Loan Product")
        verbose_name_plural = _("Loan Products")
        ordering = ["name"]


class LoanSequence(models.Model):
    """Simple sequence row used to allocate sequential loan core IDs.

    Using a dedicated row avoids scanning the loans table and provides
    a single row to lock with `select_for_update()` when incrementing
    the counter, which is more reliable under concurrency.
    """
    name = models.CharField(max_length=32, unique=True)
    last = models.PositiveBigIntegerField(default=0)

    def __str__(self):
        return f"{self.name}:{self.last}"


class Loan(models.Model):
    """
    A single loan issued (or being processed) for a client.

    Lifecycle:  DRAFT → PENDING → APPROVED or REJECTED
                APPROVED → ACTIVE (once disbursed)
                ACTIVE   → COMPLETED (once fully repaid)
                ACTIVE   → DEFAULTED (if written off)
                ACTIVE   → RESTRUCTURED (if terms modified)
    """

    class Status(models.TextChoices):
        DRAFT          = "DRAFT",     _("Draft")
        PENDING        = "PENDING",   _("Pending Approval")
        APPROVED       = "APPROVED",  _("Approved")
        REJECTED       = "REJECTED",  _("Rejected")
        ACTIVE         = "ACTIVE",    _("Active")
        RESTRUCTURED   = "RESTRUCTURED", _("Restructured")
        COMPLETED      = "COMPLETED", _("Completed")
        DEFAULTED      = "DEFAULTED", _("Defaulted")
        WRITTEN_OFF    = "WRITTEN_OFF", _("Written Off")

    class RepaymentFrequency(models.TextChoices):
        DAILY    = "DAILY",    _("Daily")
        WEEKLY   = "WEEKLY",   _("Weekly")
        BIWEEKLY = "BIWEEKLY", _("Bi-Weekly")
        MONTHLY  = "MONTHLY",  _("Monthly")

    class Priority(models.TextChoices):
        LOW      = "LOW",      _("Low")
        NORMAL   = "NORMAL",   _("Normal")
        HIGH     = "HIGH",     _("High")
        URGENT   = "URGENT",   _("Urgent")

    # ------------------------------------------------------------------ #
    # Identity                                                             #
    # ------------------------------------------------------------------ #

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Human-readable reference, e.g. LN-2024-00042
    loan_number = models.CharField(max_length=25, unique=True, editable=False)

    # Core ID for faster lookups (sequential)
    core_id = models.CharField(max_length=20, unique=True, editable=False, null=True, blank=True, help_text=_("Sequential core ID"))

    # ------------------------------------------------------------------ #
    # Relationships                                                        #
    # ------------------------------------------------------------------ #

    client = models.ForeignKey(
        "clients.Client",
        on_delete=models.PROTECT,
        related_name="loans",
    )
    product = models.ForeignKey(
        LoanProduct,
        on_delete=models.PROTECT,
        related_name="loans",
    )

    # Branch where this loan was processed
    branch = models.ForeignKey(
        "accounts.Branch",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="loans",
    )

    # Staff who created the application on behalf of the client
    applied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="applied_loans",
        null=True, blank=True,
    )

    # Staff who approved or rejected
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reviewed_loans",
        null=True, blank=True,
    )

    # Cashier who recorded the first disbursement
    disbursed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="disbursed_loans",
        null=True, blank=True,
    )

    # For renewed loans, link to the previous loan
    renewed_from = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="renewals",
        help_text=_("If this is a renewal, the original loan."),
    )

    # ------------------------------------------------------------------ #
    # Financial terms (snapshot at application time)                      #
    # ------------------------------------------------------------------ #
    # We snapshot all terms from LoanProduct at application time so that
    # future changes to the product do not alter existing loans.

    principal_amount = models.DecimalField(
        max_digits=15, decimal_places=2,
        help_text=_("Original loan amount in UGX."),
    )

    # Snapshotted from product at application time
    interest_rate_monthly = models.DecimalField(max_digits=5, decimal_places=2)
    interest_method       = models.CharField(max_length=10, choices=LoanProduct.InterestMethod.choices)
    penalty_rate_monthly  = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("2.00"))

    term_months = models.PositiveSmallIntegerField(
        help_text=_("Loan term in months."),
    )

    repayment_frequency = models.CharField(
        max_length=10,
        choices=RepaymentFrequency.choices,
        default=RepaymentFrequency.MONTHLY,
    )

    # Priority for collections
    priority = models.CharField(
        max_length=10,
        choices=Priority.choices,
        default=Priority.NORMAL,
    )

    # Calculated totals stored for fast reporting (recomputed on schedule generation)
    total_repayable      = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0"))
    total_interest       = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0"))
    total_paid           = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0"))
    outstanding_balance  = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0"))
    total_penalties      = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0"))
    total_fees           = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0"))
    processing_fee       = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0"))

    # ------------------------------------------------------------------ #
    # Dates                                                                #
    # ------------------------------------------------------------------ #

    application_date     = models.DateField(default=timezone.localdate)
    approval_date        = models.DateField(null=True, blank=True)
    disbursement_date    = models.DateField(
        null=True, blank=True,
        help_text=_("Date the money was physically handed to the client."),
    )
    first_repayment_date = models.DateField(
        null=True, blank=True,
        help_text=_("Date of first scheduled repayment — usually 1 period after disbursement."),
    )
    maturity_date        = models.DateField(null=True, blank=True)
    completion_date      = models.DateField(null=True, blank=True)
    written_off_date     = models.DateField(null=True, blank=True)

    # ------------------------------------------------------------------ #
    # Status & workflow                                                    #
    # ------------------------------------------------------------------ #

    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )

    rejection_reason = models.TextField(
        blank=True,
        help_text=_("Required when rejecting a loan application."),
    )

    purpose = models.TextField(
        blank=True,
        help_text=_("What the client intends to use the money for."),
    )

    # For tracking restructuring history
    is_restructured = models.BooleanField(default=False)
    restructure_count = models.PositiveSmallIntegerField(default=0)
    last_restructure_date = models.DateField(null=True, blank=True)

    # For tracking renewals
    is_renewal = models.BooleanField(default=False)
    renewal_count = models.PositiveSmallIntegerField(default=0)

    # Write-off details
    write_off_reason = models.TextField(blank=True)
    write_off_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="written_off_loans",
    )

    # Risk classification
    risk_rating = models.CharField(
        max_length=15,
        choices=[
            ("LOW", "Low Risk"),
            ("NORMAL", "Normal Risk"),
            ("WATCH", "Watch List"),
            ("SUBSTANDARD", "Substandard"),
            ("DOUBTFUL", "Doubtful"),
            ("LOSS", "Loss"),
        ],
        default="NORMAL",
        db_index=True,
    )

    # Portfolio at Risk classification
    par_category = models.CharField(
        max_length=10,
        choices=[
            ("CURRENT", "Current"),
            ("PAR1", "1-30 days overdue"),
            ("PAR30", "31-60 days overdue"),
            ("PAR60", "61-90 days overdue"),
            ("PAR90", "90+ days overdue"),
        ],
        default="CURRENT",
        db_index=True,
    )

    notes = models.TextField(blank=True, help_text=_("Internal staff notes."))

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ------------------------------------------------------------------ #
    # Methods                                                              #
    # ------------------------------------------------------------------ #

    def save(self, *args, **kwargs):
        """Auto-generate loan_number and core_id before first save."""
        if not self.loan_number:
            year = timezone.now().year
            count = Loan.objects.filter(
                application_date__year=year
            ).count() + 1
            self.loan_number = f"LN-{year}-{count:05d}"

        if not self.core_id:
            with transaction.atomic():
                seq, _ = LoanSequence.objects.select_for_update().get_or_create(
                    name="loans",
                    defaults={"last": 0},
                )
                seq.last = seq.last + 1
                seq.save()
                self.core_id = f"LN{seq.last:08d}"

        # Compute processing fee from CompanySettings (primary source) if not
        # already set by the view layer.
        if self.processing_fee == Decimal("0") and self.product_id and self.principal_amount:
            try:
                from loans.utils import calculate_processing_fee_amount
                self.processing_fee = calculate_processing_fee_amount(
                    self.principal_amount, product=self.product
                )
            except Exception:
                pass

        super().save(*args, **kwargs)

    @property
    def effective_processing_fee(self):
        if self.processing_fee and self.processing_fee > Decimal("0"):
            return self.processing_fee
        try:
            from loans.utils import calculate_processing_fee_amount
            return calculate_processing_fee_amount(self.principal_amount, product=self.product)
        except Exception:
            return Decimal("0")

    @property
    def cash_disbursed(self):
        return self.principal_amount

    @property
    def total_repayable_inclusive_of_charges(self):
        return self.total_repayable + self.effective_processing_fee

    @property
    def is_overdue(self):
        """True if there is at least one unpaid schedule entry past its due date."""
        today = timezone.localdate()
        return self.schedule.filter(
            status__in=[LoanSchedule.Status.PENDING, LoanSchedule.Status.OVERDUE],
            due_date__lt=today,
        ).exists()

    @property
    def days_overdue(self):
        """Days since the oldest unpaid overdue entry."""
        today = timezone.localdate()
        oldest = (
            self.schedule.filter(
                status__in=[LoanSchedule.Status.PENDING, LoanSchedule.Status.OVERDUE],
                due_date__lt=today,
            )
            .order_by("due_date")
            .first()
        )
        if oldest:
            return (today - oldest.due_date).days
        return 0

    @property
    def next_due_date(self):
        """Due date of the next unpaid schedule entry."""
        entry = (
            self.schedule.filter(status__in=[LoanSchedule.Status.PENDING, LoanSchedule.Status.OVERDUE])
            .order_by("due_date")
            .first()
        )
        return entry.due_date if entry else None

    @property
    def next_due_amount(self):
        """Total amount due on the next unpaid schedule entry."""
        entry = (
            self.schedule.filter(status__in=[LoanSchedule.Status.PENDING, LoanSchedule.Status.OVERDUE])
            .order_by("due_date")
            .first()
        )
        return entry.total_payment + entry.penalty_due - entry.amount_paid if entry else Decimal("0")

    @property
    def total_guaranteed_amount(self):
        """Total amount guaranteed by all guarantors for this loan."""
        return sum(g.guaranteed_amount for g in self.guarantees.all())

    @property
    def guarantor_shortfall(self):
        """Amount still needed from guarantors to meet product requirements."""
        required = self.principal_amount * (self.product.max_guarantor_liability_percent / 100)
        return max(required - self.total_guaranteed_amount, Decimal("0"))

    def __str__(self):
        return f"{self.loan_number} — {self.client} ({self.get_status_display()})"

    class Meta:
        verbose_name = _("Loan")
        verbose_name_plural = _("Loans")
        ordering = ["-application_date"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["client", "status"]),
            models.Index(fields=["disbursement_date"]),
            models.Index(fields=["risk_rating"]),
            models.Index(fields=["par_category"]),
            models.Index(fields=["branch", "status"]),
        ]


class Guarantor(models.Model):
    """
    A person who provides a guarantee for a client's loan.
    Guarantors can guarantee multiple loans but have a maximum liability limit.
    """

    class Type(models.TextChoices):
        INDIVIDUAL = "INDIVIDUAL", _("Individual")
        CORPORATE = "CORPORATE", _("Corporate/Company")

    # Personal details
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    other_names = models.CharField(max_length=100, blank=True)

    # For corporate guarantors
    company_name = models.CharField(max_length=200, blank=True)
    registration_number = models.CharField(max_length=50, blank=True)

    guarantor_type = models.CharField(
        max_length=10,
        choices=Type.choices,
        default=Type.INDIVIDUAL,
    )

    # Contact details
    nin = models.CharField(max_length=20, blank=True, help_text=_("National ID Number"))
    phone_primary = models.CharField(max_length=20)
    phone_secondary = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    physical_address = models.TextField()
    district = models.CharField(max_length=100, default="Kampala")

    # Employment/Business info
    employer_name = models.CharField(max_length=200, blank=True)
    job_title = models.CharField(max_length=100, blank=True)
    monthly_income = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal("0"),
        help_text=_("Monthly income in UGX"),
    )

    # Maximum liability this guarantor can undertake
    max_liability = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal("0"),
        help_text=_("Maximum total liability this guarantor can undertake (UGX). 0 = no limit."),
    )

    # Total current liability across all active guarantees
    current_liability = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal("0"),
        help_text=_("Current total liability from active guarantees."),
    )

    # Status
    is_active = models.BooleanField(default=True)
    is_verified = models.BooleanField(default=False)
    verification_date = models.DateField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
    )

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def full_name(self):
        parts = [self.first_name, self.other_names, self.last_name]
        return " ".join(p for p in parts if p).strip()

    @property
    def available_capacity(self):
        """How much more this guarantor can guarantee."""
        if self.max_liability == 0:
            return Decimal("999999999999")  # No limit
        return max(self.max_liability - self.current_liability, Decimal("0"))

    def __str__(self):
        if self.guarantor_type == self.Type.CORPORATE:
            return f"{self.company_name} (Corporate Guarantor)"
        return f"{self.full_name} (Guarantor)"

    class Meta:
        verbose_name = _("Guarantor")
        verbose_name_plural = _("Guarantors")
        ordering = ["last_name", "first_name"]
        indexes = [
            models.Index(fields=["nin"]),
            models.Index(fields=["phone_primary"]),
            models.Index(fields=["is_active"]),
        ]


class LoanGuarantee(models.Model):
    """
    Links a guarantor to a loan with specific guarantee terms.
    """

    guarantor = models.ForeignKey(
        Guarantor,
        on_delete=models.PROTECT,
        related_name="guarantees",
    )
    loan = models.ForeignKey(
        Loan,
        on_delete=models.CASCADE,
        related_name="guarantees",
    )

    # Guarantee details
    guaranteed_amount = models.DecimalField(
        max_digits=15, decimal_places=2,
        help_text=_("Amount guaranteed for this loan (UGX)."),
    )

    guarantee_type = models.CharField(
        max_length=20,
        choices=[
            ("FULL", "Full Guarantee"),
            ("PARTIAL", "Partial Guarantee"),
            ("JOINT", "Joint and Several"),
            ("CONTINUING", "Continuing Guarantee"),
        ],
        default="FULL",
    )

    # Guarantee documents
    agreement_signed = models.BooleanField(default=False)
    agreement_date = models.DateField(null=True, blank=True)
    agreement_document = models.FileField(upload_to="guarantees/", null=True, blank=True)

    # ID document
    id_document = models.FileField(upload_to="guarantees/", null=True, blank=True)

    # Status
    is_active = models.BooleanField(default=True)
    released_date = models.DateField(null=True, blank=True)
    release_reason = models.TextField(blank=True)

    # Called guarantee (guarantor had to pay)
    is_called = models.BooleanField(default=False)
    called_date = models.DateField(null=True, blank=True)
    called_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0"))

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.guarantor} → {self.loan.loan_number} (UGX {self.guaranteed_amount:,.0f})"

    class Meta:
        verbose_name = _("Loan Guarantee")
        verbose_name_plural = _("Loan Guarantees")
        ordering = ["-created_at"]
        unique_together = [("guarantor", "loan")]
        indexes = [
            models.Index(fields=["loan", "is_active"]),
            models.Index(fields=["guarantor", "is_active"]),
        ]


class LoanFee(models.Model):
    """
    Fees charged on a specific loan.
    Can be automatically applied based on FeeType or manually added.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        WAIVED = "WAIVED", _("Waived")
        PAID = "PAID", _("Paid")

    loan = models.ForeignKey(
        Loan,
        on_delete=models.CASCADE,
        related_name="fees",
    )

    fee_type = models.ForeignKey(
        "accounts.FeeType",
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="loan_fees",
    )

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    amount = models.DecimalField(max_digits=15, decimal_places=2)

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )

    due_date = models.DateField(null=True, blank=True)
    paid_date = models.DateField(null=True, blank=True)

    # Waiver details
    waived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="waived_fees",
    )
    waiver_reason = models.TextField(blank=True)
    waiver_date = models.DateField(null=True, blank=True)

    # Who added this fee
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="added_fees",
    )

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.loan.loan_number} - {self.name} (UGX {self.amount:,.0f})"

    class Meta:
        verbose_name = _("Loan Fee")
        verbose_name_plural = _("Loan Fees")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["loan", "status"]),
            models.Index(fields=["due_date"]),
        ]


class LoanRestructure(models.Model):
    """
    Records when a loan's terms are modified after approval.
    """

    loan = models.ForeignKey(
        Loan,
        on_delete=models.CASCADE,
        related_name="restructures",
    )

    # What changed
    old_term_months = models.PositiveSmallIntegerField()
    new_term_months = models.PositiveSmallIntegerField()

    old_interest_rate = models.DecimalField(max_digits=5, decimal_places=2)
    new_interest_rate = models.DecimalField(max_digits=5, decimal_places=2)

    old_installment = models.DecimalField(max_digits=15, decimal_places=2)
    new_installment = models.DecimalField(max_digits=15, decimal_places=2)

    old_maturity_date = models.DateField(null=True, blank=True)
    new_maturity_date = models.DateField()

    # Reason and approval
    reason = models.TextField()
    requested_by = models.TextField(help_text=_("Who requested the restructure (client/staff)"))

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approved_restructures",
    )

    restructure_fee = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal("0"),
        help_text=_("Fee charged for restructuring."),
    )

    effective_date = models.DateField(default=timezone.localdate)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Restructure {self.loan.loan_number} on {self.effective_date}"

    class Meta:
        verbose_name = _("Loan Restructure")
        verbose_name_plural = _("Loan Restructures")
        ordering = ["-effective_date"]
        indexes = [
            models.Index(fields=["loan", "effective_date"]),
        ]


class LoanRenewal(models.Model):
    """
    Tracks when a loan is renewed/rolled over into a new loan.
    """

    original_loan = models.ForeignKey(
        Loan,
        on_delete=models.PROTECT,
        related_name="renewal_records",
    )

    new_loan = models.ForeignKey(
        Loan,
        on_delete=models.PROTECT,
        related_name="renewal_from",
    )

    # Amount rolled over
    outstanding_amount = models.DecimalField(max_digits=15, decimal_places=2)
    additional_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0"))
    total_new_principal = models.DecimalField(max_digits=15, decimal_places=2)

    # Reason for renewal
    reason = models.TextField()

    # Approval
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approved_renewals",
    )

    renewal_date = models.DateField(default=timezone.localdate)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Renewal: {self.original_loan.loan_number} → {self.new_loan.loan_number}"

    class Meta:
        verbose_name = _("Loan Renewal")
        verbose_name_plural = _("Loan Renewals")
        ordering = ["-renewal_date"]
        unique_together = [("original_loan", "new_loan")]


class CollateralItem(models.Model):
    """
    A piece of collateral pledged against a loan.
    Multiple items can be attached to one loan.
    """
    loan              = models.ForeignKey(Loan, on_delete=models.CASCADE, related_name="collateral_items")
    description       = models.CharField(max_length=255, help_text=_("e.g. Land title, Motorcycle, TV"))
    estimated_value   = models.DecimalField(max_digits=15, decimal_places=2)
    notes             = models.CharField(max_length=255, blank=True)

    # Additional fields for better tracking
    document_number = models.CharField(max_length=100, blank=True, help_text=_("Title deed number, etc."))
    storage_location = models.CharField(max_length=200, blank=True, help_text=_("Where physical collateral is stored"))
    release_date = models.DateField(null=True, blank=True)
    released_to = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return f"{self.description} — UGX {self.estimated_value:,.0f} ({self.loan.loan_number})"

    class Meta:
        verbose_name = _("Collateral Item")
        verbose_name_plural = _("Collateral Items")


class LoanSchedule(models.Model):
    """
    One row per repayment period in a loan's amortization table.

    Rows are generated by loans/utils.py::generate_schedule() when
    the loan is approved and saved in bulk.

    Status transitions
    ------------------
    PENDING  → PAID    (full payment received for this period)
    PENDING  → PARTIAL (partial payment received, still outstanding)
    PENDING  → OVERDUE (due date passed with no/insufficient payment)
    PARTIAL  → PAID    (remaining balance paid)
    OVERDUE  → PAID    (overdue amount + penalties paid)
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        PARTIAL = "PARTIAL", _("Partially Paid")
        PAID    = "PAID",    _("Paid")
        OVERDUE = "OVERDUE", _("Overdue")
        WAIVED  = "WAIVED",  _("Waived")  # CEO can waive a period

    loan = models.ForeignKey(Loan, on_delete=models.CASCADE, related_name="schedule")

    # Period number: 1 = first repayment, 2 = second, etc.
    period_number = models.PositiveSmallIntegerField()

    due_date         = models.DateField(db_index=True)

    # Balances and payment breakdown (all in UGX)
    opening_balance  = models.DecimalField(max_digits=15, decimal_places=2)
    principal_due    = models.DecimalField(max_digits=15, decimal_places=2)
    interest_due     = models.DecimalField(max_digits=15, decimal_places=2)
    penalty_due      = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0"))
    fee_due          = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0"))
    total_payment    = models.DecimalField(
        max_digits=15, decimal_places=2,
        help_text=_("principal_due + interest_due + penalty_due + fee_due"),
    )
    closing_balance  = models.DecimalField(max_digits=15, decimal_places=2)

    # Amounts actually received against this period
    amount_paid      = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0"))
    paid_date        = models.DateField(null=True, blank=True)

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    # For tracking which payment covered this
    paid_by_payment = models.ForeignKey(
        "payments.Payment",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="schedule_entries_paid",
    )

    notes = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return (
            f"{self.loan.loan_number} — Period {self.period_number} "
            f"(Due {self.due_date}, {self.get_status_display()})"
        )

    class Meta:
        verbose_name = _("Loan Schedule Entry")
        verbose_name_plural = _("Loan Schedule")
        ordering = ["loan", "period_number"]
        unique_together = [("loan", "period_number")]
        indexes = [
            models.Index(fields=["due_date", "status"]),
            models.Index(fields=["loan", "status"]),
        ]


class LoanScheduleExtension(models.Model):
    """
    Records manual extensions to a LoanSchedule.due_date made by staff.
    Stores the original date, the new date, who performed the change and a reason.
    """

    schedule_entry = models.ForeignKey(
        LoanSchedule,
        on_delete=models.CASCADE,
        related_name="extensions",
    )

    old_due_date = models.DateField()
    new_due_date = models.DateField()
    reason = models.TextField()

    extended_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="schedule_extensions",
    )
    extended_at = models.DateTimeField(auto_now_add=True)

    notes = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"Extend {self.schedule_entry.loan.loan_number} period {self.schedule_entry.period_number}: {self.old_due_date} → {self.new_due_date}"

    class Meta:
        verbose_name = _("Loan Schedule Extension")
        verbose_name_plural = _("Loan Schedule Extensions")
        ordering = ["-extended_at"]

