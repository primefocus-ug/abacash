from django.db import migrations, models


class Migration(migrations.Migration):
    """
    PlatformAdmin was accidentally deleted from tenants/models.py at some
    point, which caused 0007_remove_onboardingattempt_registration_and_more
    to auto-generate a DeleteModel for it. The model has been restored (it's
    the real, in-use auth model for /public-admin/ — see tenants/auth.py and
    tenants/management/commands/create_platform_admin.py), so this migration
    recreates the table with the exact same schema 0004_platformadmin.py
    originally defined.

    Note: 0007 is left as-is (with its DeleteModel) rather than edited in
    place, since it may already be applied against real databases — Django
    only checks that a migration *name* has run, not its contents, so editing
    an already-applied migration silently does nothing on those databases.
    A new forward migration is the safe way to reintroduce the table.
    """

    dependencies = [
        ("tenants", "0007_remove_onboardingattempt_registration_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="PlatformAdmin",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("username", models.CharField(max_length=150, unique=True)),
                ("email", models.EmailField(max_length=254, unique=True)),
                ("password", models.CharField(max_length=128)),
                ("first_name", models.CharField(blank=True, max_length=150)),
                ("last_name", models.CharField(blank=True, max_length=150)),
                (
                    "role",
                    models.CharField(
                        choices=[("SUPERADMIN", "Super Admin"), ("OPERATOR", "Operator")],
                        default="OPERATOR",
                        max_length=12,
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("last_login", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Platform Admin",
                "verbose_name_plural": "Platform Admins",
                "ordering": ["username"],
            },
        ),
    ]
