"""
python manage.py onboard_tenant \
    --schema=sacco_kampala \
    --name="Sacco Kampala MFI" \
    --domain=sacco-kampala.yourdomain.com \
    --email=admin@sacco.com \
    --notify

This command runs provisioning synchronously (CLI/scripting use — there's
no HTTP request to keep responsive). Web-triggered onboarding instead goes
through tenants.tasks.provision_tenant_task via Celery; both paths share
the exact same logic in tenants/provisioning.py.
"""
from django.core.management.base import BaseCommand, CommandError

from tenants.provisioning import PLANS, ProvisioningError, provision_tenant


class Command(BaseCommand):
    help = "Provision a new tenant: schema + seed data + CEO user (synchronous)."

    def add_arguments(self, parser):
        parser.add_argument("--schema",   required=True)
        parser.add_argument("--name",     required=True)
        parser.add_argument("--domain",   required=True)
        parser.add_argument("--email",    required=True)
        parser.add_argument("--password", default=None, help="If omitted, the CEO account gets an unusable password and must use the emailed reset link (--notify).")
        parser.add_argument("--plan",     default="STARTER", choices=PLANS.keys())
        parser.add_argument("--phone",    default="")
        parser.add_argument("--address",  default="")
        parser.add_argument("--company-email", default="", help="Optional contact email for company settings.")
        parser.add_argument("--notify", action="store_true", default=False, help="Send credentials to the company contact email after provisioning.")

    def handle(self, *args, **options):
        from tenants.models import Company, Domain

        schema = options["schema"].lower().replace("-", "_")
        name   = options["name"]
        domain = options["domain"]
        email  = options["email"]
        plan   = options["plan"]

        self._header(name, schema, domain, plan)

        if Company.objects.filter(schema_name=schema).exists():
            raise CommandError(f"Schema '{schema}' already exists.")

        self._step("1", "Registering tenant (public schema)")
        company = Company.objects.create(schema_name=schema, name=name, is_active=True, plan=plan)
        Domain.objects.create(domain=domain, tenant=company, is_primary=True)
        self.stdout.write(f"    ✔  Company row + domain '{domain}' created (status: PENDING)")

        self._step("2", "Provisioning (schema, migrations, seed data, CEO)")
        try:
            result = provision_tenant(
                company.id, domain, email,
                password=options["password"], plan=plan,
                phone=options["phone"], address=options["address"],
                company_email=options["company_email"],
                notify=options["notify"],
                log=lambda msg: self.stdout.write(f"    …  {msg}"),
            )
        except ProvisioningError as exc:
            raise CommandError(f"Provisioning failed: {exc}")

        self._summary(name, schema, domain, email, result["password_set"], result["notify_sent"], plan)
        self.stdout.write(self.style.SUCCESS("\n✅ Onboarding complete!\n"))

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

    def _summary(self, name, schema, domain, email, password_set, notify_sent, plan):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("╔══════════════════════════════════════════╗"))
        self.stdout.write(self.style.SUCCESS("║  ✅  Onboarding complete!                ║"))
        self.stdout.write(self.style.SUCCESS("╚══════════════════════════════════════════╝"))
        self.stdout.write(f"\n  Login  → https://{domain}/accounts/login/")
        self.stdout.write(f"  Email  → {email}")
        self.stdout.write(f"  Plan   → {plan}\n")
        if notify_sent:
            self.stdout.write("  Password-reset link sent via email.\n")
        elif password_set:
            self.stdout.write("  A password was set — share it with the tenant administrator securely.\n")
        else:
            self.stdout.write(self.style.WARNING(
                "  ⚠  No password was set and no reset email was sent — this CEO "
                "account cannot log in yet. Re-run with --notify (and a valid "
                "--company-email), or use the public admin panel's 'reset access' "
                "action to send a login link.\n"
            ))
        self.stdout.write("  Next: point DNS, issue SSL cert, configure logo & branches.\n")
