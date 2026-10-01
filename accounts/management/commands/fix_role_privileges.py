"""List (and optionally fix) staff whose role is not CEO but who still hold
superuser/staff flags -- e.g. ex-CEOs who were demoted before the demotion fix.

    python manage.py fix_role_privileges            # dry run, just lists them
    python manage.py fix_role_privileges --apply    # strips the flags

Multi-tenant: run inside each tenant (tenant_command ... --schema=<name>).
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Strip is_superuser/is_staff from users whose role is Manager or Cashier."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **opts):
        User = get_user_model()
        bad = User.objects.exclude(role="CEO").filter(is_superuser=True) | \
              User.objects.filter(role="CASHIER", is_staff=True)
        bad = bad.distinct()
        if not bad.exists():
            self.stdout.write(self.style.SUCCESS("No over-privileged non-CEO users found."))
            return
        for u in bad:
            self.stdout.write(f"{u.email:40} role={u.role:8} superuser={u.is_superuser} staff={u.is_staff}")
            if opts["apply"]:
                u.is_superuser = False
                u.is_staff = False
                u.save(update_fields=["is_superuser", "is_staff"])
        if opts["apply"]:
            self.stdout.write(self.style.SUCCESS(f"Fixed {bad.count()} user(s)."))
        else:
            self.stdout.write(self.style.WARNING("Dry run. Re-run with --apply to fix."))
