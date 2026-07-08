from decimal import Decimal
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):

    class Role(models.TextChoices):
        CASHIER = "CASHIER", _("Cashier")
        MANAGER = "MANAGER", _("Manager")
        CEO     = "CEO",     _("CEO")

    # Every user must have exactly one role.
    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.CASHIER,
        help_text=_("Controls which parts of the system this user can access."),
    )

    # Override email to make it required and unique.
    email = models.EmailField(_("email address"), unique=True)

    phone = models.CharField(
        max_length=20,
        blank=True,
        help_text=_("Staff contact number, e.g. +256700123456"),
    )

    # Branch assignment for multi-branch operations
    branch = models.ForeignKey(
        "accounts.Branch",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="staff_members",
        help_text=_("Branch where this user is stationed."),
    )

    # Commission rate for performance tracking (percentage)
    commission_rate = models.DecimalField(
        max_digits=5, decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
        help_text=_("Commission rate as a percentage (e.g., 2.50 for 2.5%)."),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ------------------------------------------------------------------ #
    # Convenience properties used in templates and views                   #
    # ------------------------------------------------------------------ #

    @property
    def is_cashier(self):
        return self.role == self.Role.CASHIER

    @property
    def is_manager(self):
        return self.role == self.Role.MANAGER

    @property
    def is_ceo(self):
        return self.role == self.Role.CEO

    @property
    def can_approve_loans(self):
        """Managers and CEOs can approve loans."""
        return self.role in (self.Role.MANAGER, self.Role.CEO)

    @property
    def full_name(self):
        return self.get_full_name() or self.username

    def __str__(self):
        branch_info = f" - {self.branch.name}" if self.branch else ""
        return f"{self.full_name} ({self.get_role_display()}{branch_info})"

    class Meta:
        verbose_name = _("User")
        verbose_name_plural = _("Users")
        ordering = ["first_name", "last_name"]


class Branch(models.Model):
    """
    Represents a branch/office location of the microfinance institution.
    Allows for multi-branch operations with branch-specific settings.
    """
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=10, unique=True, help_text=_("Short code for this branch, e.g., KLA, MBA"))
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    manager = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="managed_branches",
        help_text=_("Branch manager."),
    )
    is_active = models.BooleanField(default=True)
    opened_date = models.DateField(null=True, blank=True)
    closed_date = models.DateField(null=True, blank=True)

    # Branch-specific settings
    approval_limit = models.DecimalField(
        max_digits=15, decimal_places=2,
        default=Decimal("10_000_000"),
        help_text=_("Maximum loan amount this branch can approve without head office approval (UGX)."),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.code})"

    class Meta:
        verbose_name = _("Branch")
        verbose_name_plural = _("Branches")
        ordering = ["name"]


class FeeType(models.Model):
    """
    Defines different types of fees that can be charged.
    Examples: Processing fee, Late payment fee, Early repayment penalty, etc.
    """
    class CalculationMethod(models.TextChoices):
        FLAT = "FLAT", _("Flat Amount")
        PERCENTAGE = "PERCENTAGE", _("Percentage of Loan Amount")
        PERCENTAGE_OUTSTANDING = "PERCENTAGE_OUTSTANDING", _("Percentage of Outstanding Balance")

    class AppliedTo(models.TextChoices):
        LOAN_APPLICATION = "LOAN_APP", _("Loan Application")
        LOAN_DISBURSEMENT = "LOAN_DISB", _("Loan Disbursement")
        LATE_PAYMENT = "LATE_PAY", _("Late Payment")
        EARLY_REPAYMENT = "EARLY_PAY", _("Early Repayment")
        LOAN_RESTRUCTURE = "RESTRUCTURE", _("Loan Restructuring")
        CHECKBOOK = "CHECKBOOK", _("Checkbook Issuance")
        STATEMENT = "STATEMENT", _("Account Statement")
        OTHER = "OTHER", _("Other")

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    applied_to = models.CharField(max_length=20, choices=AppliedTo.choices)
    calculation_method = models.CharField(
        max_length=30,
        choices=CalculationMethod.choices,
        default=CalculationMethod.FLAT,
    )
    amount = models.DecimalField(
        max_digits=15, decimal_places=2,
        default=Decimal("0.00"),
        help_text=_("Flat amount in UGX or percentage value depending on calculation method."),
    )
    is_active = models.BooleanField(default=True)
    is_mandatory = models.BooleanField(
        default=False,
        help_text=_("If True, this fee is automatically applied to all applicable transactions."),
    )

    # For percentage-based fees, set min and max limits
    min_amount = models.DecimalField(
        max_digits=15, decimal_places=2,
        default=Decimal("0.00"),
        help_text=_("Minimum fee amount (0 = no minimum)."),
    )
    max_amount = models.DecimalField(
        max_digits=15, decimal_places=2,
        default=Decimal("0.00"),
        help_text=_("Maximum fee amount (0 = no maximum)."),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.get_applied_to_display()})"

    class Meta:
        verbose_name = _("Fee Type")
        verbose_name_plural = _("Fee Types")
        ordering = ["name"]


