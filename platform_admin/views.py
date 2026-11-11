"""
Views for the public-schema platform admin console.

Deliberately reuses tenants.models.Company / Domain / CompanyRegistration
rather than defining its own — those models already live in the public
schema and are the source of truth for tenant/company records. This app
is a dedicated, easier-to-navigate front end on top of them (the existing
tenants:public_admin panel remains available for onboarding/role/reset
actions; this app focuses on dashboard + per-company detail).
"""
from datetime import date, timedelta
from decimal import Decimal
import ipaddress
import logging
import secrets
import smtplib

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import DatabaseError, transaction
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django_tenants.utils import schema_context

from tenants.models import Company, CompanyRegistration, Domain, Plan

from .decorators import require_public_admin

logger = logging.getLogger(__name__)


@require_public_admin
def dashboard(request):
    today = date.today()
    month_start = today.replace(day=1)

    companies = Company.objects.exclude(schema_name="public")
    total_companies     = companies.count()
    active_companies    = companies.filter(is_active=True).count()
    suspended_companies = total_companies - active_companies

    provisioning_counts = {
        row["provisioning_status"]: row["c"]
        for row in companies.values("provisioning_status").annotate(c=Count("id"))
    }
    in_progress_count = provisioning_counts.get("PENDING", 0) + provisioning_counts.get("RUNNING", 0)
    failed_provisioning = companies.filter(
        provisioning_status=Company.ProvisioningStatus.FAILED
    ).order_by("-provisioning_started_at")[:5]
    failed_count = provisioning_counts.get("FAILED", 0)

    plan_breakdown = list(
        companies.values("plan").annotate(count=Count("id")).order_by("-count")
    )

    new_this_month = companies.filter(created_on__gte=month_start).count()

    recent_companies = companies.order_by("-created_on")[:8]

    pending_leads = CompanyRegistration.objects.filter(
        status=CompanyRegistration.Status.PENDING
    ).order_by("-submitted_at")[:8]
    pending_lead_count = CompanyRegistration.objects.filter(
        status=CompanyRegistration.Status.PENDING
    ).count()

    return render(request, "platform_admin/dashboard.html", {
        "total_companies": total_companies,
        "active_companies": active_companies,
        "suspended_companies": suspended_companies,
        "in_progress_count": in_progress_count,
        "failed_count": failed_count,
        "failed_provisioning": failed_provisioning,
        "plan_breakdown": plan_breakdown,
        "new_this_month": new_this_month,
        "recent_companies": recent_companies,
        "pending_leads": pending_leads,
        "pending_lead_count": pending_lead_count,
    })


@require_public_admin
def company_list(request):
    companies = Company.objects.exclude(schema_name="public").order_by("name")

    q = request.GET.get("q", "").strip()
    if q:
        companies = companies.filter(Q(name__icontains=q) | Q(schema_name__icontains=q))

    status = request.GET.get("status", "")
    if status == "active":
        companies = companies.filter(is_active=True)
    elif status == "suspended":
        companies = companies.filter(is_active=False)

    plan = request.GET.get("plan", "")
    if plan:
        companies = companies.filter(plan=plan)

    paginator = Paginator(companies, 25)
    try:
        page_obj = paginator.page(request.GET.get("page", 1))
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    return render(request, "platform_admin/company_list.html", {
        "page_obj": page_obj,
        "paginator": paginator,
        "q": q,
        "status": status,
        "plan": plan,
        "plan_choices": Plan.choices,
    })


