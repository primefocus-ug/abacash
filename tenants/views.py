from django.contrib import messages
from django.core.mail import mail_admins, send_mail
from django.conf import settings as django_settings
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.core.validators import validate_email
from django.db import DatabaseError, ProgrammingError, connection
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET
from django.utils import timezone
from django.utils.text import slugify

from django_tenants.utils import schema_context

import secrets
import logging

logger = logging.getLogger(__name__)


from .models import Company, CompanyRegistration, Domain, Plan

PAGE_LINKS = [
    {"label": "Home", "url_name": "landing"},
    {"label": "Features", "url_name": "features"},
    {"label": "Pricing", "url_name": "pricing"},
    {"label": "Support", "url_name": "support"},
    {"label": "Register", "url_name": "public_register"},
    {"label": "Login", "url_name": "public_login"},
    {"label": "Admin", "url_name": "public_admin"},
    {"label": "Pages", "url_name": "pages"},
]

FEATURE_LIST = [
    {
        "icon": "📋",
        "title": "Loan Applications",
        "description": "Streamlined application workflow with instant approval tracking and document management.",
    },
    {
        "icon": "💰",
        "title": "Payment Processing",
        "description": "Record payments, generate receipts, and track repayment schedules effortlessly.",
    },
    {
        "icon": "📊",
        "title": "Advanced Reports",
        "description": "Comprehensive reporting including loan book, collections, overdue analysis, and income statements.",
    },
    {
        "icon": "🔔",
        "title": "Smart Reminders",
        "description": "Automated SMS and WhatsApp reminders for upcoming payments and renewals.",
    },
    {
        "icon": "👥",
        "title": "Multi-User Access",
        "description": "Role-based permissions with Cashier, Manager, and CEO access levels.",
    },
    {
        "icon": "🔒",
        "title": "Enterprise Security",
        "description": "Bank-grade encryption, audit logs, and compliance with data protection standards.",
    },
]

PRICING_PLANS = [
    {
        "variant": "starter",
        "name": "STARTER",
        "price": "Free",
        "description": "Perfect for getting started",
        "features": [
            "Up to 100 clients",
            "Basic loan tracking",
            "Payment recording",
            "Email support",
        ],
        "button_text": "Get Started",
    },
    {
        "variant": "professional",
        "name": "PROFESSIONAL",
        "price": "Custom",
        "description": "For growing teams",
        "featured": True,
        "features": [
            "Unlimited clients",
            "Advanced reporting",
            "SMS/WhatsApp reminders",
            "Multiple users",
            "Priority support",
        ],
        "button_text": "Request Demo",
    },
    {
        "variant": "enterprise",
        "name": "ENTERPRISE",
        "price": "Custom",
        "description": "For large organizations",
        "features": [
            "Everything in Professional",
            "Multi-branch support",
            "Custom integrations",
            "Dedicated account manager",
            "24/7 support",
        ],
        "button_text": "Contact Sales",
    },
]


def landing(request):
    return render(request, "tenants/landing_new.html", {
        "page_links": PAGE_LINKS,
        "feature_list": FEATURE_LIST,
        "pricing_plans": PRICING_PLANS,
    })


def features(request):
    return render(request, "tenants/features.html", {
        "page_links": PAGE_LINKS,
        "feature_list": FEATURE_LIST,
    })


def pricing(request):
    return render(request, "tenants/pricing.html", {
        "page_links": PAGE_LINKS,
        "pricing_plans": PRICING_PLANS,
    })


