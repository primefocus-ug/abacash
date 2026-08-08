# Generated manually — adds Loan.processing_fee_manually_set

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0003_loandisbursementaudit'),
    ]

    operations = [
        migrations.AddField(
            model_name='loan',
            name='processing_fee_manually_set',
            field=models.BooleanField(
                default=False,
                help_text=(
                    "If True, processing_fee was set on purpose (e.g. waived to 0) and "
                    "must not be recalculated automatically on save."
                ),
            ),
        ),
    ]