def _tenant_stats(company: Company) -> dict:
    """Best-effort per-tenant stats gathered via schema_context.

    Wrapped defensively: a tenant whose schema hasn't been migrated yet
    (or is mid-provisioning) shouldn't take down the detail page — we show
    what we can and note what we couldn't fetch.
    """
    stats = {
        "ok": False,
        "error": None,
        "staff_count": None,
        "branch_count": None,
        "client_count": None,
        "active_loan_count": None,
        "portfolio_outstanding": None,
        "collected_this_month": None,
    }
    if company.provisioning_status != Company.ProvisioningStatus.READY:
        stats["error"] = f"Provisioning status is {company.get_provisioning_status_display()}, not Ready yet."
        return stats
    try:
        with schema_context(company.schema_name):
            from accounts.models import User, Branch
            from clients.models import Client
            from loans.models import Loan
            from payments.models import Payment
            from django.db.models import Sum

            today = date.today()
            month_start = today.replace(day=1)

            stats["staff_count"]  = User.objects.filter(is_active=True).count()
            stats["branch_count"] = Branch.objects.filter(is_active=True).count()
            stats["client_count"] = Client.objects.filter(is_active=True).count()

            active_loans = Loan.objects.filter(status__in=["ACTIVE", "RESTRUCTURED"])
            stats["active_loan_count"] = active_loans.count()
            stats["portfolio_outstanding"] = active_loans.aggregate(
                t=Sum("outstanding_balance")
            )["t"] or Decimal("0")

            stats["collected_this_month"] = Payment.objects.cash_receipts().filter(
                payment_date__gte=month_start, status="ALLOCATED",
            ).aggregate(t=Sum("amount_received"))["t"] or Decimal("0")

            stats["ok"] = True
    except Exception as exc:
        stats["error"] = str(exc)
    return stats


@require_public_admin
def company_detail(request, schema_name):
    company = get_object_or_404(Company, schema_name=schema_name)
    domains = Domain.objects.filter(tenant=company)
    stats = _tenant_stats(company)

    return render(request, "platform_admin/company_detail.html", {
        "company": company,
        "domains": domains,
        "stats": stats,
        "plan_choices": Plan.choices,
    })


def _send_tenant_user_activation(user, company):
    domain = Domain.objects.filter(tenant=company).order_by("-is_primary").values_list(
        "domain", flat=True
    ).first()
    if not domain:
        domain = f"{company.schema_name}.{getattr(settings, 'TENANT_PUBLIC_DOMAIN', 'abacash.loan')}"

    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    reset_url = f"https://{domain}/accounts/reset/{uid}/{token}/"
    return send_mail(
        subject=f"Set up your Abacash account for {company.name}",
        message=(
            f"Hello {user.get_full_name()},\n\n"
            f"An administrator created or requested access for your account in {company.name}.\n"
            f"Use this secure link to set or reset your password: {reset_url}\n\n"
            "If you did not expect this message, contact your organization administrator."
        ),
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[user.email],
        fail_silently=False,
    )


def _record_platform_user_action(request, user, action, changes, remarks):
    from accounts.models import AuditLog

    ip_address = request.META.get("REMOTE_ADDR")
    try:
        ipaddress.ip_address(ip_address)
    except ValueError:
        ip_address = None
    AuditLog.objects.create(
        user=None,
        action=action,
        entity_type="User",
        entity_id=str(user.pk),
        entity_repr=str(user)[:500],
        changes=changes,
        ip_address=ip_address,
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
        remarks=f"Platform admin {request.platform_admin.username}: {remarks}",
    )


