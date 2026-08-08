"""
Core tenant provisioning logic, shared by:
  - management/commands/onboard_tenant.py (synchronous, for CLI/scripting use)
  - tasks.py's provision_tenant_task (asynchronous, for web-triggered onboarding)

Company.auto_create_schema is False (see models.py) — schema creation is
always driven explicitly through provision_tenant() below, never implicitly
on save(). This is what makes background provisioning possible: with
auto_create_schema=True, django-tenants creates+migrates the schema inside
save() itself, synchronously, no matter what calls it.

provision_tenant() always updates Company.provisioning_status as it goes
(RUNNING -> READY or FAILED) so callers — sync or async — can be observed
the same way from the UI.
"""
import logging
from decimal import Decimal

from django.utils import timezone

logger = logging.getLogger(__name__)

PLANS = {
    "STARTER":      {"manager_limit": 5_000_000,   "max_loans": 2},
    "PROFESSIONAL": {"manager_limit": 20_000_000,  "max_loans": 3},
    "ENTERPRISE":   {"manager_limit": 999_999_999, "max_loans": 5},
}

DEFAULT_PRODUCTS = [
    {"name": "Salary Loan",    "interest_rate_monthly": "5.00", "interest_method": "FLAT",     "min_amount": "100000",  "max_amount": "5000000",  "min_term": 1, "max_term": 12},
    {"name": "Business Loan",  "interest_rate_monthly": "4.00", "interest_method": "REDUCING", "min_amount": "500000",  "max_amount": "50000000", "min_term": 3, "max_term": 24},
    {"name": "Emergency Loan", "interest_rate_monthly": "6.00", "interest_method": "FLAT",     "min_amount": "50000",   "max_amount": "1000000",  "min_term": 1, "max_term": 3},
]


class ProvisioningError(Exception):
    """Raised on any step failure; message is stored on Company.provisioning_error."""


def provision_tenant(
    company_id,
    domain,
    email,
    password=None,
    plan="STARTER",
    phone="",
    address="",
    company_email="",
    notify=False,
    log=None,
):
    """Create the schema, run migrations, seed data, create the CEO user.

    `company_id` must already exist (status=PENDING) — the caller creates
    the Company + Domain rows first (fast, public-schema-only writes) so
    there's something to track status against even before this function
    starts. `log(message)` is an optional callback for step-by-step output
    (the CLI command passes self.stdout.write; the Celery task can pass
    logger.info or leave it as a no-op).

    Returns a dict summary. Raises ProvisioningError on failure — but the
    Company row's provisioning_status/provisioning_error are always updated
    before this function returns or raises, so callers don't have to catch
    the exception just to know what happened.
    """
    from tenants.models import Company

    _log = log or (lambda msg: None)
    company = Company.objects.get(pk=company_id)
    company.provisioning_status = Company.ProvisioningStatus.RUNNING
    company.provisioning_started_at = timezone.now()
    company.provisioning_error = ""
    company.save(update_fields=["provisioning_status", "provisioning_started_at", "provisioning_error"])

    plan_cfg = PLANS.get(plan, PLANS["STARTER"])
    company_email = company_email or email
    created_user = None
    notify_sent = False

    try:
        _log(f"Creating schema '{company.schema_name}'…")
        company.create_schema(check_if_exists=True, verbosity=1)
        _log("Schema created.")

        _log("Applying tenant migrations…")
        from django.core import management as django_management
        django_management.call_command("migrate_schemas", schema_name=company.schema_name, verbosity=1)
        _log("Migrations applied.")

        _log("Seeding schema data…")
        from django_tenants.utils import schema_context
        with schema_context(company.schema_name):
            _seed_settings(company.name, phone, address, plan_cfg, company_email)
            branch = _seed_branch(company.name, phone, address, company_email)
            _seed_sequence("accounts.models", "ReceiptSequence", "receipt")
            _seed_sequence("loans.models", "LoanSequence", "loans")
            _seed_products()
            created_user = _create_ceo(company.name, email, password)
            if created_user is not None and branch is not None and created_user.branch_id is None:
                created_user.branch = branch
                created_user.save(update_fields=["branch"])
        _log("Seeding complete.")

        if notify and company_email:
            notify_sent = _send_notify_email(company.name, company.schema_name, domain, email, company_email, created_user)
            _log("Notification email sent." if notify_sent else "Notification email failed — see logs.")

    except Exception as exc:
        logger.exception("Provisioning failed for company %s (%s)", company_id, getattr(company, "schema_name", "?"))
        company.provisioning_status = Company.ProvisioningStatus.FAILED
        company.provisioning_error = str(exc)
        company.save(update_fields=["provisioning_status", "provisioning_error"])
        raise ProvisioningError(str(exc)) from exc

    company.provisioning_status = Company.ProvisioningStatus.READY
    company.provisioning_completed_at = timezone.now()
    company.save(update_fields=["provisioning_status", "provisioning_completed_at"])

    return {
        "company_id": company.id,
        "schema": company.schema_name,
        "password_set": bool(password),
        "notify_sent": notify_sent,
    }


