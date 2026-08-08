"""
Create a PlatformAdmin (system admin) account for the /public-admin/
control panel.

    python manage.py create_platform_admin
    python manage.py create_platform_admin --username=ops --email=ops@abacash.loan --password=... --role=SUPERADMIN

The first account created defaults to SUPERADMIN if no role is given and no
platform admins exist yet; later accounts default to OPERATOR.
"""
from getpass import getpass

from django.core.management.base import BaseCommand, CommandError

from tenants.models import PlatformAdmin


class Command(BaseCommand):
    help = "Create a PlatformAdmin (system admin) account for /public-admin/."

    def add_arguments(self, parser):
        parser.add_argument("--username", type=str, default=None)
        parser.add_argument("--email", type=str, default=None)
        parser.add_argument("--password", type=str, default=None)
        parser.add_argument(
            "--role",
            type=str,
            default=None,
            choices=[c[0] for c in PlatformAdmin.Role.choices],
        )
        parser.add_argument("--first-name", type=str, default="")
        parser.add_argument("--last-name", type=str, default="")

    def handle(self, *args, **options):
        username = options.get("username") or input("Username: ").strip()
        email = options.get("email") or input("Email: ").strip()

        if not username:
            raise CommandError("Username is required.")
        if not email:
            raise CommandError("Email is required.")

        if PlatformAdmin.objects.filter(username__iexact=username).exists():
            raise CommandError(f"A platform admin with username '{username}' already exists.")
        if PlatformAdmin.objects.filter(email__iexact=email).exists():
            raise CommandError(f"A platform admin with email '{email}' already exists.")

        role = options.get("role")
        if not role:
            is_first = not PlatformAdmin.objects.exists()
            default_role = PlatformAdmin.Role.SUPERADMIN if is_first else PlatformAdmin.Role.OPERATOR
            choices_str = ", ".join(c[0] for c in PlatformAdmin.Role.choices)
            entered = input(f"Role [{choices_str}] (default {default_role}): ").strip().upper()
            role = entered or default_role

        if role not in dict(PlatformAdmin.Role.choices):
            raise CommandError(f"Invalid role '{role}'. Choose from: {', '.join(dict(PlatformAdmin.Role.choices))}")

        password = options.get("password")
        if not password:
            password = getpass("Password: ")
            confirm = getpass("Confirm password: ")
            if password != confirm:
                raise CommandError("Passwords do not match.")
        if len(password) < 8:
            raise CommandError("Password must be at least 8 characters.")

        admin = PlatformAdmin(
            username=username,
            email=email,
            role=role,
            first_name=options.get("first_name") or "",
            last_name=options.get("last_name") or "",
        )
        admin.set_password(password)
        admin.save()

        self.stdout.write(self.style.SUCCESS(
            f"\n✔  Platform admin '{username}' created with role {role}.\n"
            f"   Log in at /public-admin/login/\n"
        ))