def pages(request):
    return render(request, "tenants/pages.html", {
        "page_links": PAGE_LINKS,
        "pages": [
            {"title": "Home", "description": "Visit the marketing homepage.", "url_name": "tenants:landing"},
            {"title": "Features", "description": "Learn about platform capabilities.", "url_name": "tenants:features"},
            {"title": "Pricing", "description": "Review plans and pricing.", "url_name": "tenants:pricing"},
            {"title": "Public Admin", "description": "Onboard new tenants and manage the platform.", "url_name": "tenants:public_admin"},
            {"title": "Register", "description": "Apply for your Abacash account.", "url_name": "tenants:public_register"},
            {"title": "Login", "description": "Sign in to your Abacash account.", "url_name": "tenants:public_login"},
            {"title": "Support", "description": "Get help from our customer success team.", "url_name": "tenants:support"},
            {"title": "Success", "description": "Confirmation after registration.", "url_name": "tenants:success"},
        ],
    })


def public_admin_login(request):
    """Public-admin login for the /public-admin/ control panel.

    Authenticates against real, individually-hashed PlatformAdmin rows (see
    tenants.auth and tenants.models.PlatformAdmin) rather than a single shared
    credential pair — that legacy scheme has been retired (see settings.py).
    Uses a normal server-side session (django.contrib.sessions is enabled on
    the public schema — see settings.py) rather than a hand-signed cookie.
    """
    from tenants.auth import authenticate_platform_admin, login_platform_admin

    error = None
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()

        admin = authenticate_platform_admin(username, password)
        if admin is not None:
            login_platform_admin(request, admin)
            return redirect('platform_admin:dashboard')
        else:
            # Deliberately vague: don't reveal whether the username or
            # password was wrong.
            error = 'Invalid credentials.'

    return render(request, 'tenants/public_admin_login.html', { 'error': error })


def public_admin_logout(request):
    """End the platform admin's session and redirect to the landing page."""
    from tenants.auth import logout_platform_admin

    logout_platform_admin(request)
    return redirect('tenants:landing')


def public_login(request):
    tenant_domain = getattr(django_settings, "TENANT_PUBLIC_DOMAIN", "abacash.loan")
    target_url = None
    form_error = None

    if request.method == "POST":
        tenant_slug = request.POST.get("tenant_slug", "").strip().lower()
        if not tenant_slug:
            form_error = "Enter your company or tenant slug to continue."
        else:
            target_url = f"https://{tenant_slug}.{tenant_domain}/"
            return redirect(target_url)

    return render(request, "tenants/login.html", {
        "page_links": PAGE_LINKS,
        "tenant_domain": tenant_domain,
        "form_error": form_error,
        "target_url": target_url,
    })


def support(request):
    return render(request, "tenants/support.html", {
        "page_links": PAGE_LINKS,
    })


def _tenant_user_table_available(company):
    """Avoid querying the tenant user model before its schema has been migrated."""
    from accounts.models import User

    try:
        with schema_context(company.schema_name):
            return User._meta.db_table in connection.introspection.table_names()
    except DatabaseError:
        logger.exception("Could not inspect user table for tenant %s", company.schema_name)
        return None