class Holiday(models.Model):
    """
    Holiday calendar for due date adjustments.
    If a due date falls on a holiday, it can be adjusted to the next working day.
    """
    name = models.CharField(max_length=200)
    date = models.DateField()
    is_recurring = models.BooleanField(
        default=False,
        help_text=_("If True, this holiday occurs every year on the same date."),
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.date})"

    class Meta:
        verbose_name = _("Holiday")
        verbose_name_plural = _("Holidays")
        ordering = ["date"]
        indexes = [
            models.Index(fields=["date"]),
        ]


class CompanySettings(models.Model):
    """
    Singleton model for company-wide configuration.
    Only one row should ever exist — use CompanySettings.get() to access it.
    """
    # Company Information
    company_name            = models.CharField(max_length=200, default="ABA Uganda")
    currency_symbol         = models.CharField(max_length=10, default="UGX",
                                               help_text=_("Currency symbol displayed with amounts."))
    company_address         = models.TextField(blank=True)
    company_phone           = models.CharField(max_length=50, blank=True)
    company_email           = models.EmailField(blank=True)
    company_logo            = models.ImageField(upload_to="company/", null=True, blank=True)
    company_website         = models.URLField(blank=True)
    company_registration    = models.CharField(max_length=100, blank=True, help_text=_("Registration number"))
    tax_identification      = models.CharField(max_length=100, blank=True, help_text=_("TIN number"))

    # Loan Business Rules
    manager_approval_limit  = models.DecimalField(
        max_digits=15, decimal_places=2, default=5_000_000,
        help_text=_("Maximum loan amount a Manager can approve without CEO sign-off (UGX).")
    )
    default_penalty_rate    = models.DecimalField(
        max_digits=5, decimal_places=2, default=2,
        help_text=_("Default monthly penalty rate on overdue amounts (%)."),
    )
    income_multiplier       = models.DecimalField(
        max_digits=4, decimal_places=1, default=3,
        help_text=_("Max loan = monthly income × this multiplier."),
    )
    collateral_haircut      = models.DecimalField(
        max_digits=4, decimal_places=2, default=50,
        help_text=_("Percentage of collateral value used as loan floor (e.g. 50 = 50%)."),
    )

    # Fee Settings
    default_processing_fee_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=1,
        help_text=_("Default loan processing fee as a percentage of loan amount."),
    )
    processing_fee_method = models.CharField(
        max_length=20,
        choices=[("PERCENTAGE", "Percentage"), ("RANGE", "Range")],
        default="PERCENTAGE",
        help_text=_("Choose whether processing fees are calculated using a percentage or amount ranges."),
    )
    processing_fee_ranges = models.TextField(
        blank=True,
        default="",
        help_text=_("Processing fee ranges as 'MIN-MAX:AMOUNT' per line, for example '0-500000:5000'."),
    )
    early_repayment_penalty_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text=_("Penalty for early loan repayment as a percentage of outstanding balance (0 = no penalty)."),
    )
    loan_restructure_fee = models.DecimalField(
        max_digits=15, decimal_places=2, default=10000,
        help_text=_("Flat fee for loan restructuring (UGX)."),
    )

    # Maximum loans per client
    max_active_loans_per_client = models.PositiveSmallIntegerField(
        default=3,
        help_text=_("Maximum number of active loans a client can have simultaneously."),
    )

    # SMS & Communication Settings
    sms_reminders_enabled   = models.BooleanField(default=True)
    reminder_days_before    = models.PositiveSmallIntegerField(
        default=3,
        help_text=_("Days before due date to send payment reminder."),
    )
    sms_sender_id = models.CharField(
        max_length=20, blank=True, default="ABA Uganda",
        help_text=_("Sender ID for SMS messages."),
    )

    # Due Date Adjustment Settings
    adjust_due_dates_for_holidays = models.BooleanField(
        default=True,
        help_text=_("If True, move due dates that fall on holidays to next working day."),
    )
    grace_period_days = models.PositiveSmallIntegerField(
        default=3,
        help_text=_("Number of grace days before marking a payment as overdue."),
    )

    # Savings Settings (for future savings module)
    savings_enabled = models.BooleanField(default=False)
    default_savings_interest_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=3,
        help_text=_("Annual interest rate paid on savings balances (%)."),
    )
    minimum_savings_balance = models.DecimalField(
        max_digits=15, decimal_places=2, default=10000,
        help_text=_("Minimum required savings balance (UGX)."),
    )

    # Share Capital Settings (for future shares module)
    shares_enabled = models.BooleanField(default=False)
    share_price = models.DecimalField(
        max_digits=15, decimal_places=2, default=50000,
        help_text=_("Price per share (UGX)."),
    )
    minimum_shares = models.PositiveSmallIntegerField(
        default=10,
        help_text=_("Minimum number of shares a member must hold."),
    )
    maximum_shares = models.PositiveSmallIntegerField(
        default=1000,
        help_text=_("Maximum number of shares a member can hold."),
    )

    # Dividend Settings
    dividend_frequency = models.CharField(
        max_length=10,
        choices=[
            ("MONTHLY", "Monthly"),
            ("QUARTERLY", "Quarterly"),
            ("ANNUALLY", "Annually"),
        ],
        default="ANNUALLY",
        help_text=_("How often dividends are calculated and distributed."),
    )

    # Risk Management
    max_portfolio_at_risk_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=5,
        help_text=_("Maximum acceptable Portfolio at Risk (PAR) percentage."),
    )
    auto_write_off_days = models.PositiveSmallIntegerField(
        default=180,
        help_text=_("Number of days overdue before a loan is automatically flagged for write-off."),
    )

    # Audit & Tracking
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        "accounts.User", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Company Settings"

    class Meta:
        verbose_name = _("Company Settings")
        verbose_name_plural = _("Company Settings")



