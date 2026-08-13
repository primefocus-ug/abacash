from django.conf import settings
from django.conf.urls.static import static  # add this import
from django.contrib import admin
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import include, path
from django.views.generic import TemplateView

from accounts.pwa_views import (
    manifest_view,
    icon_view,
    icon_maskable_view,
    service_worker_view,
)


urlpatterns = [
    path("", include("accounts.login_url")),
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("clients/", include("clients.urls")),
    path("loans/", include("loans.urls")),
    path("payments/", include("payments.urls")),
    path("reports/", include("reports.urls")),
    path("platform/", include("tenants.urls")),

    # ── PWA — must stay at the domain root, not under a prefix, so the
    #    service worker's scope covers the whole tenant site ──────────
    path("manifest.webmanifest", manifest_view, name="pwa_manifest"),
    path("sw.js", service_worker_view, name="pwa_service_worker"),
    path("icons/<int:size>.png", icon_view, name="pwa_icon"),
    path("icons/<int:size>-maskable.png", icon_maskable_view, name="pwa_icon_maskable"),
    path("offline/", TemplateView.as_view(template_name="pwa/offline.html"), name="pwa_offline"),
]

if settings.DEBUG:
    try:
        import importlib
        if importlib.util.find_spec("debug_toolbar") is not None:
            urlpatterns.insert(0, path("__debug__/", include("debug_toolbar.urls")))
    except Exception:
        # Skip adding debug toolbar URLs when package isn't installed.
        pass

    # Serve user-uploaded media files (company logos, etc.) in development.
    # MEDIA_URL = "media/" (no leading slash) still works fine here.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)