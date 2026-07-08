"""
clients/models.py
=================
Everything related to a loan client (borrower) at ABA Uganda.

Models
------
Client          – the person borrowing money
NextOfKin       – emergency contact for the client
ClientDocument  – uploaded ID scans or supporting documents

Design notes
------------
* Phone numbers are stored as plain strings (Uganda format: +256XXXXXXXXX).
  Validation is done in forms/serializers, not at the model level, so that
  imported data with slightly different formats does not break migrations.

* NIN (National Identification Number) is unique per client and indexed.

* All monetary fields (monthly_income) use DecimalField with max_digits=15
  and decimal_places=2 — never FloatField for currency.
"""

import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


def client_document_path(instance, filename):
    """Upload path: documents/client_<uuid>/<filename>"""
    return f"documents/client_{instance.client.id}/{filename}"


def client_photo_path(instance, filename):
    """Upload path: photos/client_<uuid>/<filename>"""
    return f"photos/client_{instance.id}/{filename}"


class Client(models.Model):
    """
    A borrower registered at ABA Uganda.
    One client can have multiple loans over time.
    """

    class Gender(models.TextChoices):
        MALE   = "M", _("Male")
        FEMALE = "F", _("Female")
        OTHER  = "O", _("Other")

    class MaritalStatus(models.TextChoices):
        SINGLE   = "SINGLE",   _("Single")
        MARRIED  = "MARRIED",  _("Married")
        DIVORCED = "DIVORCED", _("Divorced")
        WIDOWED  = "WIDOWED",  _("Widowed")

    class EmploymentStatus(models.TextChoices):
        EMPLOYED    = "EMPLOYED",    _("Employed")
        SELF_EMPLOYED = "SELF_EMPLOYED", _("Self-Employed")
        BUSINESS    = "BUSINESS",    _("Business Owner")
        UNEMPLOYED  = "UNEMPLOYED",  _("Unemployed")
        OTHER       = "OTHER",       _("Other")

    # ------------------------------------------------------------------ #
    # Identity                                                             #
    # ------------------------------------------------------------------ #

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text=_("Internal unique identifier."),
    )

    # Human-readable reference shown in the UI, e.g. CLT-00042
    client_number = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        help_text=_("Auto-generated client reference number."),
    )

    first_name = models.CharField(max_length=100)
    last_name  = models.CharField(max_length=100)
    other_names = models.CharField(max_length=100, blank=True)

    gender         = models.CharField(max_length=1,  choices=Gender.choices)
    date_of_birth  = models.DateField()
    marital_status = models.CharField(max_length=10, choices=MaritalStatus.choices)

    # Uganda National Identification Number — 14 alphanumeric characters
    nin = models.CharField(
        max_length=20,
        unique=True,
        db_index=True,
        verbose_name=_("National ID Number (NIN)"),
        help_text=_("14-character Uganda NIN, e.g. CF20100122XXXXX"),
    )

    # ------------------------------------------------------------------ #
    # Contact                                                              #
    # ------------------------------------------------------------------ #

    phone_primary   = models.CharField(
        max_length=20,
        help_text=_("Primary phone, Uganda format: +256XXXXXXXXX"),
    )
    phone_secondary = models.CharField(max_length=20, blank=True)
    email           = models.EmailField(blank=True)

    physical_address = models.TextField(
        help_text=_("Full physical address including LC1 area and district.")
    )
    district = models.CharField(max_length=100, default="Kampala")

    # ------------------------------------------------------------------ #
    # Employment & income                                                  #
    # ------------------------------------------------------------------ #

    employment_status = models.CharField(
        max_length=15,
        choices=EmploymentStatus.choices,
        default=EmploymentStatus.EMPLOYED,
    )
    employer_name    = models.CharField(max_length=200, blank=True)
    employer_address = models.TextField(blank=True)
    job_title        = models.CharField(max_length=100, blank=True)

    # Monthly income in UGX — use DecimalField, never FloatField
    monthly_income = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=0,
        help_text=_("Gross monthly income in UGX."),
    )

    credit_balance = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0"),
        help_text=_("Credit balance created from overpayments and retained for future use."),
    )

    # ------------------------------------------------------------------ #
    # Status & audit                                                       #
    # ------------------------------------------------------------------ #

    is_active = models.BooleanField(
        default=True,
        help_text=_("Inactive clients cannot apply for new loans."),
    )
    is_blacklisted = models.BooleanField(
        default=False,
        help_text=_("Blacklisted clients are blocked from all loan applications."),
    )
    blacklist_reason = models.TextField(blank=True)

    # The staff member who registered this client
    registered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="registered_clients",
        null=True,
        blank=True,
    )

    passport_photo = models.ImageField(
        upload_to=client_photo_path,
        null=True,
        blank=True,
        help_text=_("Recent passport-size photograph of the client."),
    )

    notes      = models.TextField(blank=True, help_text=_("Internal staff notes."))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ------------------------------------------------------------------ #
    # Methods                                                              #
    # ------------------------------------------------------------------ #

    def save(self, *args, **kwargs):
        """Auto-generate client_number on first save."""
        if not self.client_number:
            from django.db import transaction
            with transaction.atomic():
                last = Client.objects.select_for_update().order_by("-created_at").filter(
                    client_number__startswith="CLT-"
                ).first()
                if last:
                    try:
                        seq = int(last.client_number.split("-")[1]) + 1
                    except (IndexError, ValueError):
                        seq = 1
                else:
                    seq = 1
                self.client_number = f"CLT-{seq:05d}"
        super().save(*args, **kwargs)

    @property
    def full_name(self):
        parts = [self.first_name, self.other_names, self.last_name]
        return " ".join(p for p in parts if p).strip()

    @property
    def active_loan_count(self):
        """Number of currently active loans."""
        return self.loans.filter(status="ACTIVE").count()

    def __str__(self):
        return f"{self.full_name} ({self.client_number})"

    class Meta:
        verbose_name = _("Client")
        verbose_name_plural = _("Clients")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["nin"]),
            models.Index(fields=["phone_primary"]),
            models.Index(fields=["last_name", "first_name"]),
        ]


