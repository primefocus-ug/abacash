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

from django.contrib import messages
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django_tenants.utils import schema_context

from tenants.models import Company, CompanyRegistration, Domain, Plan

from .decorators import require_public_admin


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
        notify=(request.POST.get("notify") == "on"),
    )
    messages.success(request, f"Retrying provisioning for '{company.name}'.")
    return redirect("platform_admin:company_detail", schema_name=schema_name)
