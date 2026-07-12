"""
config/urls_public.py
---------------------
URL configuration served ONLY on the public schema (abacash.loan).
Tenant subdomains (test.abacash.loans) use config/urls.py instead.
"""
from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from tenants import views as tenant_views

urlpatterns = [
    # Marketing landing page at the root
    path("",          tenant_views.landing,  name="public_landing"),
    path("register/", tenant_views.register, name="public_register"),
    path("success/",  tenant_views.success,  name="public_success"),

    # robots.txt and sitemap served from views
    path("robots.txt", tenant_views.robots_txt,  name="robots_txt"),
    path("sitemap.xml",tenant_views.sitemap_xml, name="sitemap_xml"),

    # Django admin still accessible on public domain for super-admins
    path("admin/", admin.site.urls),

    # Tenant management platform
    path("platform/", include("tenants.urls")),
]
