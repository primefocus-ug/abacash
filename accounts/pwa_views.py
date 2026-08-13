# accounts/pwa_views.py
#
# PWA endpoints for the tenant-schema URLconf (config/urls.py). These run
# per-request AFTER django_tenants.middleware.main.TenantMainMiddleware has
# already resolved request.tenant from the domain, so everything here is
# naturally tenant-scoped for free — no explicit schema filtering needed,
# the same way accounts.views already works.
#
# Do NOT add these to config/urls_public.py — the public schema has no
# CompanySettings (see context_processors.company), so there's nothing
# tenant-specific to brand a manifest/icon with there.

from django.http import HttpResponse, JsonResponse, HttpResponseNotFound
from django.templatetags.static import static
from django.urls import reverse
from django.utils.http import http_date
from django.views.decorators.http import require_GET

from .models import CompanySettings
from .pwa_icons import get_icon_png, get_icon_etag

ICON_SIZES = (192, 512)


@require_GET
def manifest_view(request):
    tenant = getattr(request, "tenant", None)
    company_settings = CompanySettings.get()
    company_name = (company_settings.company_name if company_settings else None) or (
        getattr(tenant, "name", None) or "Loan Management"
    )

    icons = []
    for size in ICON_SIZES:
        icons.append({
            "src": reverse("pwa_icon", kwargs={"size": size}),
            "sizes": f"{size}x{size}",
            "type": "image/png",
            "purpose": "any",
        })
    icons.append({
        "src": reverse("pwa_icon_maskable", kwargs={"size": 512}),
        "sizes": "512x512",
        "type": "image/png",
        "purpose": "maskable",
    })

    manifest = {
        "name": company_name,
        "short_name": company_name[:12],
        "description": f"{company_name} — Loan Management System",
        "start_url": "/accounts/dashboard/?source=pwa",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait-primary",
        "background_color": "#F5F8FC",
        "theme_color": "#127970",
        "icons": icons,
        "categories": ["finance", "business"],
        "shortcuts": [
            {
                "name": "Record Payment",
                "short_name": "Payment",
                "url": "/payments/record/?source=pwa",
            },
            {
                "name": "New Loan",
                "short_name": "New Loan",
                "url": "/loans/apply/?source=pwa",
            },
        ],
    }

    response = JsonResponse(manifest)
    response["Content-Type"] = "application/manifest+json"
    # Short-ish cache: the manifest itself is tiny and rarely changes, but
    # unlike the icons it has no version/hash in its URL to bust on logo
    # change, so keep this well under the icon's immutable cache lifetime.
    response["Cache-Control"] = "public, max-age=3600"
    return response


def _icon_response(request, size, maskable):
    if size not in ICON_SIZES and size != 512:
        return HttpResponseNotFound()

    company_settings = CompanySettings.get()
    company_name = company_settings.company_name if company_settings else "Company"

    etag = get_icon_etag(company_settings, size, maskable)
    if request.headers.get("If-None-Match") == etag:
        resp = HttpResponse(status=304)
        resp["ETag"] = etag
        return resp

    png_bytes = get_icon_png(company_settings, company_name, size, maskable=maskable)

    response = HttpResponse(png_bytes, content_type="image/png")
    response["ETag"] = etag
    # Icons are safe to cache hard because the ETag changes whenever the
    # tenant uploads a new logo (see get_icon_etag) — the URL is stable,
    # freshness is handled by revalidation, not by cache-busting the URL.
    response["Cache-Control"] = "public, max-age=604800, must-revalidate"
    return response


@require_GET
def icon_view(request, size):
    return _icon_response(request, int(size), maskable=False)


@require_GET
def icon_maskable_view(request, size):
    return _icon_response(request, int(size), maskable=True)


SERVICE_WORKER_JS = r"""
// sw.js — served from the domain root (config/urls.py, not under
// /static/) so its scope is "/". Each tenant subdomain gets its own
// registration since service workers are scoped per-origin by the
// browser — tenant isolation here comes for free from DNS, not code.

const CACHE_VERSION = "v1";
const CACHE_NAME = `lms-cache-${CACHE_VERSION}`;

const PRECACHE_URLS = [
  "/",
  "/offline/",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key.startsWith("lms-cache-") && key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

function isStaticAsset(request) {
  const url = new URL(request.url);
  return (
    url.pathname.startsWith("/static/") ||
    url.pathname.startsWith("/media/") ||
    /\.(?:css|js|woff2?|png|jpg|jpeg|svg|ico)$/.test(url.pathname)
  );
}

self.addEventListener("fetch", (event) => {
  const { request } = event;

  if (request.method !== "GET") return; // never intercept POST (payments!)

  if (isStaticAsset(request)) {
    event.respondWith(
      caches.match(request).then(
        (cached) =>
          cached ||
          fetch(request).then((response) => {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
            return response;
          })
      )
    );
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          return response;
        })
        .catch(() => caches.match(request).then((cached) => cached || caches.match("/offline/")))
    );
  }
});
""".strip()


@require_GET
def service_worker_view(request):
    response = HttpResponse(SERVICE_WORKER_JS, content_type="application/javascript")
    response["Cache-Control"] = "no-cache"
    response["Service-Worker-Allowed"] = "/"
    return response