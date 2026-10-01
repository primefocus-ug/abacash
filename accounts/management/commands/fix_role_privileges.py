"""List (and optionally fix) staff whose role is not CEO but who still hold
superuser/staff flags -- e.g. ex-CEOs who were demoted before the demotion fix.

Always runs inside a tenant schema context (see tenants/command_utils.py):

    python manage.py fix_role_privileges --schema=<name>              # dry run
    python manage.py fix_role_privileges --schema=<name> --apply      # fix
    python manage.py fix_role_privileges --all-tenants [--apply]
"""
from django.contrib.auth import get_user_model

from tenants.command_utils import TenantSchemaCommand


class Command(TenantSchemaCommand):
    help = "Strip is_superuser/is_staff from users whose role is Manager or Cashier."

    def add_tenant_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Actually change the users (default is a dry run).")

    def handle_tenant(self, schema, *args, **opts):
        User = get_user_model()
        bad = (
            User.objects.exclude(role="CEO").filter(is_superuser=True)
            | User.objects.filter(role="CASHIER", is_staff=True)
        ).distinct()
        users = list(bad)
        if not users:
            self.stdout.write(self.style.SUCCESS("No over-privileged non-CEO users found."))
            return
        for u in users:
            self.stdout.write(f"{u.email:40} role={u.role:8} superuser={u.is_superuser} staff={u.is_staff}")
            if opts["apply"]:
                u.is_superuser = False
                u.is_staff = False
                u.save(update_fields=["is_superuser", "is_staff"])
        if opts["apply"]:
            self.stdout.write(self.style.SUCCESS(f"Fixed {len(users)} user(s)."))
        else:
            self.stdout.write(self.style.WARNING("Dry run. Re-run with --apply to fix."))
