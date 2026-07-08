"""
Custom Django template filters for ABA Uganda.

Templates use:
    {% load aba_filters %}
"""

from decimal import Decimal, InvalidOperation

from django import template

from accounts.models import CompanySettings

register = template.Library()


def get_currency_symbol():
    try:
        return CompanySettings.get().currency_symbol or "UGX"
    except Exception:
        return "UGX"


@register.simple_tag
def currency_symbol():
    return get_currency_symbol()


@register.simple_tag
def company_name():
    try:
        return CompanySettings.get().company_name or "Company"
    except Exception:
        return "Company"


@register.simple_tag
def manager_approval_limit():
    try:
        return money(CompanySettings.get().manager_approval_limit)
    except Exception:
        return money(5_000_000)


@register.filter
def money(value, symbol=None):
    if symbol is None:
        symbol = get_currency_symbol()
    try:
        num = Decimal(str(value))
        formatted = f"{int(num):,}"
        return f"{symbol} {formatted}"
    except (InvalidOperation, TypeError, ValueError):
        return f"{symbol} 0"


@register.filter
def ugx(value):
    return money(value)


@register.filter
def ugx_plain(value):
    try:
        return f"{int(Decimal(str(value))):,}"
    except (InvalidOperation, TypeError, ValueError):
        return "0"


@register.filter
def pct(value, decimals=2):
    try:
        return f"{Decimal(str(value)):.{decimals}f}%"
    except (InvalidOperation, TypeError, ValueError):
        return "0.00%"


@register.filter
def loan_status_badge(status):
    mapping = {
        "DRAFT":       ("badge-muted",  "Draft"),
        "PENDING":     ("badge-amber",  "Pending"),
        "APPROVED":    ("badge-blue",   "Approved"),
        "ACTIVE":      ("badge-green",  "Active"),
        "COMPLETED":   ("badge-teal",   "Completed"),
        "REJECTED":    ("badge-red",    "Rejected"),
        "DEFAULTED":   ("badge-red",    "Defaulted"),
    }
    css, label = mapping.get(status, ("badge-muted", status))
    return f'<span class="badge {css}">{label}</span>'


@register.filter
def schedule_status_badge(status):
    mapping = {
        "PENDING": ("badge-muted",  "Pending"),
        "PAID":    ("badge-green",  "Paid"),
        "PARTIAL": ("badge-amber",  "Partial"),
        "OVERDUE": ("badge-red",    "Overdue"),
        "WAIVED":  ("badge-blue",   "Waived"),
    }
    css, label = mapping.get(status, ("badge-muted", status))
    return f'<span class="badge {css}">{label}</span>'


@register.filter
def initials(user):
    try:
        first = (user.first_name or user.username or "?")[0].upper()
        last = (user.last_name or "")[0].upper() if user.last_name else ""
        return f"{first}{last}"
    except Exception:
        return "?"


@register.filter
def draft_loans(loans):
    """Return only DRAFT loans from a queryset or list."""
    return [l for l in loans if l.status == "DRAFT"]


@register.filter
def non_draft_loans(loans):
    """Return all non-DRAFT loans from a queryset or list."""
    return [l for l in loans if l.status != "DRAFT"]


@register.simple_tag
def overdue_days(due_date):
    from django.utils import timezone
    today = timezone.localdate()
    if due_date < today:
        return (today - due_date).days
    return 0
