from django.contrib import messages
from django.core.mail import mail_admins
from django.conf import settings as django_settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST
from django.views.decorators.cache import cache_control

from .models import CompanyRegistration


def landing(request):
    """Public landing page — marketing + registration form."""
    return render(request, "tenants/landing.html")


@require_POST
def register(request):
    """Handle registration form submission (supports both AJAX and normal POST)."""
    data = {
        "company_name": request.POST.get("company_name", "").strip(),
        "contact_name": request.POST.get("contact_name", "").strip(),
        "email":        request.POST.get("email", "").strip(),
        "phone":        request.POST.get("phone", "").strip(),
        "country":      request.POST.get("country", "Uganda").strip(),
        "city":         request.POST.get("city", "").strip(),
        "plan":         request.POST.get("plan", "STARTER"),
        "message":      request.POST.get("message", "").strip(),
    }

    errors = {}
    for field in ("company_name", "contact_name", "email", "phone"):
        if not data[field]:
            errors[field] = "This field is required."

    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"

    if errors:
        if is_ajax:
            return JsonResponse({"ok": False, "errors": errors}, status=400)
        messages.error(request, "Please fill in all required fields.")
        return render(request, "tenants/landing.html", {"form_data": data, "errors": errors})

    reg = CompanyRegistration.objects.create(**data)

    # Notify admins
    try:
        mail_admins(
            subject=f"New registration: {reg.company_name} ({reg.get_plan_display()})",
            message=(
                f"Company : {reg.company_name}\n"
                f"Contact : {reg.contact_name}\n"
                f"Email   : {reg.email}\n"
                f"Phone   : {reg.phone}\n"
                f"City    : {reg.city}, {reg.country}\n"
                f"Plan    : {reg.get_plan_display()}\n\n"
                f"Message :\n{reg.message or '—'}\n"
            ),
            fail_silently=True,
        )
    except Exception:
        pass

    if is_ajax:
        return JsonResponse({"ok": True, "message": "Thank you! We'll be in touch within 24 hours."})

    return redirect("tenants:success")


def success(request):
    return render(request, "tenants/success.html")


@cache_control(max_age=86400)
def robots_txt(request):
    """
    /robots.txt
    - Public domain (abacash.loan): allow all, point to sitemap.
    - Tenant subdomains (*.abacash.loans): block all crawlers — the app
      is private and should never appear in search results.
    """
    host = request.get_host().split(":")[0].lower()
    public_domain = getattr(django_settings, "PUBLIC_DOMAIN", "abacash.loan")
    site_url = getattr(django_settings, "SITE_URL", "https://abacash.loan")

    if host == public_domain:
        content = (
            "User-agent: *\n"
            "Allow: /\n"
            "Disallow: /admin/\n"
            "Disallow: /platform/\n"
            f"Sitemap: {site_url}/sitemap.xml\n"
        )
    else:
        # Tenant subdomain — keep the app private
        content = "User-agent: *\nDisallow: /\n"

    return HttpResponse(content, content_type="text/plain")


@cache_control(max_age=3600)
def sitemap_xml(request):
    """
    /sitemap.xml — only meaningful on the public domain.
    Lists the static marketing pages for Google Search Console.
    """
    site_url = getattr(django_settings, "SITE_URL", "https://abacash.loan")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xsi:schemaLocation="http://www.sitemaps.org/schemas/sitemap/0.9
        http://www.sitemaps.org/schemas/sitemap/0.9/sitemap.xsd">
  <url>
    <loc>{site_url}/</loc>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>{site_url}/register/</loc>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>
</urlset>"""
    return HttpResponse(xml, content_type="application/xml")