def _send_tenant_user_access_email(user, company):
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.encoding import force_bytes
    from django.utils.http import urlsafe_base64_encode

    primary_domain = Domain.objects.filter(tenant=company).order_by(
        "-is_primary"
    ).values_list("domain", flat=True).first()
    domain = primary_domain or (
        f"{company.schema_name}.{getattr(django_settings, 'TENANT_PUBLIC_DOMAIN', 'abacash.loan')}"
    )
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    scheme = "http" if django_settings.DEBUG else "https"
    return send_mail(
        subject=f"Set up your Abacash account for {company.name}",
        message=(
            f"Hello {user.get_full_name()},\n\n"
            f"An administrator created or requested access for your account in {company.name}.\n"
            f"Use this secure link to set or reset your password: "
            f"{scheme}://{domain}/accounts/reset/{uid}/{token}/\n\n"
            "If you did not expect this message, contact your organization administrator."
        ),
        from_email=getattr(django_settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[user.email],
        fail_silently=False,
    )


def public_admin(request):
    # Require a logged-in PlatformAdmin (see tenants.auth). Attaches
    # request.platform_admin for use in the view/template below.
    from tenants.auth import get_platform_admin

    admin = get_platform_admin(request)
    if admin is None:
        return redirect('tenants:public_admin_login')
    request.platform_admin = admin


    tenant_queryset = Company.objects.exclude(schema_name="public").order_by("name")
    registration_queryset = CompanyRegistration.objects.order_by("-submitted_at")

    tenant_search = request.GET.get("tenant_q", "").strip()
    tenant_status = request.GET.get("tenant_status", "").strip()
    tenant_plan = request.GET.get("tenant_plan", "").strip()
    registration_search = request.GET.get("registration_q", "").strip()
    registration_status = request.GET.get("registration_status", "").strip()
    registration_plan = request.GET.get("registration_plan", "").strip()

    if tenant_search:
        tenant_queryset = tenant_queryset.filter(
            Q(name__icontains=tenant_search) | Q(schema_name__icontains=tenant_search)
        )
    if tenant_status == "active":
        tenant_queryset = tenant_queryset.filter(is_active=True)
    elif tenant_status == "suspended":
        tenant_queryset = tenant_queryset.filter(is_active=False)
    if tenant_plan in Plan.values:
        tenant_queryset = tenant_queryset.filter(plan=tenant_plan)

    if registration_search:
        registration_queryset = registration_queryset.filter(
            Q(company_name__icontains=registration_search)
            | Q(contact_name__icontains=registration_search)
            | Q(email__icontains=registration_search)
        )
    if registration_status in CompanyRegistration.Status.values:
        registration_queryset = registration_queryset.filter(status=registration_status)
    if registration_plan in Plan.values:
        registration_queryset = registration_queryset.filter(plan=registration_plan)

    tenant_count = Company.objects.exclude(schema_name="public").count()
    active_tenant_count = Company.objects.exclude(schema_name="public").filter(
        is_active=True
    ).count()
    inactive_tenant_count = tenant_count - active_tenant_count
    tenant_page = Paginator(tenant_queryset, 10).get_page(request.GET.get("tenant_page", 1))
    registration_page = Paginator(registration_queryset, 10).get_page(
        request.GET.get("registration_page", 1)
    )
    tenants = []
    for company in tenant_page.object_list:
        domains = list(
            Domain.objects.filter(tenant=company).values_list("domain", flat=True)
        )
        user_table_available = _tenant_user_table_available(company)
        tenants.append({
            "company": company,
            "domains": domains,
            "user_table_available": user_table_available,
            "user_table_check_failed": user_table_available is None,
        })
    recent_registrations = registration_page.object_list

    admin_context = {
        "page_links": PAGE_LINKS,
        "platform_admin": admin,
        "plan_choices": CompanyRegistration.Plan.choices,
        "registration_status_choices": CompanyRegistration.Status.choices,
        "recent_registrations": recent_registrations,
        "registration_page": registration_page,
        "registration_count": registration_page.paginator.count,
        "registration_search": registration_search,
        "registration_status": registration_status,
        "registration_plan": registration_plan,
        "tenants": tenants,
        "tenant_page": tenant_page,
        "tenant_result_count": tenant_page.paginator.count,
        "tenant_search": tenant_search,
        "tenant_status": tenant_status,
        "tenant_plan": tenant_plan,
        "tenant_count": tenant_count,
        "active_tenant_count": active_tenant_count,
        "inactive_tenant_count": inactive_tenant_count,
        "lead_count": CompanyRegistration.objects.count(),
        "tenant_domain_root": getattr(django_settings, "TENANT_PUBLIC_DOMAIN", "abacash.loan"),
    }

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "onboard_tenant":
            name = request.POST.get("company_name", "").strip()
            schema = request.POST.get("tenant_slug", "").strip().lower().replace("-", "_")
            plan = request.POST.get("plan", "STARTER")
            admin_email = request.POST.get("admin_email", "").strip()
            admin_password_input = request.POST.get("admin_password", "").strip()
            admin_password = admin_password_input or secrets.token_urlsafe(10)
            tenant_domain_root = request.POST.get("tenant_domain_root", getattr(django_settings, "TENANT_PUBLIC_DOMAIN", "abacash.loan")).strip()
            requested_domain = request.POST.get("tenant_domain", "").strip()
            domain = requested_domain or f"{schema}.{tenant_domain_root}"

            if not name or not schema or not admin_email:
                messages.error(request, "Company name, tenant slug and admin email are required to onboard a tenant.")
                return render(request, "tenants/public_admin.html", admin_context)

            if Company.objects.filter(schema_name=schema).exists():
                messages.error(request, f"Tenant schema '{schema}' already exists. Choose a different slug.")
                return render(request, "tenants/public_admin.html", admin_context)

            try:
                from tenants.tasks import provision_tenant_task

                company = Company.objects.create(schema_name=schema, name=name, is_active=True, plan=plan)
                Domain.objects.create(domain=domain, tenant=company, is_primary=True)

                provision_tenant_task.delay(
                    company.id, domain, admin_email,
                    password=admin_password, plan=plan,
                    phone=request.POST.get("phone", "").strip(),
                    address=request.POST.get("address", "").strip(),
                    company_email=request.POST.get("company_email", "").strip() or admin_email,
                    notify=True,
                )

                messages.success(
                    request,
                    f"Provisioning '{name}' has started. The administrator will receive an account activation email when setup is complete."
                )
                try:
                    return redirect("platform_admin:company_detail", schema_name=schema)
                except Exception:
                    # platform_admin may not be wired in yet — fall back gracefully
                    return redirect("tenants:public_admin")
            except Exception as exc:
                messages.error(request, f"Could not start onboarding: {exc}")
                return render(request, "tenants/public_admin.html", admin_context)

        if action == "onboard_registration":
            registration_id = request.POST.get("registration_id")
            password_input = request.POST.get("admin_password", "").strip()
            password = password_input or secrets.token_urlsafe(10)
            try:
                registration = CompanyRegistration.objects.get(pk=registration_id)
            except CompanyRegistration.DoesNotExist:
                messages.error(request, "Selected registration could not be found.")
                return render(request, "tenants/public_admin.html", admin_context)
            if registration.status != CompanyRegistration.Status.PENDING:
                messages.warning(request, "Only pending registrations can be onboarded.")
                return redirect("tenants:public_admin")

            schema = slugify(registration.company_name).replace("-", "_")
            plan = registration.plan
            domain_root = getattr(django_settings, "TENANT_PUBLIC_DOMAIN", "abacash.loan")
            domain = request.POST.get("tenant_domain", "").strip() or f"{schema}.{domain_root}"

            if Company.objects.filter(schema_name=schema).exists():
                messages.error(request, f"Tenant schema '{schema}' already exists."
                               " Choose a different slug or update the registration record.")
                return render(request, "tenants/public_admin.html", admin_context)

            try:
                from tenants.tasks import provision_tenant_task

                company = Company.objects.create(schema_name=schema, name=registration.company_name, is_active=True, plan=plan)
                Domain.objects.create(domain=domain, tenant=company, is_primary=True)

                provision_tenant_task.delay(
                    company.id, domain, registration.email,
                    password=password, plan=plan,
                    phone=registration.phone,
                    address=f"{registration.city}, {registration.country}" if registration.city or registration.country else "",
                    company_email=registration.email,
                    notify=True,
                )

                registration.status = CompanyRegistration.Status.ONBOARDED
                registration.save()
                messages.success(
                    request,
                    f"Provisioning for '{registration.company_name}' has started as '{schema}'. "
                    "The administrator will receive an account activation email when setup is complete."
                )
                try:
                    return redirect("platform_admin:company_detail", schema_name=schema)
                except Exception:
                    return redirect("tenants:public_admin")
            except Exception as exc:
                messages.error(request, f"Could not start onboarding: {exc}")
                return render(request, "tenants/public_admin.html", admin_context)

        if action == "update_registration_status":
            registration = CompanyRegistration.objects.filter(
                pk=request.POST.get("registration_id")
            ).first()
            status = request.POST.get("registration_status", "").strip().upper()
            editable_statuses = {
                CompanyRegistration.Status.PENDING,
                CompanyRegistration.Status.CONTACTED,
                CompanyRegistration.Status.REJECTED,
            }
            if registration is None:
                messages.error(request, "Selected registration could not be found.")
            elif status not in editable_statuses:
                messages.error(request, "Select a valid lead status. Onboarded status is set by tenant provisioning.")
            elif registration.status == CompanyRegistration.Status.ONBOARDED:
                messages.error(request, "An onboarded registration cannot be changed from the lead controls.")
            else:
                registration.status = status
                registration.save(update_fields=["status"])
                messages.success(request, f"Updated the lead status for {registration.company_name}.")
            return redirect("tenants:public_admin")

        if action == "assign_role":
            tenant_schema = request.POST.get("tenant_schema", "").strip().lower().replace("-", "_")
            user_email = request.POST.get("role_email", "").strip()
            role = request.POST.get("role", "CASHIER").strip().upper()
            if not tenant_schema or not user_email:
                messages.error(request, "Tenant schema and user email are required to assign a role.")
                return render(request, "tenants/public_admin.html", admin_context)

            company = Company.objects.filter(
                schema_name=tenant_schema
            ).exclude(schema_name="public").first()
            if company is None:
                messages.error(request, f"Tenant schema '{tenant_schema}' does not exist.")
                return redirect("tenants:public_admin")

            user_table_available = _tenant_user_table_available(company)
            if user_table_available is None:
                messages.error(
                    request,
                    f"Could not verify the account tables for tenant '{company.name}'. "
                    "Check database connectivity and try again.",
                )
                return redirect("tenants:public_admin")
            if not user_table_available:
                messages.error(
                    request,
                    f"Tenant '{company.name}' is not ready for user access management. "
                    "Its account tables are not migrated yet. Wait for provisioning to finish or retry it from tenant details.",
                )
                return redirect("tenants:public_admin")

            from accounts.models import User

            try:
                try:
                    validate_email(user_email)
                except ValidationError:
                    messages.error(request, "Enter a valid user email address.")
                    return redirect("tenants:public_admin")
                if role not in User.Role.values:
                    messages.error(request, "Select a valid tenant user role.")
                    return redirect("tenants:public_admin")
                password = secrets.token_urlsafe(32)
                with schema_context(tenant_schema):
                    user = User.objects.filter(email=user_email).first()
                    if user:
                        user.role = role
                        if role != User.Role.CEO:
                            user.is_superuser = False
                        user.save()
                        messages.success(request, f"Updated role for {user_email} to {role}.")
                    else:
                        username = user_email.split("@")[0]
                        count = 1
                        base_username = username
                        while User.objects.filter(username=username).exists():
                            username = f"{base_username}{count}"
                            count += 1
                        user = User.objects.create_user(
                            username=username,
                            email=user_email,
                            
                            password=password,
                            role=role,
                            is_staff=True,
                            is_superuser=(role == "CEO"),
                        )
                        if _send_tenant_user_access_email(user, company):
                            messages.success(request, f"Created user {user_email} with role {role} in tenant '{tenant_schema}'.")
                        else:
                            messages.warning(
                                request,
                                f"Created user {user_email} in tenant '{tenant_schema}', but the email service "
                                "did not accept the setup message. Use Send password reset to retry.",
                            )
            except ProgrammingError:
                logger.exception("Tenant user table is missing for schema %s", tenant_schema)
                messages.error(
                    request,
                    f"Tenant '{company.name}' has not completed its account migrations. "
                    "Retry provisioning before managing its users.",
                )
                return redirect("tenants:public_admin")
            except Exception:
                logger.exception("Role assignment failed for tenant %s", tenant_schema)
                messages.error(request, "Role assignment failed. Check tenant readiness and try again.")
                return redirect("tenants:public_admin")

            return redirect("tenants:public_admin")

        if action == "reset_tenant_access":
            tenant_schema = request.POST.get("reset_tenant_schema", "").strip().lower().replace("-", "_")
            user_email = request.POST.get("reset_email", "").strip()
            if not tenant_schema or not user_email:
                messages.error(request, "Tenant schema and user email are required to reset access.")
                return render(request, "tenants/public_admin.html", admin_context)
            try:
                validate_email(user_email)
            except ValidationError:
                messages.error(request, "Enter a valid user email address.")
                return redirect("tenants:public_admin")

            company = Company.objects.filter(
                schema_name=tenant_schema
            ).exclude(schema_name="public").first()
            if company is None:
                messages.error(request, f"Tenant schema '{tenant_schema}' does not exist.")
                return redirect("tenants:public_admin")

            user_table_available = _tenant_user_table_available(company)
            if user_table_available is None:
                messages.error(
                    request,
                    f"Could not verify the account tables for tenant '{company.name}'. "
                    "Check database connectivity and try again.",
                )
                return redirect("tenants:public_admin")
            if not user_table_available:
                messages.error(
                    request,
                    f"Tenant '{company.name}' is not ready for access resets because its account tables are not migrated. "
                    "Wait for provisioning to finish or retry it from tenant details.",
                )
                return redirect("tenants:public_admin")

            from accounts.models import User

            try:
                with schema_context(tenant_schema):
                    user = User.objects.filter(email=user_email).first()
                    if not user:
                        messages.error(request, f"No user with email '{user_email}' was found in tenant '{tenant_schema}'.")
                        return redirect("tenants:public_admin")

                    if _send_tenant_user_access_email(user, company):
                        messages.success(request, f"Password reset instructions were sent to {user.email} for tenant '{tenant_schema}'.")
                    else:
                        messages.error(request, f"The email service did not accept password reset instructions for {user.email}.")
            except ProgrammingError:
                logger.exception("Tenant user table is missing during access reset for %s", tenant_schema)
                messages.error(
                    request,
                    f"Tenant '{company.name}' has not completed its account migrations. "
                    "Retry provisioning before resetting user access.",
                )
                return redirect("tenants:public_admin")
            except Exception:
                logger.exception("Access reset failed for tenant %s", tenant_schema)
                messages.error(request, "Access reset failed. Check tenant readiness and email delivery settings.")
                return redirect("tenants:public_admin")

            return redirect("tenants:public_admin")

        if action == "suspend_tenant":
            tenant_schema = request.POST.get("suspend_tenant_schema", "").strip().lower().replace("-", "_")
            if not tenant_schema:
                messages.error(request, "Tenant schema is required to suspend or activate a tenant.")
                return render(request, "tenants/public_admin.html", admin_context)

            try:
                company = Company.objects.get(schema_name=tenant_schema)
                if company.schema_name == "public":
                    messages.error(request, "The public schema cannot be suspended.")
                    return redirect("tenants:public_admin")
                if company.provisioning_status == Company.ProvisioningStatus.RUNNING:
                    messages.warning(request, "Wait for provisioning to finish before changing tenant access.")
                    return redirect("tenants:public_admin")
                company.is_active = not company.is_active
                company.save()
                status_label = "suspended" if not company.is_active else "activated"
                messages.success(request, f"Tenant '{tenant_schema}' was {status_label} successfully.")
            except Company.DoesNotExist:
                messages.error(request, f"Tenant schema '{tenant_schema}' does not exist.")
            except Exception as exc:
                messages.error(request, f"Tenant status update failed: {exc}")

            return redirect("tenants:public_admin")

        if action == "update_subscription":
            tenant_schema = request.POST.get("subscription_tenant_schema", "").strip().lower().replace("-", "_")
            plan = request.POST.get("subscription_plan", "STARTER").strip().upper()
            if not tenant_schema:
                messages.error(request, "Tenant schema is required to update subscription.")
                return render(request, "tenants/public_admin.html", admin_context)

            try:
                company = Company.objects.exclude(schema_name="public").get(schema_name=tenant_schema)
                if plan not in Plan.values:
                    messages.error(request, "Select a valid subscription plan.")
                    return redirect("tenants:public_admin")
                company.plan = plan
                company.save()
                messages.success(request, f"Updated subscription for '{tenant_schema}' to {plan}.")
            except Company.DoesNotExist:
                messages.error(request, f"Tenant schema '{tenant_schema}' does not exist.")
            except Exception as exc:
                messages.error(request, f"Subscription update failed: {exc}")

            return redirect("tenants:public_admin")

    return render(request, "tenants/public_admin.html", admin_context)


def register(request):
    form_data = {
        "company_name": "",
        "contact_name": "",
        "email": "",
        "phone": "",
        "country": "Uganda",
        "city": "",
        "plan": "STARTER",
        "message": "",
    }
    errors = {}

    if request.method == "POST":
        form_data = {
            "company_name": request.POST.get("company_name", "").strip(),
            "contact_name": request.POST.get("contact_name", "").strip(),
            "email":        request.POST.get("email", "").strip(),
            "phone":        request.POST.get("phone", "").strip(),
            "country":      request.POST.get("country", "Uganda").strip(),
            "city":         request.POST.get("city", "").strip(),
            "plan":         request.POST.get("plan", "STARTER"),
            "message":      request.POST.get("message", "").strip(),
        }

        for field in ("company_name", "contact_name", "email", "phone"):
            if not form_data[field]:
                errors[field] = "This field is required."

        is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"

        if errors:
            if is_ajax:
                return JsonResponse({"ok": False, "errors": errors}, status=400)
            messages.error(request, "Please fill in all required fields.")
            return render(request, "tenants/register.html", {
                "form_data": form_data,
                "errors": errors,
                "page_links": PAGE_LINKS,
            })

        reg = CompanyRegistration.objects.create(**form_data)
        request.session["onboarding_registration_id"] = reg.pk
        request.session.pop("onboarding_company_id", None)

        # Send admin notification to platform operators (best-effort)
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

        # --- Launch provisioning in the background via Celery ---
        try:
            from tenants.models import Company, Domain
            from tenants.tasks import provision_tenant_task

            # NOTE: Postgres schema names use underscores (hyphens require
            # quoting), but hostnames must NOT contain underscores — Django's
            # get_host() validates against RFC 1034/1035 and will raise
            # DisallowedHost for any underscore in the Host header, regardless
            # of ALLOWED_HOSTS. Keep these two derived separately.
            slug = slugify(reg.company_name).lower()
            schema = slug.replace('-', '_')
            tenant_domain_root = getattr(django_settings, 'TENANT_PUBLIC_DOMAIN', 'abacash.loan')
            domain = f"{slug}.{tenant_domain_root}"
            admin_password = secrets.token_urlsafe(10)

            if Company.objects.filter(schema_name=schema).exists():
                raise ValueError(f"Schema '{schema}' already exists — pick a different company name or onboard manually.")

            company = Company.objects.create(schema_name=schema, name=reg.company_name, is_active=True, plan=reg.plan)
            request.session["onboarding_company_id"] = company.pk
            Domain.objects.create(domain=domain, tenant=company, is_primary=True)

            provision_tenant_task.delay(
                company.id, domain, reg.email,
                password=admin_password, plan=reg.plan,
                phone=reg.phone or '',
                address=(f"{reg.city}, {reg.country}" if (reg.city or reg.country) else ''),
                company_email=reg.email,
                notify=True,
            )

            # Record provisioning start in registration notes (do NOT store password)
            reg.notes = (reg.notes + f"\n[onboard-started] schema:{schema}, domain:{domain}, company_id:{company.id}, timestamp:{__import__('datetime').datetime.now().isoformat()}").strip()
            reg.save()

            logger.info(f"Onboarding task queued for registration {reg.id}: schema={schema}, domain={domain}, company_id={company.id}")

        except Exception as exc:
            # If background provisioning cannot be started, record the error and proceed
            error_msg = f"Failed to start onboarding: {exc}"
            reg.notes = (reg.notes + f"\n[onboard-error] {error_msg}").strip()
            reg.save()
            logger.error(error_msg, exc_info=True)

        if is_ajax:
            return JsonResponse({
                "ok": True,
                "message": "Your registration is received. We’ll show setup progress here and email you when access is ready.",
                "status_url": reverse("tenants:registration_status"),
            })

        messages.success(request, "Thank you! Your registration is being provisioned — you'll receive an email when ready.")
        return redirect("tenants:success")

    return render(request, "tenants/register.html", {
        "form_data": form_data,
        "errors": errors,
        "page_links": PAGE_LINKS,
    })


def success(request):
    return render(request, "tenants/success.html", {
        "page_links": PAGE_LINKS,
        "status_url": (
            reverse("tenants:registration_status")
            if request.session.get("onboarding_registration_id")
            else ""
        ),
    })


@require_GET
@cache_control(no_store=True)
def registration_status(request):
    registration_id = request.session.get("onboarding_registration_id")
    if not registration_id:
        return JsonResponse({"error": "No signup progress is available."}, status=404)

    try:
        registration = CompanyRegistration.objects.get(pk=registration_id)
    except CompanyRegistration.DoesNotExist:
        return JsonResponse({"error": "Signup progress is no longer available."}, status=404)

    company_id = request.session.get("onboarding_company_id")
    if not company_id:
        if "[onboard-error]" in registration.notes:
            return JsonResponse({
                "status": "FAILED",
                "step": "QUEUED",
                "failure_stage": "START",
                "waiting_seconds": 0,
            })
        return JsonResponse({
            "status": "PENDING",
            "step": "QUEUED",
            "waiting_seconds": max(0, int((timezone.now() - registration.submitted_at).total_seconds())),
        })

    try:
        company = Company.objects.get(pk=company_id)
    except Company.DoesNotExist:
        return JsonResponse({
            "status": "FAILED",
            "step": "QUEUED",
            "failure_stage": "START",
            "waiting_seconds": 0,
        })

    if (
        "[onboard-error]" in registration.notes
        and company.provisioning_status == Company.ProvisioningStatus.PENDING
        and company.provisioning_started_at is None
    ):
        return JsonResponse({
            "status": "FAILED",
            "step": "QUEUED",
            "failure_stage": "START",
            "waiting_seconds": 0,
        })

    return JsonResponse({
        "status": company.provisioning_status,
        "step": company.provisioning_step,
        "failure_stage": (
            "PROVISIONING"
            if company.provisioning_status == Company.ProvisioningStatus.FAILED
            else ""
        ),
        "waiting_seconds": (
            max(0, int((timezone.now() - registration.submitted_at).total_seconds()))
            if company.provisioning_status == Company.ProvisioningStatus.PENDING
            and company.provisioning_started_at is None
            else 0
        ),
    })


@cache_control(max_age=86400)
def robots_txt(request):
    """
    /robots.txt
    - Public domain (abacash.loan): allow all, point to sitemap.
    - Tenant subdomains (*.abacash.loan): block all crawlers — the app
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
    <loc>{site_url}/pricing/</loc>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>
  <url>
    <loc>{site_url}/features/</loc>
    <changefreq>monthly</changefreq>
    <priority>0.7</priority>
  </url>
  <url>
    <loc>{site_url}/support/</loc>
    <changefreq>monthly</changefreq>
    <priority>0.6</priority>
  </url>
  <url>
    <loc>{site_url}/public-admin/</loc>
    <changefreq>monthly</changefreq>
    <priority>0.5</priority>
  </url>
  <url>
    <loc>{site_url}/register/</loc>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>
</urlset>"""
    return HttpResponse(xml, content_type="application/xml")
