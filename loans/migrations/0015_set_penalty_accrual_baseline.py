from django.db import migrations
from django.utils import timezone


def set_existing_penalty_baseline(apps, schema_editor):
    CompanySettings = apps.get_model("accounts", "CompanySettings")
    LoanSchedule = apps.get_model("loans", "LoanSchedule")
    database = schema_editor.connection.alias
    settings = CompanySettings.objects.using(database).first()
    grace_period_days = settings.grace_period_days if settings else 3
    today = timezone.localdate()

    schedules = (
        LoanSchedule.objects.using(database)
        .select_related("loan")
        .filter(
            loan__status__in=("ACTIVE", "RESTRUCTURED"),
            status__in=("PENDING", "OVERDUE", "PARTIAL"),
        )
    )
    for schedule in schedules.iterator(chunk_size=500):
        days_overdue = max(
            (today - schedule.due_date).days - grace_period_days,
            0,
        )
        if schedule.loan.penalty_frequency == "DAILY":
            periods = days_overdue
        else:
            periods = (days_overdue + 29) // 30
        schedule.penalty_periods_processed = periods
        schedule.save(update_fields=["penalty_periods_processed"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0021_companysettings_penalty_frequency_and_more"),
        ("loans", "0014_loanschedule_penalty_paid_and_more"),
    ]

    operations = [
        migrations.RunPython(
            set_existing_penalty_baseline,
            migrations.RunPython.noop,
        ),
    ]
