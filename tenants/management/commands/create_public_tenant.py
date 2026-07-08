"""
Bootstrap the public schema tenant (run once after first migrate_schemas --shared).

    python manage.py create_public_tenant
    python manage.py create_public_tenant --domain=yourdomain.com
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create the public-schema Company + Domain rows required by django-tenants."

    def add_arguments(self, parser):
        parser.add_argument(
            "--domain",
            default="localhost",
            help="Primary domain for the public tenant (default: localhost)",
        )
        parser.add_argument(
            "--name",
            default="Public",
            help="Display name for the public tenant (default: Public)",
        )

    def handle(self, *args, **options):
        from tenants.models import Company, Domain

        if Company.objects.filter(schema_name="public").exists():
            raise CommandError(
                "Public tenant already exists. Nothing to do."
            )

        # auto_create_schema=True would try to CREATE the public schema,
        # which already exists in Postgres — skip that by saving directly.
        company = Company(schema_name="public", name=options["name"], is_active=True)
        company.auto_create_schema = False
        company.save()
        self.stdout.write(f"  ✔  Company row created  (schema=public, name={options['name']})")

        domain = options["domain"]
        Domain.objects.create(domain=domain, tenant=company, is_primary=True)
        self.stdout.write(f"  ✔  Domain row created   ({domain} → public)")

        self.stdout.write(self.style.SUCCESS("\nPublic tenant ready."))
        self.stdout.write(
            "  Next: python manage.py migrate_schemas --shared\n"
            "  Then: python manage.py onboard_tenant --schema=<slug> --name=... --domain=... --email=... --password=..."
        )
