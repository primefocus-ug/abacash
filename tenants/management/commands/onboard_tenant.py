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

    def handle(self, *args, **options):
        schema   = options["schema"].lower().replace("-", "_")
        name     = options["name"]
        domain   = options["domain"]
        email    = options["email"]
        password = options["password"]
        plan     = options["plan"]

        self._header(name, schema, domain, plan)

        # ── 1. Tenant + domain ──────────────────────────────────────────
        self._step("1", "Creating tenant & domain")
        from tenants.models import Company, Domain

        if Company.objects.filter(schema_name=schema).exists():
            raise CommandError(f"Schema '{schema}' already exists.")

        company = Company(schema_name=schema, name=name, is_active=True)
        company.save()
        self.stdout.write(f"    ✔  Schema '{schema}' created")

        Domain.objects.create(domain=domain, tenant=company, is_primary=True)
        self.stdout.write(f"    ✔  Domain '{domain}' mapped")

        # ── 2. Seed inside schema ───────────────────────────────────────
        self._step("2", "Seeding schema data")
        plan_cfg = PLANS[plan]

        with schema_context(schema):
            self._seed_settings(name, options["phone"], options["address"], plan_cfg)
            self._seed_sequence("accounts.models", "ReceiptSequence", "receipt")
            self._seed_sequence("loans.models",    "LoanSequence",    "loans")
            self._seed_products()
            self._create_ceo(name, email, password)

        self._summary(name, schema, domain, email, password, plan)

    # ── helpers ─────────────────────────────────────────────────────────

    def _seed_settings(self, name, phone, address, plan_cfg):
        from accounts.models import CompanySettings
        _, created = CompanySettings.objects.get_or_create(pk=1, defaults={
            "company_name": name, "company_phone": phone, "company_address": address,
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

    def _create_ceo(self, company_name, email, password):
        from accounts.models import User
        if User.objects.filter(email=email).exists():
            self.stdout.write(f"    ⚠  CEO '{email}' already exists")
            return
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
        self.stdout.write(self.style.SUCCESS("║   ABA Uganda — Tenant Onboarding         ║"))
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
        self.stdout.write(f"  Pass   → {password}  ← change on first login!")
        self.stdout.write(f"  Plan   → {plan}\n")
        self.stdout.write("  Next: point DNS, issue SSL cert, configure logo & branches.\n")
