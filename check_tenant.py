
from django.db import connection
from django_tenants.utils import schema_context
from tenants.models import Company

tenant = Company.objects.get(schema_name="aba")

print("Tenant:", tenant.name)
print("Schema:", tenant.schema_name)

with connection.cursor() as cursor:
    cursor.execute(
        "SELECT EXISTS ("
        "SELECT 1 FROM pg_namespace WHERE nspname = %s"
        ")",
        [tenant.schema_name],
    )
    schema_exists = cursor.fetchone()[0]

if not schema_exists:
    with connection.cursor() as cursor:
        cursor.execute(
            'CREATE SCHEMA "aba"'
        )
    print("Created schema: aba")
else:
    print("Schema already exists: aba")

print("Schema setup complete.")