@require_public_admin
@require_http_methods(["GET", "POST"])
def user_list(request):
    """Show users across ready tenant schemas and process scoped admin actions."""
    from accounts.models import AuditLog, User

    companies = list(
        Company.objects.exclude(schema_name="public").order_by("name")
    )
    ready_companies = [
        company for company in companies
        if company.provisioning_status == Company.ProvisioningStatus.READY
    ]

    if request.method == "POST":
        action = request.POST.get("action", "")
        schema_name = request.POST.get("tenant_schema", "").strip()
        company = get_object_or_404(
            Company.objects.exclude(schema_name="public"),
            schema_name=schema_name,
            provisioning_status=Company.ProvisioningStatus.READY,
        )
        try:
            with schema_context(company.schema_name):
                if action == "create":
                    email = request.POST.get("email", "").strip()
                    role = request.POST.get("role", "").strip().upper()
                    try:
                        validate_email(email)
                    except ValidationError:
                        messages.error(request, "Enter a valid user email address.")
                        return redirect("platform_admin:user_list")
                    if role not in User.Role.values:
                        messages.error(request, "Select a valid tenant user role.")
                        return redirect("platform_admin:user_list")
                    if User.objects.filter(email__iexact=email).exists():
                        messages.error(request, f"A user with {email} already exists in {company.name}.")
                        return redirect("platform_admin:user_list")

                    with transaction.atomic():
                        user = User.objects.create_user(
                            email=email,
                            password=secrets.token_urlsafe(32),
                            role=role,
                            is_active=True,
                        )
                        _record_platform_user_action(
                            request,
                            user,
                            AuditLog.Action.CREATE,
                            {"email": email, "role": role, "is_active": True},
                            "Tenant user created and activation link requested",
                        )
                    try:
                        sent = _send_tenant_user_activation(user, company)
                    except (OSError, smtplib.SMTPException):
                        logger.exception("Could not send activation email for tenant user %s", user.pk)
                        messages.warning(
                            request,
                            f"User {email} was created, but the activation email could not be sent. "
                            "Use Send password reset on the user row to retry.",
                        )
                    else:
                        if sent:
                            messages.success(request, f"Created {email} in {company.name} and sent a secure activation link.")
                        else:
                            messages.warning(
                                request,
                                f"User {email} was created, but the email service did not accept the activation message. "
                                "Use Send password reset on the user row to retry.",
                            )

                elif action in {"update", "reset"}:
                    if action == "update":
                        with transaction.atomic():
                            active_ceo_ids = list(
                                User.objects.select_for_update().filter(
                                    role=User.Role.CEO, is_active=True
                                ).values_list("pk", flat=True)
                            )
                            user = get_object_or_404(
                                User.objects.select_for_update(),
                                pk=request.POST.get("user_id"),
                            )
                            role = request.POST.get("role", "").strip().upper()
                            is_active = request.POST.get("is_active") == "on"
                            if role not in User.Role.values:
                                messages.error(
                                    request,
                                    "Select a valid tenant user role.",
                                )
                                return redirect("platform_admin:user_list")
                            if user.pk in active_ceo_ids and (role != User.Role.CEO or not is_active):
                                another_active_ceo = any(pk != user.pk for pk in active_ceo_ids)
                                if not another_active_ceo:
                                    messages.error(
                                        request,
                                        f"{user.email} is the only active CEO in {company.name}. "
                                        "Promote another active user before changing this account.",
                                    )
                                    return redirect("platform_admin:user_list")
                            old_role = user.role
                            old_is_active = user.is_active
                            user.role = role
                            user.is_active = is_active
                            if role != User.Role.CEO:
                                user.is_superuser = False
                            user.save(update_fields=["role", "is_active", "is_superuser"])
                            _record_platform_user_action(
                                request,
                                user,
                                AuditLog.Action.UPDATE,
                                {
                                    "role": [old_role, role],
                                    "is_active": [old_is_active, is_active],
                                },
                                "Tenant user access updated",
                            )
                        messages.success(request, f"Updated access for {user.email} in {company.name}.")
                    else:
                        user = get_object_or_404(User, pk=request.POST.get("user_id"))
                        if _send_tenant_user_activation(user, company):
                            _record_platform_user_action(
                                request,
                                user,
                                AuditLog.Action.OTHER,
                                {},
                                "Password setup email sent",
                            )
                            messages.success(request, f"Sent password setup instructions to {user.email}.")
                        else:
                            messages.error(request, f"The email service did not accept a message for {user.email}.")
                else:
                    messages.error(request, "Unknown user management action.")
        except (OSError, smtplib.SMTPException):
            logger.exception("Could not send tenant user reset email")
            messages.error(request, "The email could not be sent. The account was not changed.")
        return redirect("platform_admin:user_list")

    q = request.GET.get("q", "").strip()
    role_filter = request.GET.get("role", "").strip().upper()
    status_filter = request.GET.get("status", "").strip()
    tenant_filter = request.GET.get("tenant", "").strip()

    filtered_companies = ready_companies
    if tenant_filter:
        filtered_companies = [
            company for company in ready_companies
            if company.schema_name == tenant_filter
        ]

    rows = []
    load_errors = []
    for company in filtered_companies:
        try:
            with schema_context(company.schema_name):
                tenant_users = User.objects.select_related("branch").all()
                if q:
                    tenant_users = tenant_users.filter(
                        Q(email__icontains=q)
                        | Q(username__icontains=q)
                        | Q(first_name__icontains=q)
                        | Q(last_name__icontains=q)
                    )
                if role_filter in User.Role.values:
                    tenant_users = tenant_users.filter(role=role_filter)
                if status_filter == "active":
                    tenant_users = tenant_users.filter(is_active=True)
                elif status_filter == "inactive":
                    tenant_users = tenant_users.filter(is_active=False)
                rows.extend((company, user) for user in tenant_users.order_by("email"))
        except DatabaseError:
            logger.exception("Could not load tenant users for schema %s", company.schema_name)
            load_errors.append(company.name)

    paginator = Paginator(rows, 25)
    page_obj = paginator.get_page(request.GET.get("page", 1))
    return render(request, "platform_admin/user_list.html", {
        "page_obj": page_obj,
        "q": q,
        "role_filter": role_filter,
        "status_filter": status_filter,
        "tenant_filter": tenant_filter,
        "company_choices": ready_companies,
        "role_choices": User.Role.choices,
        "load_errors": load_errors,
        "unavailable_tenant_count": len(companies) - len(ready_companies),
    })