class TransactionCategory(models.Model):
    """User-manageable transaction categories (e.g. Operations, Payroll)."""
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    color = models.CharField(
        max_length=20, default="amber",
        help_text=_("Badge colour: teal, amber, red, green, blue, purple"),
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = _("Transaction Category")
        verbose_name_plural = _("Transaction Categories")
        ordering = ["name"]


class ExpenseType(models.Model):
    """Specific expense types nested under a TransactionCategory."""
    category = models.ForeignKey(
        TransactionCategory,
        on_delete=models.PROTECT,
        related_name="expense_types",
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.category.name} — {self.name}"

    class Meta:
        verbose_name = _("Expense Type")
        verbose_name_plural = _("Expense Types")
        ordering = ["category__name", "name"]
        unique_together = [("category", "name")]


class Expense(models.Model):

    class Status(models.TextChoices):
        DRAFT    = "DRAFT",    _("Draft")
        PENDING  = "PENDING",  _("Pending Approval")
        APPROVED = "APPROVED", _("Approved")
        REJECTED = "REJECTED", _("Rejected")

    class PaymentMethod(models.TextChoices):
        CASH         = "CASH",         _("Cash")
        BANK         = "BANK",         _("Bank Transfer")
        MOBILE_MONEY = "MOBILE_MONEY", _("Mobile Money")
        CHEQUE       = "CHEQUE",       _("Cheque")

    reference_number = models.CharField(
        max_length=30, unique=True, blank=True,
        help_text=_("Auto-generated on save, e.g. EXP-2025-00042"),
    )
    category = models.ForeignKey(
        TransactionCategory,
        on_delete=models.PROTECT,
        related_name="expenses",
        null=True, blank=True,
    )
    expense_type = models.ForeignKey(
        ExpenseType,
        on_delete=models.SET_NULL,
        related_name="expenses",
        null=True, blank=True,
    )
    branch = models.ForeignKey(
        "accounts.Branch",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="expenses",
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    expense_date = models.DateField(default=timezone.localdate)
    vendor = models.CharField(max_length=200, blank=True, help_text=_("Supplier / payee name"))
    payment_method = models.CharField(
        max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.CASH,
    )
    receipt_number = models.CharField(max_length=100, blank=True, help_text=_("Supplier receipt or cheque number"))
    description = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.APPROVED)
    approved_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="approved_expenses",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="created_expenses",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.reference_number:
            year = self.expense_date.year if self.expense_date else timezone.localdate().year
            last = Expense.objects.filter(
                reference_number__startswith=f"EXP-{year}-"
            ).order_by("-reference_number").first()
            seq = 1
            if last and last.reference_number:
                try:
                    seq = int(last.reference_number.split("-")[-1]) + 1
                except ValueError:
                    pass
            self.reference_number = f"EXP-{year}-{seq:05d}"
        super().save(*args, **kwargs)

    def __str__(self):
        cat = self.category.name if self.category else "Uncategorised"
        return f"{self.reference_number} — {cat} UGX {self.amount:,.0f}"

    class Meta:
        verbose_name = _("Expense")
        verbose_name_plural = _("Expenses")
        ordering = ["-expense_date", "-created_at"]
        indexes = [
            models.Index(fields=["expense_date"]),
            models.Index(fields=["category"]),
            models.Index(fields=["status"]),
        ]


class CapitalInjection(models.Model):
    source = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    injected_date = models.DateField(default=timezone.localdate)
    investor = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="created_injections",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Capital injection UGX {self.amount:,.0f} from {self.source} on {self.injected_date}"

    class Meta:
        verbose_name = _("Capital Injection")
        verbose_name_plural = _("Capital Injections")
        ordering = ["-injected_date", "-created_at"]
        indexes = [models.Index(fields=["injected_date"])]


class BankAccount(models.Model):
    """Institution's own bank accounts for tracking balances and reconciliation."""

    class AccountType(models.TextChoices):
        CURRENT  = "CURRENT",  _("Current Account")
        SAVINGS  = "SAVINGS",  _("Savings Account")
        FIXED    = "FIXED",    _("Fixed Deposit")
        MOBILE   = "MOBILE",   _("Mobile Money")

    account_name   = models.CharField(max_length=200)
    account_number = models.CharField(max_length=50, unique=True)
    bank_name      = models.CharField(max_length=200)
    branch_name    = models.CharField(max_length=200, blank=True)
    account_type   = models.CharField(max_length=10, choices=AccountType.choices, default=AccountType.CURRENT)
    currency       = models.CharField(max_length=10, default="UGX")
    opening_balance = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    current_balance = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    is_active      = models.BooleanField(default=True)
    notes          = models.TextField(blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.account_name} — {self.bank_name} ({self.account_number})"

    class Meta:
        verbose_name = _("Bank Account")
        verbose_name_plural = _("Bank Accounts")
        ordering = ["bank_name", "account_name"]


class BankTransaction(models.Model):
    class TransactionType(models.TextChoices):
        CREDIT = "CREDIT", _("Credit")
        DEBIT = "DEBIT", _("Debit")

    branch = models.ForeignKey(
        "accounts.Branch",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="bank_transactions",
    )
    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.PROTECT,
        related_name="transactions",
    )
    category = models.CharField(max_length=200, blank=True)
    transaction_type = models.CharField(
        max_length=10,
        choices=TransactionType.choices,
        default=TransactionType.CREDIT,
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    transaction_date = models.DateTimeField(default=timezone.now)
    reference_number = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="bank_transactions_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_transaction_type_display()} UGX {self.amount:,.0f} — {self.bank_account}"

    class Meta:
        verbose_name = _("Bank Transaction")
        verbose_name_plural = _("Bank Transactions")
        ordering = ["-transaction_date", "bank_account"]
        indexes = [
            models.Index(fields=["transaction_date"]),
            models.Index(fields=["branch"]),
            models.Index(fields=["transaction_type"]),
        ]


class AuditLog(models.Model):
    """
    Detailed audit trail for important actions in the system.
    This complements django-auditlog by capturing business-level events.
    """
    class Action(models.TextChoices):
        CREATE = "CREATE", _("Create")
        UPDATE = "UPDATE", _("Update")
        DELETE = "DELETE", _("Delete")
        APPROVE = "APPROVE", _("Approve")
        REJECT = "REJECT", _("Reject")
        DISBURSE = "DISBURSE", _("Disburse")
        PAYMENT = "PAYMENT", _("Payment")
        REVERSE = "REVERSE", _("Reverse")
        WAIVE = "WAIVE", _("Waive")
        RESTRUCTURE = "RESTRUCTURE", _("Restructure")
        WRITE_OFF = "WRITE_OFF", _("Write Off")
        LOGIN = "LOGIN", _("Login")
        LOGOUT = "LOGOUT", _("Logout")
        OTHER = "OTHER", _("Other")

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    entity_type = models.CharField(max_length=100, help_text=_("Type of entity affected, e.g., Loan, Client"))
    entity_id = models.CharField(max_length=100, help_text=_("ID of the entity affected"))
    entity_repr = models.CharField(max_length=500, help_text=_("String representation of the entity"))
    changes = models.JSONField(
        default=dict, blank=True,
        help_text=_("JSON representation of changes made"),
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    remarks = models.TextField(blank=True, help_text=_("Additional notes about this action"))
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        return f"{self.get_action_display()} - {self.entity_type} #{self.entity_id} by {self.user}"

    class Meta:
        verbose_name = _("Audit Log")
        verbose_name_plural = _("Audit Logs")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["entity_type", "entity_id"]),
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["action"]),
        ]


