from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0019_alter_user_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="companysettings",
            name="penalties_enabled",
            field=models.BooleanField(
                default=True,
                help_text="Allow late-payment penalties on new and updated loans for this tenant.",
            ),
        ),
    ]
