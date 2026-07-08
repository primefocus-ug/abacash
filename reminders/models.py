"""
reminders/models.py
===================
Tracks every automated SMS and WhatsApp reminder sent to clients.

Models
------
ReminderLog     – one row per message attempt (success or failure)
ReminderSetting – per-loan override for reminder behaviour

Design notes
------------
* The Celery beat task (reminders/tasks.py) inserts a ReminderLog row for
  every message it attempts.  On success the status is SENT; on Africa's
  Talking / Twilio API failure the status is FAILED with the error stored.

* We never delete ReminderLog rows — they are the audit trail proving that
  a client was notified before being reported as a defaulter.

* ReminderSetting allows staff to suppress reminders for a specific loan
  (e.g. client is in hospital, CEO has agreed to pause reminders temporarily).
"""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class ReminderLog(models.Model):
    """
    A record of every SMS or WhatsApp reminder message sent (or attempted).
    """

    class Channel(models.TextChoices):
        SMS       = "SMS",      _("SMS")
        WHATSAPP  = "WHATSAPP", _("WhatsApp")

    class Status(models.TextChoices):
        SENT    = "SENT",    _("Sent Successfully")
        FAILED  = "FAILED",  _("Failed")
        PENDING = "PENDING", _("Pending / Queued")

    class TriggerType(models.TextChoices):
        DUE_IN_3_DAYS = "DUE_3D",   _("Due in 3 Days")
        DUE_TOMORROW  = "DUE_1D",   _("Due Tomorrow")
        DUE_TODAY     = "DUE_TODAY", _("Due Today")
        OVERDUE_1D    = "OVD_1D",   _("Overdue 1 Day")
        OVERDUE_WEEK  = "OVD_7D",   _("Overdue 7+ Days")
        MANUAL        = "MANUAL",   _("Manually Triggered")

    # ------------------------------------------------------------------ #
    # Relationships                                                        #
    # ------------------------------------------------------------------ #

    loan = models.ForeignKey(
        "loans.Loan",
        on_delete=models.PROTECT,
        related_name="reminder_logs",
    )

    client = models.ForeignKey(
        "clients.Client",
        on_delete=models.PROTECT,
        related_name="reminder_logs",
    )

    # The schedule entry this reminder relates to (can be null for general reminders)
    schedule_entry = models.ForeignKey(
        "loans.LoanSchedule",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="reminder_logs",
    )

    # Who triggered this if it was a manual send
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="triggered_reminders",
    )

    # ------------------------------------------------------------------ #
    # Message details                                                      #
    # ------------------------------------------------------------------ #

    channel      = models.CharField(max_length=10, choices=Channel.choices)
    trigger_type = models.CharField(max_length=10, choices=TriggerType.choices)

    # The phone number the message was sent to
    recipient_phone = models.CharField(max_length=20)

    # Full text of the message as sent
    message_body = models.TextField()

    # ------------------------------------------------------------------ #
    # Status & error tracking                                              #
    # ------------------------------------------------------------------ #

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    # Africa's Talking / Twilio message ID for tracking delivery
    provider_message_id = models.CharField(max_length=100, blank=True)

    # If FAILED, store the full error message for debugging
    error_message = models.TextField(blank=True)

    sent_at    = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return (
            f"{self.get_channel_display()} to {self.recipient_phone} "
            f"({self.get_status_display()}) — {self.loan.loan_number}"
        )

    class Meta:
        verbose_name = _("Reminder Log")
        verbose_name_plural = _("Reminder Logs")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["loan", "channel", "status"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["status"]),
        ]


class ReminderSetting(models.Model):
    """
    Per-loan override for automated reminder behaviour.

    By default all active loans receive reminders.
    A manager or CEO can suppress reminders for a specific loan
    for a defined period (e.g. while a dispute is being resolved).
    """

    loan = models.OneToOneField(
        "loans.Loan",
        on_delete=models.CASCADE,
        related_name="reminder_setting",
    )

    # If False, no automated reminders will be sent for this loan
    reminders_enabled = models.BooleanField(default=True)

    # Optional: suppress until a specific date
    suppressed_until = models.DateField(
        null=True, blank=True,
        help_text=_("If set, reminders are suppressed until this date."),
    )

    suppression_reason = models.TextField(
        blank=True,
        help_text=_("Reason reminders were paused — required when suppressing."),
    )

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True, blank=True,
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        status = "enabled" if self.reminders_enabled else "suppressed"
        return f"Reminders {status} — {self.loan.loan_number}"

    class Meta:
        verbose_name = _("Reminder Setting")
        verbose_name_plural = _("Reminder Settings")