class ReceiptSequence(models.Model):
    """Concurrency-safe sequence counter for receipt numbers."""
    name = models.CharField(max_length=32, unique=True)
    last = models.PositiveBigIntegerField(default=0)

    def __str__(self):
        return f"{self.name}:{self.last}"


class SystemParameter(models.Model):
    """
    Key-value store for system-wide parameters that may need to be adjusted
    without code changes. Useful for feature flags and configuration values.
    """
    key = models.CharField(max_length=100, unique=True)
    value = models.TextField(help_text=_("Parameter value (stored as text)"))
    value_type = models.CharField(
        max_length=20,
        choices=[
            ("STRING", "String"),
            ("INTEGER", "Integer"),
            ("DECIMAL", "Decimal"),
            ("BOOLEAN", "Boolean"),
            ("JSON", "JSON"),
        ],
        default="STRING",
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
    )

    def get_typed_value(self):
        """Return the value converted to the appropriate type."""
        if self.value_type == "INTEGER":
            return int(self.value)
        elif self.value_type == "DECIMAL":
            return Decimal(self.value)
        elif self.value_type == "BOOLEAN":
            return self.value.lower() in ("true", "1", "yes")
        elif self.value_type == "JSON":
            import json
            return json.loads(self.value)
        return self.value

    def __str__(self):
        return f"{self.key} = {self.value}"

    class Meta:
        verbose_name = _("System Parameter")
        verbose_name_plural = _("System Parameters")
        ordering = ["key"]