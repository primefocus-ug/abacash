import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
        ('clients', '0002_client_credit_balance_credittransaction'),
    ]

    operations = [
        migrations.AddField(
            model_name='client',
            name='branch',
            field=models.ForeignKey(
                blank=True,
                help_text='Branch this client is registered under.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='clients',
                to='accounts.branch',
            ),
        ),
    ]
