"""
python manage.py migrate_all_tenants

Migrates every tenant schema one at a time, each in its own fully isolated
subprocess (a plain `migrate_schemas --schema=<name>` call). This exists
because the bulk `migrate_schemas` (no --schema filter) runs all tenants
sequentially inside a single long-lived process/connection, and has been
observed to fail on a schema that migrates perfectly cleanly on its own
(psycopg2.errors.InvalidSchemaName: "no schema has been selected to create
in", raised inside django's MigrationRecorder.ensure_schema() well after
that same schema already logged "No migrations to apply.") — almost
certainly leftover connection/search_path state bleeding across tenants
within that one process, not anything wrong with the tenant's data.

Running each tenant as its own subprocess sidesteps that entirely: every
tenant starts with a brand new Python process, DB connection, and search
path, so nothing from tenant N can affect tenant N+1. A failure on one
tenant is logged and does NOT stop the run — every other tenant still gets
migrated, and you get a clear summary of exactly which ones (if any) need
a closer look.

Usage:
    python manage.py migrate_all_tenants
    python manage.py migrate_all_tenants --include-public
    python manage.py migrate_all_tenants --only=raystine_easy_cash,aba
"""
import subprocess
import sys

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Migrate every tenant schema, one isolated subprocess per tenant. Failures are logged, not fatal."

    def add_arguments(self, parser):
        parser.add_argument(
            "--include-public", action="store_true", default=False,
            help="Also migrate the public schema first (usually already covered separately).",
        )
        parser.add_argument(
            "--only", default="",
            help="Comma-separated list of schema_names to migrate, instead of every tenant.",
        )

    def handle(self, *args, **options):
        from tenants.models import Company

        only = {s.strip() for s in options["only"].split(",") if s.strip()}
        schemas = list(
            Company.objects.order_by("id").values_list("schema_name", flat=True)
        )
        if only:
            schemas = [s for s in schemas if s in only]

        if not schemas:
            self.stdout.write(self.style.WARNING("No tenant schemas matched — nothing to do."))
            return

        total = len(schemas) + (1 if options["include_public"] else 0)
        self.stdout.write(f"Migrating {total} schema(s), one isolated process each…\n")

        succeeded, failed = [], []

        if options["include_public"]:
            self._migrate_one("public", 1, total, succeeded, failed)

        for i, schema in enumerate(schemas, start=(2 if options["include_public"] else 1)):
            self._migrate_one(schema, i, total, succeeded, failed)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"✔ {len(succeeded)} succeeded"))
        if failed:
            self.stdout.write(self.style.ERROR(f"✘ {len(failed)} failed:"))
            for schema, err in failed:
                self.stdout.write(self.style.ERROR(f"    {schema}: {err.strip().splitlines()[-1] if err.strip() else 'unknown error'}"))
            self.stdout.write("")
            self.stdout.write("Re-run just the failed ones once fixed, e.g.:")
            self.stdout.write(f"    python manage.py migrate_all_tenants --only={','.join(s for s, _ in failed)}")
        else:
            self.stdout.write(self.style.SUCCESS("All schemas migrated cleanly."))

    def _migrate_one(self, schema, idx, total, succeeded, failed):
        self.stdout.write(f"[{idx}/{total}] {schema} …")
        result = subprocess.run(
            [sys.executable, "manage.py", "migrate_schemas", f"--schema={schema}"],
            cwd=str(settings.BASE_DIR),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            self.stdout.write(self.style.SUCCESS(f"    ok"))
            succeeded.append(schema)
        else:
            self.stdout.write(self.style.ERROR(f"    FAILED (see summary at the end)"))
            failed.append((schema, result.stderr or result.stdout))
