from django.db import migrations, models

from accounts.models import DEFAULT_LOAN_TERMS


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0011_user_signature"),
    ]

    operations = [
        migrations.AddField(
            model_name="companysettings",
            name="loan_terms_and_conditions",
            field=models.TextField(
                default=DEFAULT_LOAN_TERMS,
                help_text=(
                    "Terms printed on loan schedules. Review with qualified local "
                    "counsel before relying on them as a legal contract."
                ),
            ),
        ),
    ]
