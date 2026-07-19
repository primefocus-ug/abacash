from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
    verbose_name = "Accounts"

    def ready(self):
        import accounts.audit  # noqa: F401 — registers login/logout signals
        # register tenant post-migrate signals which seed initial data inside a tenant
        try:
            import accounts.signals  # noqa: F401
        except Exception:
            # Avoid preventing Django from starting if signals import fails
            pass
