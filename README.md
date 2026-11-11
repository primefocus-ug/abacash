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

### Terminal debug logging

With `DEBUG=True` in `.env`, the development console shows `DEBUG` and higher
logs with their logger name and source line, for example
`[DEBUG   ] accounts.views:42 | ...`. Use a module logger in application code
to emit a diagnostic:

```python
import logging

logger = logging.getLogger(__name__)
logger.debug("Loaded %s records", records.count())
```

Keep credentials, passwords, tokens, and other sensitive values out of log
messages. Production (`DEBUG=False`) keeps debug-level console output disabled.

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
# Windows (eventlet is installed from requirements.txt)
celery -A config worker --loglevel=info --pool=eventlet
celery -A config beat   --loglevel=info

# Linux VPS
celery -A config worker --loglevel=info
celery -A config beat   --loglevel=info
```

### Automatic Gmail activation emails

Tenant activation email is sent after the Celery provisioning task has
completed migrations and seeded the tenant. Gmail OAuth authorization is
performed once for a single platform sender; access tokens are then refreshed
automatically by the Gmail API backend.

1. Enable the Gmail API in Google Cloud. On the OAuth consent screen, add the
   sender mailbox as a test user while the app is in Testing.
2. Add `http://localhost:8766/` as an Authorized redirect URI for the Web OAuth
   client. If a client secret was exposed, rotate it and download a new client
   JSON before continuing.
3. Run this from the project environment, replacing the path and sender:

   ```powershell
   python manage.py configure_gmail_oauth --client-secrets "C:\path\to\client_secret.json" --sender-email "sender@example.com"
   ```

   Sign in to the sender mailbox in the browser and approve Gmail send access.
   The command saves the refresh token to the ignored
   `google_oauth_token.json` file and enables Gmail delivery in `.env`; it
   does not print the token or store it on tenant records.
4. Restart Django and run a Celery worker so signup provisioning and its
   activation email are processed. On Windows, use the worker command above
   with the `eventlet` pool. Keep the token file in a secret-protected location
   in production and mount it at `GOOGLE_OAUTH_TOKEN_FILE`.

The sender must match the Google account used during authorization (or an
authorized Gmail alias). While an external OAuth app remains in Testing,
Google refresh tokens may expire after seven days; production use requires
publishing/verifying the consent configuration as required by Google.

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
