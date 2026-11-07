from django.db import migrations, models
from django.core.validators import MinValueValidator
from decimal import Decimal


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0015_capitalinjection_investor_record"),
    ]

    operations = [
        migrations.AddField(
            model_name="companysettings",
            name="daily_disbursement_limit",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text="Maximum total loan principal disbursed per day. Zero disables the limit.",
                max_digits=15,
                validators=[MinValueValidator(Decimal("0.00"))],
            ),
        ),
        migrations.AddField(
            model_name="companysettings",
            name="daily_disbursement_limit_scope",
            field=models.CharField(
                choices=[
                    ("ALL", "All staff"),
                    ("CASHIER", "Cashiers"),
                    ("MANAGER", "Managers"),
                    ("CEO", "CEOs"),
                ],
                default="ALL",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="companysettings",
            name="weekly_disbursement_limit",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text="Maximum total loan principal disbursed per week. Zero disables the limit.",
                max_digits=15,
                validators=[MinValueValidator(Decimal("0.00"))],
            ),
        ),
        migrations.AddField(
            model_name="companysettings",
            name="weekly_disbursement_limit_scope",
            field=models.CharField(
                choices=[
                    ("ALL", "All staff"),
                    ("CASHIER", "Cashiers"),
                    ("MANAGER", "Managers"),
                    ("CEO", "CEOs"),
                ],
                default="ALL",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="companysettings",
            name="monthly_disbursement_limit",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text="Maximum total loan principal disbursed per month. Zero disables the limit.",
                max_digits=15,
                validators=[MinValueValidator(Decimal("0.00"))],
            ),
        ),
        migrations.AddField(
            model_name="companysettings",
            name="monthly_disbursement_limit_scope",
            field=models.CharField(
                choices=[
                    ("ALL", "All staff"),
                    ("CASHIER", "Cashiers"),
                    ("MANAGER", "Managers"),
                    ("CEO", "CEOs"),
                ],
                default="ALL",
                max_length=10,
            ),
        ),
    ]
