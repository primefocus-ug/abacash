from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("loans", "0006_loanschedulesnapshot"),
    ]

    operations = [
        migrations.AddField(
            model_name="loanproduct",
            name="requires_collateral",
            field=models.BooleanField(
                default=False,
                help_text="If True, client must provide at least one collateral item before approval.",
            ),
        ),
    ]
