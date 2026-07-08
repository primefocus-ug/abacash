"""
reminders/tasks.py
==================
Celery tasks for automated SMS and WhatsApp reminders.

Schedule (set in Django admin under Periodic Tasks after running migrations):
  check_due_payments  →  every day at 08:00 Africa/Kampala

Windows local dev: start worker with eventlet
  celery -A aba_uganda worker --loglevel=info --pool=eventlet
  celery -A aba_uganda beat   --loglevel=info

VPS production:
  Managed by Supervisor (see deployment guide).
"""

from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from django_tenants.utils import get_tenant_model, tenant_context


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def _send_sms(phone: str, message: str) -> tuple[bool, str]:
    """
    Send an SMS via Africa's Talking.
    Returns (success: bool, provider_message_id or error: str).
    """
    try:
        import africastalking
        africastalking.initialize(
            username=settings.AT_USERNAME,
            api_key=settings.AT_API_KEY,
        )
        sms      = africastalking.SMS
        response = sms.send(message, [phone], sender_id=settings.AT_SENDER_ID)
        recipients = response.get("SMSMessageData", {}).get("Recipients", [])
        if recipients and recipients[0].get("status") == "Success":
            return True, recipients[0].get("messageId", "")
        return False, str(response)
    except Exception as e:
        return False, str(e)


