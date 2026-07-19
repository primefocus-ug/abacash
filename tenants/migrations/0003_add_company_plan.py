from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0002_companyregistration"),
    ]

    operations = [
        migrations.AddField(
            model_name="company",
            name="plan",
            field=models.CharField(
                choices=[
                    ("STARTER", "Starter — up to 500 clients"),
                    ("PROFESSIONAL", "Professional — up to 2,000 clients"),
                    ("ENTERPRISE", "Enterprise — unlimited"),
                ],
                default="STARTER",
                max_length=20,
            ),
        ),
    ]
