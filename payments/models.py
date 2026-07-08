import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Payment(models.Model):

    class PaymentMethod(models.TextChoices):
        CASH         = "CASH",   _("Cash")
        MOBILE_MONEY = "MOMO",   _("Mobile Money (MTN/Airtel)")
        BANK         = "BANK",   _("Bank Transfer")
        OTHER        = "OTHER",  _("Other")

    class Status(models.TextChoices):
        PENDING   = "PENDING",   _("Pending Allocation")
        ALLOCATED = "ALLOCATED", _("Allocated")
        REVERSED  = "REVERSED",  _("Reversed")
    # ------------------------------------------------------------------ #
    # Identity                                                             #
    # ------------------------------------------------------------------ #

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # ------------------------------------------------------------------ #
    # Relationships                                                        #
    # ------------------------------------------------------------------ #

    loan = models.ForeignKey(
        "loans.Loan",
        on_delete=models.PROTECT,
        related_name="payments",
    )

    # Denormalised for speed — avoids joining through Loan on every query
    client = models.ForeignKey(
        "clients.Client",
        on_delete=models.PROTECT,
        related_name="payments",
    )

    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recorded_payments",
        help_text=_("Cashier who received and recorded this payment."),
    )

    # If a payment is reversed, who authorised it
    reversed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reversed_payments",
        null=True, blank=True,
    )

    # ------------------------------------------------------------------ #
    # Financial details                                                    #
    # ------------------------------------------------------------------ #

    amount_received = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        help_text=_("Actual cash amount received in UGX."),
    )

    # Breakdown of how the amount was allocated (filled by allocation service)
    principal_paid  = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0"))
    interest_paid   = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0"))
    penalty_paid    = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0"))

    # Any amount above what was due — will be applied to the next period
    overpayment     = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0"))

    payment_method  = models.CharField(
        max_length=10,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH,
    )

    # External reference: mobile money transaction ID, bank ref, etc.
    reference_number = models.CharField(
        max_length=100,
        blank=True,
        help_text=_("Mobile money or bank transaction reference number."),
    )

    payment_date = models.DateField(
        default=timezone.localdate,
        help_text=_("Date the payment was physically received."),
    )

    # ------------------------------------------------------------------ #
    # Status                                                               #
    # ------------------------------------------------------------------ #

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    reversal_reason = models.TextField(
        blank=True,
        help_text=_("Reason for reversal — required when status = REVERSED."),
    )
    reversal_date   = models.DateField(null=True, blank=True)

    notes      = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ------------------------------------------------------------------ #
    # Methods                                                              #
    # ------------------------------------------------------------------ #

    def __str__(self):
        return (
            f"Payment UGX {self.amount_received:,.0f} on {self.payment_date} "
            f"— {self.loan.loan_number}"
        )

    class Meta:
        verbose_name = _("Payment")
        verbose_name_plural = _("Payments")
        ordering = ["-payment_date", "-created_at"]
        indexes = [
            models.Index(fields=["loan", "payment_date"]),
            models.Index(fields=["recorded_by", "payment_date"]),
            models.Index(fields=["status"]),
        ]


class Receipt(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Human-readable number shown on the printed receipt
    receipt_number = models.CharField(max_length=25, unique=True, editable=False)

    payment = models.OneToOneField(
        Payment,
        on_delete=models.PROTECT,
        related_name="receipt",
    )

    # Snapshot of loan balance AT THE TIME of this payment
    balance_before = models.DecimalField(max_digits=15, decimal_places=2)
    balance_after  = models.DecimalField(max_digits=15, decimal_places=2)
    # Snapshot of how the payment was allocated at time of issue
    amount_received = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    principal_paid  = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    interest_paid   = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    penalty_paid    = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    overpayment     = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))

    issued_at = models.DateTimeField(auto_now_add=True)

    # Whether a physical copy was printed
    printed    = models.BooleanField(default=False)
    printed_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        """Auto-generate receipt_number before first save (concurrency-safe)."""
        if not self.receipt_number:
            from django.db import transaction
            from accounts.models import ReceiptSequence

            year = timezone.now().year
            key = f"receipts_{year}"
            with transaction.atomic():
                ReceiptSequence.objects.get_or_create(name=key, defaults={"last": 0})
                seq_row = ReceiptSequence.objects.select_for_update().get(name=key)
                # Self-heal: if DB has receipts beyond the sequence counter, catch up.
                prefix = f"REC-{year}-"
                last_in_db = (
                    Receipt.objects.filter(receipt_number__startswith=prefix)
                    .order_by("-receipt_number")
                    .values_list("receipt_number", flat=True)
                    .first()
                )
                if last_in_db:
                    last_num = int(last_in_db.split("-")[-1])
                    if last_num >= seq_row.last:
                        seq_row.last = last_num
                seq_row.last += 1
                seq_row.save(update_fields=["last"])
                self.receipt_number = f"REC-{year}-{seq_row.last:05d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.receipt_number} — {self.payment}"

    class Meta:
        verbose_name = _("Receipt")
        verbose_name_plural = _("Receipts")
        ordering = ["-issued_at"]