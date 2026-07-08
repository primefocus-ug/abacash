from django.conf import settings
from django.contrib import admin
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import include, path




urlpatterns = [
    path("",include("accounts.login_url")),
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("clients/", include("clients.urls")),
    path("loans/", include("loans.urls")),
    path("payments/", include("payments.urls")),
    path("reports/", include("reports.urls")),
    path("platform/", include("tenants.urls")),
]

if settings.DEBUG:
    try:
        import importlib
        if importlib.util.find_spec("debug_toolbar") is not None:
            urlpatterns.insert(0, path("__debug__/", include("debug_toolbar.urls")))
    except Exception:
        # Skip adding debug toolbar URLs when package isn't installed.
        pass
