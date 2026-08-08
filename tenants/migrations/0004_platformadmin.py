from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0003_add_company_plan"),
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
