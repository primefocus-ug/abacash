"""
accounts/audit.py
=================
Lightweight helper to write business-level audit log entries.

Usage:
    from accounts.audit import log_action
    from accounts.models import AuditLog

    log_action(request.user, AuditLog.Action.APPROVE, loan, request=request,
               changes={"status": ["PENDING", "ACTIVE"]})
"""

from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver
from accounts.models import AuditLog


def _get_ip(request):
    if not request:
        return None
    x_fwd = request.META.get("HTTP_X_FORWARDED_FOR")
    return x_fwd.split(",")[0].strip() if x_fwd else request.META.get("REMOTE_ADDR")


@receiver(user_logged_in)
def _on_login(sender, request, user, **kwargs):
    AuditLog.objects.create(
        user=user,
        action=AuditLog.Action.LOGIN,
        entity_type="User",
        entity_id=str(user.pk),
        entity_repr=str(user),
        changes={},
        ip_address=_get_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "") if request else "",
        remarks=f"Login by {user.get_full_name() or user.username}",
    )


@receiver(user_logged_out)
def _on_logout(sender, request, user, **kwargs):
    if user:
        AuditLog.objects.create(
            user=user,
            action=AuditLog.Action.LOGOUT,
            entity_type="User",
            entity_id=str(user.pk),
            entity_repr=str(user),
            changes={},
            ip_address=_get_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", "") if request else "",
            remarks=f"Logout by {user.get_full_name() or user.username}",
        )


def log_action(user, action, entity, changes=None, request=None, remarks=""):
    """
    Create an AuditLog entry for a business-level event.

    Parameters
    ----------
    user     : User instance (the actor)
    action   : AuditLog.Action choice string
    entity   : any model instance (Loan, Payment, etc.)
    changes  : dict describing what changed, e.g. {"status": ["old", "new"]}
    request  : HttpRequest — used to capture IP and user-agent
    remarks  : optional free-text note
    """
    ip = None
    ua = ""
    if request:
        x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        ip = x_forwarded.split(",")[0].strip() if x_forwarded else request.META.get("REMOTE_ADDR")
        ua = request.META.get("HTTP_USER_AGENT", "")

    entity_id = str(entity.pk) if entity.pk is not None else ""

    AuditLog.objects.create(
        user=user,
        action=action,
        entity_type=entity.__class__.__name__,
        entity_id=entity_id,
        entity_repr=str(entity)[:500],
        changes=changes or {},
        ip_address=ip,
        user_agent=ua,
        remarks=remarks,
    )