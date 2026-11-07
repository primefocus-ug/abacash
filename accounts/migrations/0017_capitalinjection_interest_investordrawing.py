from django.db import migrations, models
from django.core.validators import MinValueValidator
from django.utils import timezone
from decimal import Decimal


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0016_companysettings_disbursement_limits"),
    ]

    operations = [
        migrations.AddField(
            model_name="capitalinjection",
            name="attracts_interest",
            field=models.BooleanField(
                default=False,
                help_text="Apply the configured annual savings interest rate to this injection.",
            ),
        ),
        migrations.AddField(
            model_name="capitalinjection",
            name="interest_rate_annual",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text="Annual interest rate snapshotted when this injection was recorded.",
                max_digits=5,
            ),
        ),
        migrations.CreateModel(
            name="InvestorDrawing",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=15, validators=[MinValueValidator(Decimal("0.01"))])),
                ("drawing_date", models.DateField(default=timezone.localdate)),
                ("payment_method", models.CharField(
                    choices=[("CASH", "Cash"), ("BANK", "Bank Transfer"), ("MOBILE_MONEY", "Mobile Money")],
                    default="BANK", max_length=20,
                )),
                ("purpose", models.CharField(blank=True, max_length=255)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(
                    blank=True, null=True, on_delete=models.SET_NULL,
                    related_name="created_investor_drawings", to="accounts.user",
                )),
                ("investor", models.ForeignKey(
                    on_delete=models.PROTECT, related_name="drawings", to="accounts.investor",
                )),
            ],
            options={
                "ordering": ["-drawing_date", "-created_at"],
                "indexes": [models.Index(fields=["investor", "drawing_date"], name="accounts_in_investo_ab4c0c_idx")],
            },
        ),
    ]
