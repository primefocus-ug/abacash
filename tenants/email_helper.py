"""
Notification emails for platform operators.

Previously new-signup notifications went through mail_admins(), which is a
silent no-op unless settings.ADMINS is populated — and it never was, so
operators simply never heard about new registrations. This module sends a
real HTML+text email to a concrete recipient list instead.
"""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def notification_recipients():
    """Who gets platform notification emails.

    Defaults to active PlatformAdmin emails so new operators start
    receiving notifications automatically as soon as they're added — no
    separate settings.py edit required. Can be overridden with an explicit
    PLATFORM_NOTIFICATION_EMAILS list in settings for cases where you want
    notifications to go somewhere other than the operator accounts.
    """
    override = getattr(settings, "PLATFORM_NOTIFICATION_EMAILS", None)
    if override:
        return list(override)

    from .models import PlatformAdmin

    return list(
        PlatformAdmin.objects.filter(is_active=True)
        .exclude(email="")
        .values_list("email", flat=True)
    )


def _send(subject, template_base, context, recipients):
    if not recipients:
        logger.warning(
            "Skipping notification email '%s' — no recipients configured "
            "(no active PlatformAdmin has an email, and "
            "PLATFORM_NOTIFICATION_EMAILS is not set).",
            subject,
        )
        return False

    text_body = render_to_string(f"emails/{template_base}.txt", context)
    html_body = render_to_string(f"emails/{template_base}.html", context)
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@abacash.loan")

    message = EmailMultiAlternatives(subject, text_body, from_email, recipients)
    message.attach_alternative(html_body, "text/html")
    try:
        message.send(fail_silently=False)
        return True
    except Exception:
        logger.exception("Failed to send notification email '%s'", subject)
        return False


def _registration_detail_url(registration):
    site_url = getattr(settings, "SITE_URL", "https://abacash.loan").rstrip("/")
    return f"{site_url}/public-admin/registrations/{registration.pk}/"


def notify_new_registration(registration):
    """Sent the moment a company submits the public registration form."""
    context = {
        "reg": registration,
        "detail_url": _registration_detail_url(registration),
    }
    subject = f"New registration: {registration.company_name} ({registration.get_plan_display()})"
    return _send(subject, "new_registration", context, notification_recipients())


def notify_onboarding_result(registration, *, success, error=None):
    """Sent when a provisioning attempt (auto or manual) finishes, so
    operators find out about a failure without a customer having to
    complain first."""
    context = {
        "reg": registration,
        "success": success,
        "error": error,
        "detail_url": _registration_detail_url(registration),
    }
    prefix = "Onboarded" if success else "Onboarding failed"
    subject = f"{prefix}: {registration.company_name}"
    return _send(subject, "onboarding_result", context, notification_recipients())