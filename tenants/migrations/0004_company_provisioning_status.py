from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0003_add_company_plan'),
    ]

    operations = [
        migrations.AddField(
            model_name='company',
            name='provisioning_status',
            field=models.CharField(
                choices=[
                    ('PENDING', 'Pending'),
                    ('RUNNING', 'Provisioning'),
                    ('READY', 'Ready'),
                    ('FAILED', 'Failed'),
                ],
                default='PENDING',
                help_text=(
                    "Tracks background schema creation + seeding via Celery. "
                    "A company is not safe to log into until this reaches READY."
                ),
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='company',
            name='provisioning_error',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='company',
            name='provisioning_started_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='company',
            name='provisioning_completed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