class CreditTransaction(models.Model):
    """
    Immutable ledger of every movement on a client's credit balance.
    Never update or delete rows — append only.
    """

    class TxType(models.TextChoices):
        OVERPAYMENT = "OVERPAYMENT", _("Overpayment Received")
        APPLIED     = "APPLIED",     _("Applied to Loan")
        REFUNDED    = "REFUNDED",    _("Refunded to Client")
        WRITTEN_OFF = "WRITTEN_OFF", _("Written Off to Income")
        ADJUSTMENT  = "ADJUSTMENT",  _("Manual Adjustment")

    client      = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="credit_transactions")
    tx_type     = models.CharField(max_length=20, choices=TxType.choices)
    amount      = models.DecimalField(max_digits=15, decimal_places=2,
                                      help_text=_("Positive = credit added, Negative = credit used/removed"))
    balance_after = models.DecimalField(max_digits=15, decimal_places=2)
    loan        = models.ForeignKey("loans.Loan", on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name="credit_transactions")
    payment     = models.ForeignKey("payments.Payment", on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name="credit_transactions")
    notes       = models.TextField(blank=True)
    created_by  = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                    null=True, blank=True, related_name="credit_transactions_created")
    created_at  = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_tx_type_display()} UGX {self.amount:,.0f} — {self.client}"

    class Meta:
        verbose_name = _("Credit Transaction")
        verbose_name_plural = _("Credit Transactions")
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["client", "created_at"])]


class NextOfKin(models.Model):
    """
    Emergency contact / guarantor for a client.
    A client can have multiple next-of-kin records,
    but at least one is required before loan approval.
    """

    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name="next_of_kin",
    )

    full_name    = models.CharField(max_length=200)
    relationship = models.CharField(
        max_length=50,
        help_text=_("E.g. Spouse, Parent, Sibling, Friend"),
    )
    phone_primary   = models.CharField(max_length=20)
    phone_secondary = models.CharField(max_length=20, blank=True)
    physical_address = models.TextField()

    is_guarantor = models.BooleanField(
        default=False,
        help_text=_("Check if this person is also acting as loan guarantor."),
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.full_name} ({self.relationship}) — {self.client}"

    class Meta:
        verbose_name = _("Next of Kin")
        verbose_name_plural = _("Next of Kin")


class ClientDocument(models.Model):
    """
    Scanned ID, payslip, or any supporting document for a client.
    Files are stored under MEDIA_ROOT/documents/client_<uuid>/.
    """

    class DocumentType(models.TextChoices):
        NATIONAL_ID   = "NIN",      _("National ID Card")
        PASSPORT      = "PASSPORT", _("Passport")
        DRIVERS_LICENCE = "DRIVING", _("Driving Licence")
        PAYSLIP       = "PAYSLIP",  _("Payslip")
        UTILITY_BILL  = "UTILITY",  _("Utility Bill")
        OTHER         = "OTHER",    _("Other")

    client        = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="documents")
    document_type = models.CharField(max_length=10, choices=DocumentType.choices)
    file          = models.FileField(upload_to=client_document_path)
    description   = models.CharField(max_length=255, blank=True)
    uploaded_by   = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True, blank=True,
    )
    uploaded_at   = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_document_type_display()} — {self.client}"

    class Meta:
        verbose_name = _("Client Document")
        verbose_name_plural = _("Client Documents")
        ordering = ["-uploaded_at"]