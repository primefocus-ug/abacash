from django.conf import settings
from django.db import connection
from django.db.models.signals import post_migrate
from django.dispatch import receiver
from django.contrib.auth import get_user_model


@receiver(post_migrate)
def create_initial_tenant_admin(sender, app_config, **kwargs):
    """Create an initial tenant admin user automatically after tenant migrations.

    This runs on post_migrate for the 'accounts' app inside a tenant schema.
    Behavior:
    - Skip when running in the public schema (schema_name == 'public').
    - Only act when app_config.name == 'accounts' to avoid duplicate runs.
    - If the User table has no users, create a superuser with defaults from settings.

    This provides a safe automatic seeding: the first migration into a brand new
    tenant will create an admin account so operators can sign in immediately.
    """
    try:
        schema = getattr(connection, 'schema_name', None) or getattr(connection, 'settings_dict', {}).get('OPTIONS', {}).get('schema', None)
    except Exception:
        schema = None

    # If we are in the public schema, do nothing
    if schema in (None, 'public'):
        return

    # Only run when the accounts app migrations have completed in this schema
    if getattr(app_config, 'name', '') != 'accounts':
        return

    User = get_user_model()

    try:
        if User.objects.exists():
            # Tenant already has users, nothing to do
            return
    except Exception:
        # If the user table doesn't exist or other DB error, abort silently
        return

    admin_username = getattr(settings, 'TENANT_INITIAL_ADMIN_USERNAME', 'admin')
    admin_password = getattr(settings, 'TENANT_INITIAL_ADMIN_PASSWORD', '@Developer25')
    tenant_domain_root = getattr(settings, 'TENANT_PUBLIC_DOMAIN', 'localhost')
    admin_email = f"{admin_username}@{schema}.{tenant_domain_root}" if schema else f"{admin_username}@{tenant_domain_root}"

    try:
        User.objects.create_superuser(username=admin_username, email=admin_email, password=admin_password)
        # Optionally write to stdout for visibility when running management commands
        try:
            from django.core.management import call_command
            print(f"Created initial tenant admin: {admin_username} ({admin_email}) in schema {schema}")
        except Exception:
            pass
    except Exception as exc:
        # Do not raise during migrations; just log to stderr if possible
        try:
            import sys
            sys.stderr.write(f"Could not create initial tenant admin for schema {schema}: {exc}\n")
        except Exception:
            pass
