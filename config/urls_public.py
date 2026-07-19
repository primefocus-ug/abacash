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
    path("", include(("tenants.urls", "tenants"), namespace="tenants")),
    # robots.txt and sitemap served from views
    path("robots.txt", tenant_views.robots_txt, name="robots_txt"),
    path("sitemap.xml", tenant_views.sitemap_xml, name="sitemap_xml"),
]
