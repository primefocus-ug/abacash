from django.contrib import messages
from django.core.mail import mail_admins
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST

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
