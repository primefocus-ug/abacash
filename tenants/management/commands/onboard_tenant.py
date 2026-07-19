"""
python manage.py onboard_tenant \
    --schema=sacco_kampala \
    --name="Sacco Kampala MFI" \
    --domain=sacco-kampala.yourdomain.com \
    --email=admin@sacco.com \
    --password=ChangeMe123!
"""
from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import schema_context
import logging
import os

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


class Command(BaseCommand):
    help = "Provision a new tenant: schema + seed data + CEO user."

    def add_arguments(self, parser):
        parser.add_argument("--schema",   required=True)
        parser.add_argument("--name",     required=True)
        parser.add_argument("--domain",   required=True)
        parser.add_argument("--email",    required=True)
        parser.add_argument("--password", default="ChangeMe123!")
        parser.add_argument("--plan",     default="STARTER", choices=PLANS.keys())
        parser.add_argument("--phone",    default="")
        parser.add_argument("--address",  default="")
        parser.add_argument("--company-email", default="", help="Optional contact email for company settings.")
        parser.add_argument("--notify", action="store_true", default=False, help="Send credentials to the company contact email after provisioning.")

    def handle(self, *args, **options):
        schema   = options["schema"].lower().replace("-", "_")
        name     = options["name"]
        domain   = options["domain"]
        email    = options["email"]
        password = options["password"]
        plan     = options["plan"]
        company_email = options["company_email"] or email

        self._header(name, schema, domain, plan)

        # ── 1. Tenant + domain ──────────────────────────────────────────
        self._step("1", "Creating tenant & domain")
        from tenants.models import Company, Domain

        if Company.objects.filter(schema_name=schema).exists():
            raise CommandError(f"Schema '{schema}' already exists.")

        company = Company(schema_name=schema, name=name, is_active=True, plan=plan)
        company.save()
        self.stdout.write(f"    ✔  Schema '{schema}' created")

        Domain.objects.create(domain=domain, tenant=company, is_primary=True)
        self.stdout.write(f"    ✔  Domain '{domain}' mapped")

        # Run tenant migrations for the newly created schema before seeding
        try:
            from django.core import management as django_management
            self._step("1a", "Applying tenant migrations")
            # django-tenants provides migrate_schemas to apply migrations across schemas.
            # Pass the schema name so only the new tenant receives migrations where supported.
            django_management.call_command('migrate_schemas', schema_name=schema, verbosity=1)
            self.stdout.write("    ✔  Tenant migrations applied")
        except Exception as exc:
            # Fail loud so operators can investigate — migrations are required before seeding
            raise CommandError(f"Tenant migrations failed for schema '{schema}': {exc}")

        # ── 2. Seed inside schema ───────────────────────────────────────
        self._step("2", "Seeding schema data")
        plan_cfg = PLANS[plan]

        created_user = None
        with schema_context(schema):
            self._seed_settings(name, options["phone"], options["address"], plan_cfg, company_email)
            self._seed_sequence("accounts.models", "ReceiptSequence", "receipt")
            self._seed_sequence("loans.models",    "LoanSequence",    "loans")
            self._seed_products()
            created_user = self._create_ceo(name, email)

        # Provide a summary without revealing passwords
        self._summary(name, schema, domain, email, None, plan)

        # ── 3. Optional notification to company contact (send password-reset link) ─────────────────
        notify = bool(options.get('notify'))
        if notify and company_email:
            try:
                from django.core.mail import send_mail
                from django.conf import settings
                # Build a password reset link for the created admin user
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
                            path = reverse('password_reset_confirm', args=[uid, token])
                            reset_url = f"https://{domain}{path}"
                        except Exception:
                            # Fallback to the common default path
                            reset_url = f"https://{domain}/accounts/reset/{uid}/{token}/"
                    except Exception as e:
                        self.stdout.write(self.style.WARNING(f"    ⚠  Could not generate reset link: {e}"))
                        reset_url = f"https://{domain}/accounts/login/"

                subject = f"Your Abacash tenant '{name}' is ready"
                if reset_url and 'accounts/reset' in reset_url:
                    body = (
                        f"Hello,\n\n"
                        f"Your Abacash tenant has been provisioned. To complete setup, use the administrator account and set your password by following the secure link below:\n\n"
                        f"Tenant: {name}\n"
                        f"Domain: {domain}\n"
                        f"Administrator email: {email}\n\n"
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

                from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', getattr(settings, 'EMAIL_HOST_USER', 'support@abacash.loan'))
                send_mail(subject, body, from_email, [company_email], fail_silently=False)
                self.stdout.write(self.style.SUCCESS(f"    ✔  Sent password reset instructions to {company_email}"))
                logger.info(f"Sent password reset email for tenant {schema} to {company_email}")
            except Exception as exc:
                warning_msg = f"Failed to send credentials email: {exc}"
                self.stdout.write(self.style.WARNING(f"    ⚠  {warning_msg}"))
                logger.warning(warning_msg, exc_info=True)

        self.stdout.write(self.style.SUCCESS(f"\n✅ Onboarding complete!\n"))

    # ── helpers ─────────────────────────────────────────────────────────

    def _seed_settings(self, name, phone, address, plan_cfg, company_email):
        from accounts.models import CompanySettings
        _, created = CompanySettings.objects.get_or_create(pk=1, defaults={
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
        self.stdout.write(f"    ✔  CompanySettings {'created' if created else 'exists'}")

    def _seed_sequence(self, module_path, model_name, seq_name):
        import importlib
        mod = importlib.import_module(module_path)
        Model = getattr(mod, model_name)
        _, created = Model.objects.get_or_create(name=seq_name, defaults={"last": 0})
        self.stdout.write(f"    ✔  {model_name}({seq_name}) {'created' if created else 'exists'}")

    def _seed_products(self):
        from loans.models import LoanProduct
        n = 0
        for p in DEFAULT_PRODUCTS:
            _, created = LoanProduct.objects.get_or_create(name=p["name"], defaults={
                "interest_rate_monthly": Decimal(p["interest_rate_monthly"]),
                "interest_method": p["interest_method"],
                "min_amount": Decimal(p["min_amount"]),
                "max_amount": Decimal(p["max_amount"]),
                "min_term_months": p["min_term"],
                "max_term_months": p["max_term"],
                "is_active": True,
            })
            if created:
                n += 1
        self.stdout.write(f"    ✔  {n} loan products seeded")

    def _create_ceo(self, company_name, email, password=None):
        from accounts.models import User
        if User.objects.filter(email=email).exists():
            existing_user = User.objects.filter(email=email).first()
            self.stdout.write(f"    ⚠  CEO '{email}' already exists")
            return existing_user
        username = base = email.split("@")[0]
        i = 1
        while User.objects.filter(username=username).exists():
            username = f"{base}{i}"; i += 1
        User.objects.create_superuser(
            username=username, email=email, password=password,
            first_name=company_name.split()[0], role="CEO",
        )
        self.stdout.write(f"    ✔  CEO '{email}' created (username: {username})")

    def _step(self, n, label):
        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO(f"  ── Step {n}: {label}"))

    def _header(self, name, schema, domain, plan):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("╔══════════════════════════════════════════╗"))
        self.stdout.write(self.style.SUCCESS("║   Abacash — Tenant Onboarding            ║"))
        self.stdout.write(self.style.SUCCESS("╚══════════════════════════════════════════╝"))
        self.stdout.write(f"  Company : {name}")
        self.stdout.write(f"  Schema  : {schema}")
        self.stdout.write(f"  Domain  : {domain}")
        self.stdout.write(f"  Plan    : {plan}")

    def _summary(self, name, schema, domain, email, password, plan):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("╔══════════════════════════════════════════╗"))
        self.stdout.write(self.style.SUCCESS("║  ✅  Onboarding complete!                ║"))
        self.stdout.write(self.style.SUCCESS("╚══════════════════════════════════════════╝"))
        self.stdout.write(f"\n  Login  → https://{domain}/accounts/login/")
        self.stdout.write(f"  Email  → {email}")
        self.stdout.write(f"  Plan   → {plan}\n")
        self.stdout.write("  Password-reset link sent via email.\n")
        self.stdout.write("  Next: point DNS, issue SSL cert, configure logo & branches.\n")
