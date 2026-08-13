# Adds LoanScheduleSnapshot, which powers "Undo" for the Regenerate
# Schedule action — a full backup of a loan's schedule + key totals taken
# immediately before a regenerate, so it can be restored exactly.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0005_loan_reinstate_fields'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='LoanScheduleSnapshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('reason', models.TextField(blank=True)),
                ('old_schedule_rows', models.JSONField()),
                ('old_loan_fields', models.JSONField()),
                ('new_row_ids', models.JSONField(blank=True, default=list)),
                ('is_undone', models.BooleanField(default=False)),
                ('undone_at', models.DateTimeField(blank=True, null=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('undone_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('loan', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='schedule_snapshots', to='loans.loan')),
            ],
            options={
                'verbose_name': 'Loan Schedule Snapshot',
                'verbose_name_plural': 'Loan Schedule Snapshots',
                'ordering': ['-created_at'],
            },
        ),
    ]
