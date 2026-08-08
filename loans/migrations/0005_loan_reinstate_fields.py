import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('loans', '0004_loan_processing_fee_manually_set'),
    ]

    operations = [
        migrations.AddField(
            model_name='loan',
            name='reinstated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loan',
            name='reinstated_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='reinstated_loans',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='loan',
            name='reinstatement_reason',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='loanschedule',
            name='waived_by_writeoff',
            field=models.BooleanField(
                default=False,
                help_text=(
                    "True if this entry was moved to WAIVED specifically by a loan "
                    "write-off (not an independent fee waiver). Lets reinstate() "
                    "restore exactly the entries it touched, and no others."
                ),
            ),
        ),
    ]
