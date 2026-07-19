from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context

from tenants.models import Company, Domain


class Command(BaseCommand):
    help = "Create or update the admin superuser in a tenant schema"

    def add_arguments(self, parser):
        parser.add_argument("--username", default="admin")
        parser.add_argument("--email", default="admin@aba.loan")
        parser.add_argument("--password", default="@Developer25")
        parser.add_argument("--schema-name", default=None)

    def handle(self, *args, **options):
        User = get_user_model()
        username = options["username"]
        email = options["email"]
        password = options["password"]
        schema_name = options["schema_name"]

        if schema_name:
            tenant = Company.objects.filter(schema_name=schema_name).first()
            if tenant is None:
                tenant = Company.objects.create(schema_name=schema_name, name=schema_name.capitalize(), is_active=True)
                Domain.objects.get_or_create(
                    tenant=tenant,
                    domain=f"{schema_name}.localhost",
                    defaults={"is_primary": True, "is_verified": True},
                )
        else:
            tenant = Company.objects.order_by("id").first()
            if tenant is None:
                tenant = Company.objects.create(schema_name="default", name="Default Tenant", is_active=True)
                Domain.objects.get_or_create(
                    tenant=tenant,
                    domain="default.localhost",
                    defaults={"is_primary": True, "is_verified": True},
                )

        with schema_context(tenant.schema_name):
            user = User.objects.filter(username=username).first()
            if user is None:
                user = User.objects.create_superuser(username=username, email=email, password=password)
                self.stdout.write(self.style.SUCCESS(
                    f"Created superuser '{username}' in tenant schema '{tenant.schema_name}'."
                ))
                return

            user.email = email
            user.is_staff = True
            user.is_superuser = True
            user.is_active = True
            user.set_password(password)
            user.save(update_fields=["email", "is_staff", "is_superuser", "is_active", "password"])

            self.stdout.write(self.style.SUCCESS(
                f"Updated superuser '{username}' in tenant schema '{tenant.schema_name}'."
            ))
