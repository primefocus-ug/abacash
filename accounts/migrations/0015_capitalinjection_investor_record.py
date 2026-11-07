from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0014_alter_user_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="capitalinjection",
            name="investor_record",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="capital_injections",
                to="accounts.investor",
            ),
        ),
    ]
