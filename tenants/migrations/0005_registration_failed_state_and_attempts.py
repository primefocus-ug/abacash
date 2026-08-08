import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0004_platformadmin"),
    ]

    operations = [
        migrations.AlterField(
            model_name="companyregistration",
            name="status",
            field=models.CharField(
                choices=[
                    ("PENDING", "Pending Review"),
                    ("CONTACTED", "Contacted"),
                    ("ONBOARDED", "Onboarded"),
                    ("FAILED", "Onboarding Failed"),
                    ("REJECTED", "Rejected"),
                ],
                default="PENDING",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="companyregistration",
            name="schema_name",
            field=models.CharField(
                blank=True,
                help_text="Tenant schema this registration was (or is being) provisioned as.",
                max_length=63,
            ),
        ),
        migrations.AddField(
            model_name="companyregistration",
            name="domain",
            field=models.CharField(
                blank=True,
                help_text="Primary domain assigned during provisioning.",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="companyregistration",
            name="onboarded_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="companyregistration",
            name="last_error",
            field=models.TextField(
                blank=True,
                help_text="Error message from the most recent failed onboarding attempt.",
            ),
        ),
        migrations.CreateModel(
            name="OnboardingAttempt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "triggered_by",
                    models.CharField(
                        choices=[("AUTO_SIGNUP", "Automatic (signup)"), ("MANUAL_ADMIN", "Manual (admin panel)")],
                        default="MANUAL_ADMIN",
                        max_length=20,
                    ),
                ),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("success", models.BooleanField(default=None, null=True)),
                ("schema_name", models.CharField(blank=True, max_length=63)),
                ("domain", models.CharField(blank=True, max_length=255)),
                ("log_output", models.TextField(blank=True, help_text="Captured stdout/stderr of the onboarding command.")),
                ("error_message", models.TextField(blank=True)),
                (
                    "registration",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attempts",
                        to="tenants.companyregistration",
                    ),
                ),
            ],
            options={
                "verbose_name": "Onboarding Attempt",
                "verbose_name_plural": "Onboarding Attempts",
                "ordering": ["-started_at"],
            },
        ),
    ]