# ── seeding helpers ──────────────────────────────────────────────────────

def _seed_settings(name, phone, address, plan_cfg, company_email):
    from accounts.models import CompanySettings
    CompanySettings.objects.get_or_create(pk=1, defaults={
        "company_name": name,
        "company_phone": phone,
        "company_address": address,
        "company_email": company_email,
        "manager_approval_limit": plan_cfg["manager_limit"],
        "max_active_loans_per_client": plan_cfg["max_loans"],
        "processing_fee_method": "PERCENTAGE",
        "default_processing_fee_percent": "1.00",
        "currency_symbol": "UGX",
    })


def _seed_branch(name, phone, address, company_email):
    from accounts.models import Branch
    branch, _created = Branch.objects.get_or_create(code="HQ", defaults={
        "name": f"{name} — Head Office",
        "address": address,
        "phone": phone,
        "email": company_email,
        "is_active": True,
        "opened_date": timezone.localdate(),
    })
    return branch


def _seed_sequence(module_path, model_name, seq_name):
    import importlib
    mod = importlib.import_module(module_path)
    Model = getattr(mod, model_name)
    Model.objects.get_or_create(name=seq_name, defaults={"last": 0})


def _seed_products():
    from loans.models import LoanProduct
    for p in DEFAULT_PRODUCTS:
        LoanProduct.objects.get_or_create(name=p["name"], defaults={
            "interest_rate_monthly": Decimal(p["interest_rate_monthly"]),
            "interest_method": p["interest_method"],
            "min_amount": Decimal(p["min_amount"]),
            "max_amount": Decimal(p["max_amount"]),
            "min_term_months": p["min_term"],
            "max_term_months": p["max_term"],
            "is_active": True,
        })


def _create_ceo(company_name, email, password=None):
    from accounts.models import User
    existing = User.objects.filter(email=email).first()
    if existing:
        return existing
    username = base = email.split("@")[0]
    i = 1
    while User.objects.filter(username=username).exists():
        username = f"{base}{i}"
        i += 1
    user = User.objects.create_superuser(
        username=username, email=email, password=password or None,
        first_name=company_name.split()[0], role="CEO",
    )
    if not password:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    return user


def _send_notify_email(name, schema, domain, email, company_email, created_user):
    try:
        from django.core.mail import send_mail
        from django.conf import settings

        reset_url = None
        if created_user is not None:
            try:
                from django.contrib.auth.tokens import default_token_generator
                from django.utils.http import urlsafe_base64_encode
                from django.utils.encoding import force_bytes
                from django.urls import reverse

                uid = urlsafe_base64_encode(force_bytes(created_user.pk))
                token = default_token_generator.make_token(created_user)
                try:
                    path = reverse("password_reset_confirm", args=[uid, token])
                    reset_url = f"https://{domain}{path}"
                except Exception:
                    reset_url = f"https://{domain}/accounts/reset/{uid}/{token}/"
            except Exception:
                reset_url = f"https://{domain}/accounts/login/"

        subject = f"Your Abacash tenant '{name}' is ready"
        if reset_url and "accounts/reset" in reset_url:
            body = (
                f"Hello,\n\n"
                f"Your Abacash tenant has been provisioned. To complete setup, use the administrator account and set your password by following the secure link below:\n\n"
                f"Tenant: {name}\nDomain: {domain}\nAdministrator email: {email}\n\n"
                f"Open this link to complete your password creation: {reset_url}\n\n"
                "The password entry screen will open with your username prefilled. For security, the link can only be used once. If you did not request this, contact support@abacash.loan immediately.\n\n"
                "Best regards,\nAbacash Onboarding Team"
            )
        else:
            body = (
                f"Hello,\n\n"
                f"Your Abacash tenant has been provisioned. Sign in at https://{domain}/accounts/login/ and use the password reset flow to set your administrator password.\n\n"
                "If you did not request this, contact support@abacash.loan immediately.\n\n"
                "Best regards,\nAbacash Onboarding Team"
            )

        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", getattr(settings, "EMAIL_HOST_USER", "support@abacash.loan"))
        send_mail(subject, body, from_email, [company_email], fail_silently=False)
        logger.info("Sent password reset email for tenant %s to %s", schema, company_email)
        return True
    except Exception:
        logger.warning("Failed to send credentials email for tenant %s", schema, exc_info=True)
        return False