@require_public_admin
@require_GET
def company_provisioning_status(request, schema_name):
    company = get_object_or_404(Company, schema_name=schema_name)
    return JsonResponse({
        "status": company.provisioning_status,
        "step": company.provisioning_step,
        "error": company.provisioning_error if company.provisioning_status == Company.ProvisioningStatus.FAILED else "",
    })


@require_public_admin
@require_POST
def company_toggle_active(request, schema_name):
    company = get_object_or_404(Company, schema_name=schema_name)
    if company.provisioning_status == Company.ProvisioningStatus.RUNNING:
        messages.warning(request, f"'{company.name}' is still provisioning — wait for it to finish first.")
        return redirect("platform_admin:company_detail", schema_name=schema_name)
    company.is_active = not company.is_active
    company.save(update_fields=["is_active"])
    status_label = "suspended" if not company.is_active else "activated"
    messages.success(request, f"'{company.name}' was {status_label}.")
    return redirect("platform_admin:company_detail", schema_name=schema_name)


@require_public_admin
@require_POST
def company_update_plan(request, schema_name):
    company = get_object_or_404(Company, schema_name=schema_name)
    plan = request.POST.get("plan", "").strip().upper()
    valid_plans = {choice[0] for choice in (Plan.choices)}
    if valid_plans and plan not in valid_plans:
        messages.error(request, f"'{plan}' is not a valid plan.")
    else:
        company.plan = plan
        company.save(update_fields=["plan"])
        messages.success(request, f"Updated '{company.name}' to the {plan} plan.")
    return redirect("platform_admin:company_detail", schema_name=schema_name)


@require_public_admin
@require_POST
def company_retry_provisioning(request, schema_name):
    """Re-run provisioning for a company stuck in FAILED (or PENDING, if the
    task never got picked up — e.g. the worker was down when it was queued).

    Safe to re-run: every seeding step uses get_or_create, and
    create_schema(check_if_exists=True) is a no-op if the schema already
    exists — only genuinely incomplete/failed steps actually do work.
    """
    company = get_object_or_404(Company, schema_name=schema_name)
    if company.provisioning_status == Company.ProvisioningStatus.READY:
        messages.info(request, f"'{company.name}' is already provisioned.")
        return redirect("platform_admin:company_detail", schema_name=schema_name)
    if company.provisioning_status == Company.ProvisioningStatus.RUNNING:
        messages.warning(request, f"'{company.name}' is currently provisioning — wait for it to finish or fail before retrying.")
        return redirect("platform_admin:company_detail", schema_name=schema_name)

    domain = request.POST.get("domain", "").strip()
    admin_email = request.POST.get("admin_email", "").strip()
    if not domain or not admin_email:
        domains = Domain.objects.filter(tenant=company, is_primary=True).first()
        domain = domain or (domains.domain if domains else "")
    if not domain or not admin_email:
        messages.error(request, "Need a domain and admin email to retry — provide them below.")
        return redirect("platform_admin:company_detail", schema_name=schema_name)

    from tenants.tasks import provision_tenant_task
    provision_tenant_task.delay(
        company.id, domain, admin_email,
        password=request.POST.get("password") or None,
        plan=company.plan,
        phone=request.POST.get("phone", ""),
        address=request.POST.get("address", ""),
        company_email=request.POST.get("company_email", "") or admin_email,
        notify=True,
    )
    messages.success(request, f"Retrying provisioning for '{company.name}'.")
    return redirect("platform_admin:company_detail", schema_name=schema_name)
