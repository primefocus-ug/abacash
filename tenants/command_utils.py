"""Shared base class for management commands that touch tenant data.

`accounts`, `loans`, `payments`, `clients`, ... are TENANT apps: their tables
only exist inside each company's own Postgres schema. A plain
`manage.py some_command` runs against the *public* schema, where those tables
don't exist (or, worse, silently hit the wrong data). So every such command
must run inside an explicit schema context.

Subclass TenantSchemaCommand and implement `handle_tenant(schema, ...)`:

    class Command(TenantSchemaCommand):
        help = "..."

        def add_tenant_arguments(self, parser):      # optional extra flags
            parser.add_argument("--apply", action="store_true")

        def handle_tenant(self, schema, *args, **options):
            ...   # runs inside schema_context(schema)

Usage:
    python manage.py <command> --schema=<schema_name>
    python manage.py <command> --all-tenants

One of --schema / --all-tenants is required, so nothing ever runs against an
unintended schema. With --all-tenants a failure in one tenant is reported and
the remaining tenants still run; the command exits non-zero at the end.
"""
from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import (
    get_public_schema_name,
    get_tenant_model,
    schema_context,
)


class TenantSchemaCommand(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "--schema",
            dest="tenant_schema",
            default=None,
            help="Run against this one tenant schema.",
        )
        parser.add_argument(
            "--all-tenants",
            dest="all_tenants",
            action="store_true",
            default=False,
            help="Run against every tenant schema (excludes public).",
        )
        self.add_tenant_arguments(parser)

    # -- hooks for subclasses ------------------------------------------------
    def add_tenant_arguments(self, parser):
        """Override to add command-specific arguments."""

    def handle_tenant(self, schema, *args, **options):
        raise NotImplementedError("Subclasses must implement handle_tenant().")

    # -- plumbing ------------------------------------------------------------
    def _tenant_schemas(self):
        # Company rows live in the public schema; this runs outside any tenant context.
        public = get_public_schema_name()
        return list(
            get_tenant_model().objects.exclude(schema_name=public)
            .order_by("schema_name")
            .values_list("schema_name", flat=True)
        )

    def _resolve_schemas(self, options):
        schema, all_tenants = options.get("tenant_schema"), options.get("all_tenants")
        if schema and all_tenants:
            raise CommandError("Use either --schema or --all-tenants, not both.")
        available = self._tenant_schemas()
        if schema:
            if schema not in available:
                raise CommandError(
                    f"Unknown tenant schema '{schema}'. Available: {', '.join(available) or '(none)'}"
                )
            return [schema]
        if all_tenants:
            if not available:
                raise CommandError("No tenant schemas found.")
            return available
        raise CommandError(
            "Specify --schema=<name> or --all-tenants. "
            f"Available schemas: {', '.join(available) or '(none)'}"
        )

    def handle(self, *args, **options):
        schemas = self._resolve_schemas(options)
        failed = []
        for schema in schemas:
            self.stdout.write(self.style.MIGRATE_HEADING(f"== Tenant schema: {schema} =="))
            try:
                with schema_context(schema):
                    self.handle_tenant(schema, *args, **options)
            except Exception as exc:  # keep going so one bad tenant doesn't block the rest
                if len(schemas) == 1:
                    raise
                failed.append(schema)
                self.stderr.write(self.style.ERROR(f"[{schema}] failed: {exc}"))
        if failed:
            raise CommandError(f"Failed for {len(failed)} tenant(s): {', '.join(failed)}")
