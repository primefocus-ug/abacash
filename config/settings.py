import os
from pathlib import Path
from urllib.parse import urlparse

from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent

# Logging directory for background job outputs
LOGS_DIR = os.path.join(BASE_DIR, 'logs')
os.makedirs(LOGS_DIR, exist_ok=True)





SECRET_KEY = config("SECRET_KEY", default="devv-insecure-change-me-in-production")
DEBUG =True
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="127.0.0.1,localhost,.localhost", cast=Csv())



def _database_from_url(url: str) -> dict:
    u = urlparse(url)
    if u.scheme not in ("postgres", "postgresql"):
        raise ValueError(
            f"DATABASE_URL must be postgres:// or postgresql:// (Postgres is "
            f"required for django-tenants), got {u.scheme!r}"
        )
    return {
        "ENGINE": "django_tenants.postgresql_backend",
        "NAME": (u.path or "").lstrip("/"),
        "USER": u.username or "postgres",
        "PASSWORD": u.password or "@Developer25",
        "HOST": u.hostname or "localhost",
        "PORT": str(u.port or 5432),
    }


DATABASES = {
    "default": _database_from_url(
        config("DATABASE_URL", default="postgres://postgres:@Developer25@localhost:5432/db")
    )
}

DATABASE_ROUTERS = ("django_tenants.routers.TenantSyncRouter",)

# ------------------------------------------------------------------ #
# Tenancy
# ------------------------------------------------------------------ #
TENANT_MODEL = "tenants.Company"
TENANT_DOMAIN_MODEL = "tenants.Domain"

PUBLIC_SCHEMA_URLCONF = "config.urls_public"
PUBLIC_DOMAIN = config("PUBLIC_DOMAIN", default="abacash.loan")
TENANT_PUBLIC_DOMAIN = config("TENANT_PUBLIC_DOMAIN", default="abacash.loan")
# Public admin credentials (used to protect the platform onboarding UI). In
# production, set these via environment variables and keep the password secret.
PUBLIC_ADMIN_USERNAME = config("PUBLIC_ADMIN_USERNAME", default="admin")
PUBLIC_ADMIN_PASSWORD = config("PUBLIC_ADMIN_PASSWORD", default="@Developer25")
# How long the signed public-admin cookie remains valid (seconds)
PUBLIC_ADMIN_COOKIE_AGE = config("PUBLIC_ADMIN_COOKIE_AGE", default=86400, cast=int)

SHOW_PUBLIC_IF_NO_TENANT_FOUND = True

SHARED_APPS = [
    "django_tenants",
    "tenants",
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    # Celery Beat's scheduler is a single global process — it never runs
    # inside a tenant's schema, so its own tables must live in `public`,
    # not per-tenant. The reminders task itself loops over tenants.
    "django_celery_beat",
]


TENANT_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.admin",
    "django.contrib.humanize",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.sites",
    # Third party
    "allauth",
    "allauth.account",
    "auditlog",
    "crispy_forms",
    "crispy_bootstrap5",
    "django_htmx",
    "django_extensions",
    # Local
    "accounts.apps.AccountsConfig",
    "clients.apps.ClientsConfig",
    "loans.apps.LoansConfig",
    "payments.apps.PaymentsConfig",
    "reminders.apps.RemindersConfig",
    "reports.apps.ReportsConfig",
]

INSTALLED_APPS = list(SHARED_APPS) + [app for app in TENANT_APPS if app not in SHARED_APPS]

MIDDLEWARE = [
    "django_tenants.middleware.main.TenantMainMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "auditlog.middleware.AuditlogMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

ROOT_URLCONF = "config.urls"


TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "config.context_processors.company",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Kampala"
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


AUTH_USER_MODEL = "accounts.User"

SITE_ID = 1

# Defaults used when seeding a fresh tenant after migrations
TENANT_INITIAL_ADMIN_USERNAME = config('TENANT_INITIAL_ADMIN_USERNAME', default='admin')
TENANT_INITIAL_ADMIN_PASSWORD = config('TENANT_INITIAL_ADMIN_PASSWORD', default='@Developer25')

# ------------------------------------------------------------------ #
# Logging
# ------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "file": {
            "level": "INFO",
            "class": "logging.FileHandler",
            "filename": str(BASE_DIR / "logs" / "lendip.log"),
            "formatter": "verbose",
            "encoding": "utf-8",
        },
        "payments_file": {
            "level": "ERROR",
            "class": "logging.FileHandler",
            "filename": str(BASE_DIR / "logs" / "payments.log"),
            "formatter": "verbose",
            "encoding": "utf-8",
        },
        "onboarding_file": {
            "level": "DEBUG",
            "class": "logging.FileHandler",
            "filename": str(BASE_DIR / "logs" / "onboarding.log"),
            "formatter": "verbose",
            "encoding": "utf-8",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
        "payments": {
            "handlers": ["console", "payments_file"],
            "level": "ERROR",
            "propagate": False,
        },
        "tenants": {
            "handlers": ["console", "onboarding_file"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

AUTHENTICATION_BACKENDS = [
    # Replaces ModelBackend: same behaviour, but also matches on email.
    "accounts.backends.EmailOrUsernameModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]

CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
if DEBUG:
    STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"
else:
    STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"

LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"


MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Without this, all tenants share one physical media folder — uploaded
# client photos/documents from every tenant would be written into the
# same directory tree with no isolation. This creates a per-tenant
# subdirectory under MEDIA_ROOT automatically.
DEFAULT_FILE_STORAGE = "django_tenants.files.storage.TenantFileSystemStorage"
MULTITENANT_RELATIVE_MEDIA_ROOT = "%s"

INTERNAL_IPS = ["127.0.0.1"]

CELERY_BROKER_URL = config("REDIS_URL", default="redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TIMEZONE = "Africa/Kampala"
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]

# ------------------------------------------------------------------ #
# Africa's Talking (SMS)                                              #
# ------------------------------------------------------------------ #
AT_API_KEY = config("AT_API_KEY", default="")
AT_USERNAME = config("AT_USERNAME", default="sandbox")
AT_SENDER_ID = config("AT_SENDER_ID", default="ABAUGANDA")

# ------------------------------------------------------------------ #
# Twilio (WhatsApp)                                                    #
# ------------------------------------------------------------------ #
TWILIO_ACCOUNT_SID = config("TWILIO_ACCOUNT_SID", default="")
TWILIO_AUTH_TOKEN = config("TWILIO_AUTH_TOKEN", default="")
TWILIO_WHATSAPP_FROM = config("TWILIO_WHATSAPP_FROM", default="whatsapp:+14155238886")

# ------------------------------------------------------------------ #
# Email (error alerts / contact form)                                  #
# ------------------------------------------------------------------ #
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = config("EMAIL_HOST", default="smtp.gmail.com")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_USE_TLS = True
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = config("EMAIL_HOST_USER", default="noreply@abauganda.com")

# ------------------------------------------------------------------ #
# Business rules                                                       #
# ------------------------------------------------------------------ #
MANAGER_APPROVAL_LIMIT = 5_000_000  # UGX fallback; per-tenant value lives on CompanySettings