def _send_whatsapp(phone: str, message: str) -> tuple[bool, str]:
    """
    Send a WhatsApp message via Twilio.
    Phone must be in format +256XXXXXXXXX.
    """
    try:
        from twilio.rest import Client as TwilioClient
        client = TwilioClient(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        msg = client.messages.create(
            body=message,
            from_=settings.TWILIO_WHATSAPP_FROM,
            to=f"whatsapp:{phone}",
        )
        return True, msg.sid
    except Exception as e:
        return False, str(e)


def _log_reminder(loan, client, schedule_entry, channel, trigger_type, phone, body, success, provider_id, error):
    """Create a ReminderLog row regardless of success/failure."""
    from reminders.models import ReminderLog
    ReminderLog.objects.create(
        loan                = loan,
        client              = client,
        schedule_entry      = schedule_entry,
        channel             = channel,
        trigger_type        = trigger_type,
        recipient_phone     = phone,
        message_body        = body,
        status              = "SENT" if success else "FAILED",
        provider_message_id = provider_id if success else "",
        error_message       = error if not success else "",
        sent_at             = timezone.now() if success else None,
    )


# ------------------------------------------------------------------ #
# Main daily task                                                      #
# ------------------------------------------------------------------ #

@shared_task(name="reminders.check_due_payments", bind=True, max_retries=1)
def check_due_payments(self):
    """
    Daily task: scan all active loan schedules and send SMS/WhatsApp reminders.

    Runs once per tenant. Celery tasks execute outside the request/response
    cycle, so TenantMainMiddleware never runs for them — the DB connection's
    schema has to be set explicitly here, per tenant, or queries against
    tenant-only models (like LoanSchedule) will hit the wrong schema or fail
    outright.

    Triggers:
      - DUE_3D   : payment due in exactly 3 days → SMS
      - DUE_1D   : payment due tomorrow          → SMS
      - DUE_TODAY: payment due today             → SMS
      - OVD_1D   : payment 1+ days overdue       → SMS + WhatsApp
    """
    TenantModel = get_tenant_model()
    results = {}

    for tenant in TenantModel.objects.exclude(schema_name="public"):
        try:
            with tenant_context(tenant):
                results[tenant.schema_name] = _check_due_payments_for_tenant()
        except Exception as e:
            # One tenant's failure shouldn't stop reminders going out to
            # everyone else.
            results[tenant.schema_name] = {"error": str(e)}

    return results


def _check_due_payments_for_tenant():
    """Runs entirely inside a single tenant's schema (see tenant_context above)."""
    from loans.models import LoanSchedule
    from reminders.models import ReminderLog, ReminderSetting

    today = timezone.localdate()

    triggers = [
        ("DUE_3D",    today + timedelta(days=3), "SMS"),
        ("DUE_1D",    today + timedelta(days=1), "SMS"),
        ("DUE_TODAY", today,                     "SMS"),
    ]

    sent_count    = 0
    failed_count  = 0

    for trigger_type, target_date, channel in triggers:
        entries = LoanSchedule.objects.filter(
            due_date=target_date,
            status__in=["PENDING", "PARTIAL"],
            loan__status="ACTIVE",
        ).select_related("loan__client", "loan")

        for entry in entries:
            loan   = entry.loan
            client = loan.client

            # Check if reminders are suppressed for this loan
            try:
                setting = loan.reminder_setting
                if not setting.reminders_enabled:
                    continue
                if setting.suppressed_until and setting.suppressed_until >= today:
                    continue
            except ReminderSetting.DoesNotExist:
                pass

            phone   = client.phone_primary
            amount  = f"UGX {int(entry.total_payment - entry.amount_paid):,}"
            due_str = entry.due_date.strftime("%d %b %Y")

            message = (
                f"Dear {client.first_name}, your loan payment of {amount} "
                f"for loan {loan.loan_number} is due on {due_str}. "
                f"Please pay on time to avoid penalties. "
                f"ABA Uganda — 0700000000."
            )

            success, provider_id = _send_sms(phone, message)
            _log_reminder(
                loan, client, entry, "SMS", trigger_type,
                phone, message, success, provider_id,
                "" if success else provider_id,
            )

            if success:
                sent_count += 1
            else:
                failed_count += 1

    # Overdue entries — SMS + WhatsApp
    overdue_entries = list(LoanSchedule.objects.filter(
        due_date__lt=today,
        status__in=["PENDING", "PARTIAL", "OVERDUE"],
        loan__status="ACTIVE",
    ).select_related("loan__client", "loan"))

    # Mark pending entries as OVERDUE now that we have the list
    LoanSchedule.objects.filter(
        due_date__lt=today,
        status="PENDING",
        loan__status="ACTIVE",
    ).update(status="OVERDUE")

    for entry in overdue_entries:
        loan   = entry.loan
        client = loan.client

        try:
            setting = loan.reminder_setting
            if not setting.reminders_enabled:
                continue
            if setting.suppressed_until and setting.suppressed_until >= today:
                continue
        except Exception:
            pass

        days_late = (today - entry.due_date).days
        phone     = client.phone_primary
        amount    = f"UGX {int(entry.total_payment - entry.amount_paid):,}"

        # SMS
        sms_body = (
            f"OVERDUE NOTICE: Dear {client.first_name}, loan {loan.loan_number} "
            f"has a payment of {amount} that is {days_late} day(s) overdue. "
            f"Please pay immediately to avoid further penalties. ABA Uganda."
        )
        success, pid = _send_sms(phone, sms_body)
        _log_reminder(loan, client, entry, "SMS", "OVD_1D",
                      phone, sms_body, success, pid, "" if success else pid)
        if success:
            sent_count += 1
        else:
            failed_count += 1

        # WhatsApp (only for 3+ days overdue to reduce noise)
        if days_late >= 3:
            wa_body = (
                f"*ABA Uganda — Overdue Notice*\n\n"
                f"Dear {client.first_name},\n\n"
                f"Your loan *{loan.loan_number}* has an outstanding payment "
                f"of *{amount}* that is *{days_late} days overdue*.\n\n"
                f"Please contact us immediately or visit our office to avoid "
                f"further penalties and legal action.\n\n"
                f"ABA Uganda — 0700000000"
            )
            success, pid = _send_whatsapp(phone, wa_body)
            _log_reminder(loan, client, entry, "WHATSAPP", "OVD_1D",
                          phone, wa_body, success, pid, "" if success else pid)
            if success:
                sent_count += 1
            else:
                failed_count += 1

    return {
        "date":   str(today),
        "sent":   sent_count,
        "failed": failed_count,
    }