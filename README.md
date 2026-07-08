# ABA Uganda — Loan Management System

Django 5 + PostgreSQL + HTMX + dark theme CSS

## Project Structure

```
aba_uganda/        # project config, settings, celery, templatetags
accounts/          # custom User model, login, dashboards
clients/           # client registration and management
loans/             # loan products, applications, approval workflow
payments/          # payment recording and receipts
reminders/         # Celery tasks for SMS/WhatsApp reminders
reports/           # loan book, collections, overdue, income statement
templates/         # all HTML templates (dark theme)
static/css/        # aba.css — full dark theme design system
static/js/         # aba.js — sidebar, HTMX helpers, Chart.js
```

## Setup (Windows local dev)

Use Python 3.12 for the verified local setup path.

```bat
py -3.12 -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
copy .env.example .env
REM  Edit .env with your DB credentials
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Setup (Ubuntu VPS production)

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in production values
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
gunicorn aba_uganda.wsgi:application --bind unix:/tmp/aba_uganda.sock --workers 3
```

## Celery (SMS reminders)

```bash
# Windows (requires eventlet): pip install eventlet
celery -A aba_uganda worker --loglevel=info --pool=eventlet
celery -A aba_uganda beat   --loglevel=info

# Linux VPS
celery -A aba_uganda worker --loglevel=info
celery -A aba_uganda beat   --loglevel=info
```

After first migration, go to Django Admin > Periodic Tasks
and create a task pointing to `reminders.check_due_payments`
on a crontab of every day at 08:00.

## User Roles

| Role    | Permissions |
|---------|-------------|
| Cashier | Record payments, view own loans, print receipts |
| Manager | + Apply loans, approve up to UGX 5M, view reports |
| CEO     | Full access, configure products, all reports, approve any amount |

## Key URLs

| URL | Page |
|-----|------|
| `/accounts/login/` | Login |
| `/dashboard/` | Role-based dashboard |
| `/clients/` | Client list |
| `/clients/new/` | Register client |
| `/loans/` | All loans |
| `/loans/apply/` | New loan application |
| `/payments/record/` | Record payment |
| `/reports/` | Reports index |
| `/admin/` | Django admin |
