import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ #
# Small os.getenv helpers (os.getenv only ever returns str or None,
# so bools/ints/lists need casting by hand)
# ------------------------------------------------------------------ #
def env_bool(key, default=False):
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def env_int(key, default=None):
    val = os.getenv(key)
    return int(val) if val not in (None, "") else default


def env_list(key, default=""):
    val = os.getenv(key, default)
    return [item.strip() for item in val.split(",") if item.strip()]


# ------------------------------------------------------------------ #
# Core / environment
#
# These env vars must actually be present in the process environment
# when Django starts. With systemd that means EnvironmentFile=.env in
# the .service unit (already set in gunicorn.service / celery.service /
# celerybeat.service) — systemd loads the file itself, so os.getenv()
# sees the values with no extra loader needed in this file.
#
# If you ever run manage.py by hand in a plain shell, remember
# os.getenv() will NOT read .env automatically — you'd need to
# `export $(cat .env | xargs)` first, or run under systemd/docker
# which inject env vars for you.
# ------------------------------------------------------------------ #
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable is not set")

DEBUG = env_bool("DEBUG", default=False)

# Base domain lets us build ALLOWED_HOSTS / CSRF origins for every tenant
# subdomain without hardcoding each one.
BASE_DOMAIN = os.getenv("BASE_DOMAIN", "abacash.loan")

ALLOWED_HOSTS = env_list(
    "ALLOWED_HOSTS",
    default=f".{BASE_DOMAIN},localhost,127.0.0.1",
)

# Django 4+ requires scheme + supports a leading wildcard label here.
CSRF_TRUSTED_ORIGINS = env_list(
    "CSRF_TRUSTED_ORIGINS",
    default=f"https://*.{BASE_DOMAIN},https://{BASE_DOMAIN}",
)

# Canonical public domain (used in sitemap + SEO meta tags)
PUBLIC_DOMAIN = os.getenv("PUBLIC_DOMAIN", "abacash.loan")
SITE_URL = os.getenv("SITE_URL", "https://abacash.loan")

# ------------------------------------------------------------------ #
# Database — set directly from separate env vars, no DATABASE_URL
# parsing. django-tenants requires Postgres.
# ------------------------------------------------------------------ #
DATABASES = {
    "default": {
        "ENGINE": "django_tenants.postgresql_backend",
        "NAME": os.getenv("DB_NAME", "lendip_db"),
        "USER": os.getenv("DB_USER", "postgres"),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": os.getenv("DB_HOST", "localhost"),
        "PORT": os.getenv("DB_PORT", "5432"),
    }
}

if not DATABASES["default"]["PASSWORD"] and not DEBUG:
    raise RuntimeError("DB_PASSWORD environment variable is not set")

DATABASE_ROUTERS = ("django_tenants.routers.TenantSyncRouter",)

# ------------------------------------------------------------------ #
# Tenancy
# ------------------------------------------------------------------ #
TENANT_MODEL = "tenants.Company"
TENANT_DOMAIN_MODEL = "tenants.Domain"

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
# django-tenants: public schema (abacash.loan) gets its own URL config
# so it shows the marketing landing page instead of the app login.
PUBLIC_SCHEMA_URLCONF = "config.urls_public"


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

# ------------------------------------------------------------------ #
# Logging
# ------------------------------------------------------------------ #
(BASE_DIR / "logs").mkdir(parents=True, exist_ok=True)

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
    STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

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

INTERNAL_IPS = env_list("INTERNAL_IPS", default="127.0.0.1")

CELERY_BROKER_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TIMEZONE = "Africa/Kampala"
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]

# ------------------------------------------------------------------ #
# Africa's Talking (SMS)                                              #
# ------------------------------------------------------------------ #
AT_API_KEY = os.getenv("AT_API_KEY", "")
AT_USERNAME = os.getenv("AT_USERNAME", "sandbox")
AT_SENDER_ID = os.getenv("AT_SENDER_ID", "ABAUGANDA")

# ------------------------------------------------------------------ #
# Twilio (WhatsApp)                                                    #
# ------------------------------------------------------------------ #
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")

# ------------------------------------------------------------------ #
# Email (error alerts / contact form)                                  #
# ------------------------------------------------------------------ #
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = env_int("EMAIL_PORT", default=587)
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.getenv("EMAIL_HOST_USER", "noreply@abauganda.com")

ADMINS = [
    tuple(pair.split(":", 1))
    for pair in env_list("ADMINS", default="")
    if ":" in pair
]
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# ------------------------------------------------------------------ #
# Business rules                                                       #
# ------------------------------------------------------------------ #
MANAGER_APPROVAL_LIMIT = 5_000_000  # UGX fallback; per-tenant value lives on CompanySettings

# ------------------------------------------------------------------ #
# Security — nginx terminates TLS and proxies to gunicorn over HTTP,
# so Django needs to trust the X-Forwarded-Proto header nginx sets,
# and these hardening flags should only bite in production (DEBUG=False).
# ------------------------------------------------------------------ #
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", default=not DEBUG)
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# Only enable HSTS once you've confirmed HTTPS works cleanly on the
# apex + every subdomain (Cloudflare SSL mode must be "Full (strict)").
SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", default=0 if DEBUG else 3600)
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = False