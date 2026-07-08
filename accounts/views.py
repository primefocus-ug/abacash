"""
accounts/views.py
=================
Authentication, role-based dashboard routing, and comprehensive admin panel for ABA Uganda.
"""

import json
from datetime import datetime
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import login, logout, get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password
from django.core.paginator import Paginator
from django.db.models import Q, Sum, Count
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.http import JsonResponse
from django.core.mail import send_mail
from django.conf import settings
from dateutil.relativedelta import relativedelta

from loans.models import Loan, LoanFee, LoanSchedule, LoanProduct, Guarantor
from payments.models import Payment
from clients.models import Client
from .models import CompanySettings, Branch, Expense, CapitalInjection, FeeType, Holiday, AuditLog, SystemParameter, User, TransactionCategory, ExpenseType, BankAccount, BankTransaction
from .audit import log_action
from .forms import EmailOrUsernameAuthenticationForm

User = get_user_model()


def _ceo_required(view_func):
    from functools import wraps
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_ceo:
            messages.error(request, "Only the CEO can access the admin panel.")
            return redirect("accounts:dashboard")
        return view_func(request, *args, **kwargs)
    return wrapper


def _manager_required(view_func):
    from functools import wraps
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if request.user.is_cashier:
            messages.error(request, "This feature is available to Managers and CEO only.")
            return redirect("accounts:dashboard")
        return view_func(request, *args, **kwargs)
    return wrapper


# ------------------------------------------------------------------ #
# Authentication                                                       #
# ------------------------------------------------------------------ #

def login_view(request):
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")

    form = EmailOrUsernameAuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.get_user())
        return redirect(request.GET.get("next", "accounts:dashboard"))

    return render(request, "accounts/login.html", {
        "form": form,
        "company": CompanySettings.get(),
    })


def contact_chatbot(request):
    """Public contact form on the login page — routes to email, sales, or WhatsApp."""
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        phone = (request.POST.get("phone") or "").strip()
        message = (request.POST.get("message") or "").strip()

        destination = (request.POST.get('destination') or 'whatsapp').lower()

        detail_parts = []
        if name:
            detail_parts.append(f"Name: {name}")
        if phone:
            detail_parts.append(f"Phone: {phone}")
        if message:
            detail_parts.append(f"Message: {message}")
        else:
            detail_parts.append("Message: Hello, I would like help.")

        text = " | ".join(detail_parts)

        if destination == 'email':
            settings_obj = CompanySettings.objects.first()
            to_addr = settings_obj.company_email if settings_obj and settings_obj.company_email else None
            subject = f"Website contact: {name or phone or 'Anonymous'}"
            body = text
            from_addr = getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@example.com')
            if to_addr:
                try:
                    send_mail(subject, body, from_addr, [to_addr])
                    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                        return JsonResponse({'status': 'ok', 'message': 'Email sent to support.'})
                    messages.success(request, 'Your message was sent to support by email.')
                except Exception:
                    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                        return JsonResponse({'status': 'error', 'message': 'Failed to send email.'})
                    messages.error(request, 'Failed to send email. Please try again later.')
            else:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'error', 'message': 'No support email configured.'})
                messages.error(request, 'Support email not configured.')
            return redirect('accounts:login')

        if destination == 'sales':
            settings_obj = CompanySettings.objects.first()
            to_addr = settings_obj.company_email if settings_obj and settings_obj.company_email else None
            subject = f"Sales lead: {name or phone or 'Anonymous'}"
            body = text
            from_addr = getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@example.com')
            if to_addr:
                try:
                    send_mail(subject, body, from_addr, [to_addr])
                    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                        return JsonResponse({'status': 'ok', 'message': 'Sales team notified internally.'})
                    messages.success(request, 'Sales team notified internally.')
                except Exception:
                    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                        return JsonResponse({'status': 'error', 'message': 'Failed to notify sales.'})
                    messages.error(request, 'Failed to notify sales. Please try again later.')
            else:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'error', 'message': 'No sales address configured.'})
                messages.error(request, 'Sales contact not configured.')
            return redirect('accounts:login')

        # default: whatsapp
        encoded_text = urlencode({"text": text})
        whatsapp_url = f"https://wa.me/256785230670?{encoded_text}"
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'ok', 'redirect_url': whatsapp_url, 'message': 'Opening WhatsApp chat...', 'ack_message': 'We will follow up shortly.'})
        return redirect(whatsapp_url)

    return redirect("accounts:login")


def logout_view(request):
    logout(request)
    return redirect("accounts:login")


# ------------------------------------------------------------------ #
# Dashboard                                                            #
# ------------------------------------------------------------------ #

@login_required
def dashboard(request):
    """Route to the correct dashboard based on user role."""
    user = request.user
    today = timezone.localdate()

    if user.is_ceo:
        return _ceo_dashboard(request, today)
    elif user.is_manager:
        return _manager_dashboard(request, today)
    else:
        return _cashier_dashboard(request, today)


def _cashier_dashboard(request, today):
    # Loans with payments due today
    due_today = LoanSchedule.objects.filter(
        due_date=today,
        status__in=["PENDING", "OVERDUE"],
        loan__status__in=["ACTIVE", "RESTRUCTURED"],
    ).select_related("loan__client").order_by("loan__client__last_name")[:20]

    # Recent payments recorded by this cashier
    recent_payments = Payment.objects.filter(
        recorded_by=request.user,
    ).select_related("loan__client").order_by("-created_at")[:10]

    # Today's collection total
    collected_today = Payment.objects.filter(
        recorded_by=request.user,
        payment_date=today,
        status="ALLOCATED",
    ).aggregate(total=Sum("amount_received"))["total"] or 0

    # My performance stats
    my_loans_count = Loan.objects.filter(applied_by=request.user).count()
    my_active_loans = Loan.objects.filter(applied_by=request.user, status__in=["ACTIVE", "RESTRUCTURED"]).count()

    context = {
        "due_today":             due_today,
        "recent_payments":       recent_payments,
        "collected_today_total": collected_today,
        "due_today_count":       due_today.count(),
        "my_loans_count":        my_loans_count,
        "my_active_loans":       my_active_loans,
    }
    return render(request, "accounts/dashboard_cashier.html", context)


def _manager_dashboard(request, today):
    # Pending approvals
    pending_loans = Loan.objects.filter(
        status="PENDING"
    ).select_related("client", "product", "applied_by").order_by("application_date")[:20]

    # Overdue loans
    overdue_schedules = LoanSchedule.objects.filter(
        due_date__lt=today,
        status__in=["PENDING", "OVERDUE"],
        loan__status__in=["ACTIVE", "RESTRUCTURED"],
    ).select_related("loan__client").order_by("due_date")[:20]

    # Portfolio metrics
    active_loans       = Loan.objects.filter(status__in=["ACTIVE", "RESTRUCTURED"])
    total_portfolio    = active_loans.aggregate(total=Sum("principal_amount"))["total"] or 0
    total_outstanding  = active_loans.aggregate(total=Sum("outstanding_balance"))["total"] or 0

    month_start = today.replace(day=1)
    collected_month = Payment.objects.filter(
        payment_date__gte=month_start,
        status="ALLOCATED",
    ).aggregate(total=Sum("amount_received"))["total"] or 0

    # Risk metrics
    par_30_count = Loan.objects.filter(
        status__in=["ACTIVE", "RESTRUCTURED"],
        schedule__due_date__lt=today,
        schedule__status__in=["PENDING", "OVERDUE"],
    ).distinct().count()

    staff_performance = []
    for staff in User.objects.filter(is_active=True).order_by("first_name", "last_name", "username"):
        if staff.is_ceo:
            continue
        applied_loans = Loan.objects.filter(applied_by=staff)
        collections_this_month = Payment.objects.filter(
            recorded_by=staff,
            payment_date__gte=month_start,
            status="ALLOCATED",
        ).aggregate(total=Sum("amount_received"))["total"] or Decimal("0")
        staff_performance.append({
            "user": staff,
            "applications_count": applied_loans.count(),
            "active_loans_count": applied_loans.filter(status__in=["ACTIVE", "RESTRUCTURED"]).count(),
            "collections_this_month": collections_this_month,
        })

    staff_performance.sort(
        key=lambda item: (-item["applications_count"], -item["collections_this_month"], item["user"].full_name)
    )

    context = {
        "pending_loans":        pending_loans,
        "overdue_schedules":    overdue_schedules,
        "total_portfolio":      total_portfolio,
        "total_outstanding":    total_outstanding,
        "collected_month":      collected_month,
        "overdue_count":        overdue_schedules.count(),
        "active_loan_count":    active_loans.count(),
        "pending_count":        pending_loans.count(),
        "par_30_count":         par_30_count,
        "staff_performance":   staff_performance[:8],
    }
    return render(request, "accounts/dashboard_manager.html", context)


def _ceo_dashboard(request, today):
    period = request.GET.get("period", "6")
    if period not in {"3", "6", "12"}:
        period = "6"
    period_months = int(period)

    month_start = today.replace(day=1)

    all_active = Loan.objects.filter(status__in=["ACTIVE", "RESTRUCTURED"])
    total_portfolio = all_active.aggregate(total=Sum("principal_amount"))["total"] or 0
    total_outstanding = all_active.aggregate(total=Sum("outstanding_balance"))["total"] or 0
    total_interest = all_active.aggregate(total=Sum("total_interest"))["total"] or 0

    collected_month = Payment.objects.filter(
        payment_date__gte=month_start, status="ALLOCATED"
    )
    collected_total = collected_month.aggregate(total=Sum("amount_received"))["total"] or 0
    interest_income = collected_month.aggregate(total=Sum("interest_paid"))["total"] or 0

    # PAR calculation
    overdue_30 = Loan.objects.filter(
        status__in=["ACTIVE", "RESTRUCTURED"],
        schedule__due_date__lt=today,
        schedule__status__in=["PENDING", "OVERDUE"],
    ).distinct()
    overdue_count = overdue_30.count()

    total_clients = Client.objects.filter(is_active=True).count()
    pending_count = Loan.objects.filter(status="PENDING").count()

    # Last 12 months collection for chart
    historical_data = []
    for i in range(11, -1, -1):
        d = today - relativedelta(months=i)
        ms = d.replace(day=1)
        me = ms + relativedelta(months=1)
        pmts = Payment.objects.filter(payment_date__gte=ms, payment_date__lt=me, status="ALLOCATED")
        historical_data.append({
            "label": ms.strftime("%b %Y"),
            "collected": float(pmts.aggregate(total=Sum("amount_received"))["total"] or 0),
            "interest": float(pmts.aggregate(total=Sum("interest_paid"))["total"] or 0),
        })
    monthly_data = historical_data[-period_months:]

    expense_history = []
    for i in range(11, -1, -1):
        d = today - relativedelta(months=i)
        ms = d.replace(day=1)
        me = ms + relativedelta(months=1)
        expenses = Expense.objects.filter(expense_date__gte=ms, expense_date__lt=me)
        expense_history.append({
            "label": ms.strftime("%b %Y"),
            "value": float(expenses.aggregate(total=Sum("amount"))["total"] or 0),
        })

    expense_start = (today - relativedelta(months=period_months - 1)).replace(day=1)
    expenses = Expense.objects.filter(expense_date__gte=expense_start, expense_date__lte=today)
    total_expenses = expenses.aggregate(total=Sum("amount"))["total"] or 0
    # Group by TransactionCategory name
    from collections import defaultdict
    cat_totals = defaultdict(float)
    for expense in expenses.select_related("category"):
        label = expense.category.name if expense.category else "Uncategorised"
        cat_totals[label] += float(expense.amount)
    expense_data = [{"label": k, "value": v} for k, v in cat_totals.items() if v > 0]
    if not expense_data:
        expense_data = [{"label": "No Expenses", "value": 1}]

    injections = CapitalInjection.objects.filter(injected_date__gte=expense_start, injected_date__lte=today)
    total_injections = injections.aggregate(total=Sum("amount"))["total"] or 0

    # Recent loans for loan book table
    recent_loans = Loan.objects.filter(
        status__in=["ACTIVE", "RESTRUCTURED", "COMPLETED"]
    ).select_related("client", "product").order_by("-disbursement_date")[:20]

    # Branch performance
    branches = Branch.objects.filter(is_active=True).annotate(
        loan_count=Count("loans", filter=Q(loans__status__in=["ACTIVE", "RESTRUCTURED"])),
        total_disbursed=Sum("loans__principal_amount", filter=Q(loans__disbursement_date__gte=month_start)),
    )

    # Risk distribution
    risk_distribution = {
        "LOW": Loan.objects.filter(status__in=["ACTIVE", "RESTRUCTURED"], risk_rating="LOW").count(),
        "NORMAL": Loan.objects.filter(status__in=["ACTIVE", "RESTRUCTURED"], risk_rating="NORMAL").count(),
        "WATCH": Loan.objects.filter(status__in=["ACTIVE", "RESTRUCTURED"], risk_rating="WATCH").count(),
        "SUBSTANDARD": Loan.objects.filter(status__in=["ACTIVE", "RESTRUCTURED"], risk_rating="SUBSTANDARD").count(),
        "DOUBTFUL": Loan.objects.filter(status__in=["ACTIVE", "RESTRUCTURED"], risk_rating="DOUBTFUL").count(),
        "LOSS": Loan.objects.filter(status__in=["ACTIVE", "RESTRUCTURED"], risk_rating="LOSS").count(),
    }

    context = {
        "total_portfolio": total_portfolio,
        "total_outstanding": total_outstanding,
        "total_interest": total_interest,
        "collected_month": collected_total,
        "interest_income": interest_income,
        "overdue_count": overdue_count,
        "total_clients": total_clients,
        "pending_count": pending_count,
        "monthly_data": monthly_data,
        "monthly_data_json": json.dumps(historical_data),
        "expense_history_json": json.dumps(expense_history),
        "recent_loans": recent_loans,
        "active_count": all_active.count(),
        "branches": branches,
        "risk_distribution": risk_distribution,
        "risk_data_json": json.dumps(risk_distribution),
        "expense_data": expense_data,
        "expense_data_json": json.dumps(expense_data),
        "total_expenses": total_expenses,
        "total_injections": total_injections,
        "period": int(period),
        "period_options": [3, 6, 12],
    }
    return render(request, "accounts/dashboard_ceo.html", context)

@_ceo_required

def admin_dashboard(request):
    context = {
        "total_users":    User.objects.count(),
        "active_users":   User.objects.filter(is_active=True).count(),
        "users_by_role":  {
            "Cashier": User.objects.filter(role="CASHIER").count(),
            "Manager": User.objects.filter(role="MANAGER").count(),
            "CEO":     User.objects.filter(role="CEO").count(),
        },
        "total_clients":  Client.objects.count(),
        "total_loans":    Loan.objects.count(),
        "total_guarantors": Guarantor.objects.filter(is_active=True).count(),
        "total_branches": Branch.objects.filter(is_active=True).count(),
        "settings":       CompanySettings.get(),
        "recent_users":   User.objects.order_by("-date_joined")[:5],
        "recent_loans":   Loan.objects.select_related("client").order_by("-created_at")[:5],
    }
    return render(request, "accounts/admin_dashboard.html", context)


@_ceo_required
def financial_overview(request):
    """CEO-only financial overview: disbursements, repayments, expenses, injections."""
    from django.db.models import Sum
    period = request.GET.get("period", "30")
    try:
        days = int(period)
    except Exception:
        days = 30

    today = timezone.localdate()
    start_date = today - relativedelta(days=days)

    disbursed = Loan.objects.filter(disbursement_date__gte=start_date, disbursement_date__lte=today).aggregate(total=Sum("principal_amount"))["total"] or 0
    repayments = Payment.objects.filter(payment_date__gte=start_date, payment_date__lte=today, status="ALLOCATED").aggregate(total=Sum("amount_received"))["total"] or 0
    expenses = Expense.objects.filter(expense_date__gte=start_date, expense_date__lte=today).aggregate(total=Sum("amount"))["total"] or 0
    injections = CapitalInjection.objects.filter(injected_date__gte=start_date, injected_date__lte=today).aggregate(total=Sum("amount"))["total"] or 0

    net_cash = (injections + repayments) - (disbursed + expenses)

    # Allow CSV export of ledger rows for the period
    if request.GET.get("export") == "csv":
        import csv
        from django.http import HttpResponse

        rows = []
        for l in Loan.objects.filter(disbursement_date__gte=start_date, disbursement_date__lte=today).order_by("disbursement_date"):
            rows.append((l.disbursement_date, "Disbursement", l.loan_number or "", float(l.principal_amount)))
        for p in Payment.objects.filter(payment_date__gte=start_date, payment_date__lte=today, status="ALLOCATED").order_by("payment_date"):
            rows.append((p.payment_date, "Repayment", p.loan.loan_number if p.loan else "", float(p.amount_received)))
        for e in Expense.objects.filter(expense_date__gte=start_date, expense_date__lte=today).order_by("expense_date"):
            rows.append((e.expense_date, "Expense", e.reference_number or "", float(e.amount)))
        for ci in CapitalInjection.objects.filter(injected_date__gte=start_date, injected_date__lte=today).order_by("injected_date"):
            rows.append((ci.injected_date, "Injection", ci.source, float(ci.amount)))

        rows.sort(key=lambda r: r[0])

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f"attachment; filename=financials_{start_date}_{today}.csv"
        writer = csv.writer(response)
        writer.writerow(["date", "type", "reference", "amount"])
        for r in rows:
            date_val = r[0].isoformat() if hasattr(r[0], "isoformat") else r[0]
            writer.writerow([date_val, r[1], r[2], f"{r[3]:.2f}"])
        return response

    context = {
        "disbursed": disbursed,
        "repayments": repayments,
        "expenses": expenses,
        "injections": injections,
        "net_cash": net_cash,
        "start_date": start_date,
        "end_date": today,
        "period": days,
    }
    return render(request, "accounts/admin_financials.html", context)


# ------------------------------------------------------------------ #
# User Management                                                      #
# ------------------------------------------------------------------ #

@_ceo_required
def user_list(request):
    qs = User.objects.select_related("branch").order_by("role", "first_name")
    q  = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q))
    role = request.GET.get("role", "")
    if role:
        qs = qs.filter(role=role)
    branch = request.GET.get("branch", "")
    if branch:
        qs = qs.filter(branch_id=branch)

    # Pagination
    paginator = Paginator(qs, 25)
    page = request.GET.get("page", 1)
    users = paginator.get_page(page)

    return render(request, "accounts/user_list.html", {
        "users":       users,
        "q":           q,
        "role_filter": role,
        "branch_filter": branch,
        "role_choices": User.Role.choices,
        "branches": Branch.objects.filter(is_active=True),
    })


@_ceo_required
def user_create(request):
    if request.method == "POST":
        d = request.POST
        try:
            if User.objects.filter(username=d["username"].strip()).exists():
                raise ValueError("Username already taken.")
            if User.objects.filter(email=d["email"].strip()).exists():
                raise ValueError("Email already registered.")
            if d["password1"] != d["password2"]:
                raise ValueError("Passwords do not match.")
            user = User.objects.create(
                username   = d["username"].strip(),
                first_name = d["first_name"].strip(),
                last_name  = d["last_name"].strip(),
                email      = d["email"].strip(),
                phone      = d.get("phone", "").strip(),
                role       = d["role"],
                branch_id  = d.get("branch") or None,
                commission_rate = d.get("commission_rate", "0.00"),
                is_active  = True,
                password   = make_password(d["password1"]),
            )
            log_action(request.user, AuditLog.Action.CREATE, user, request=request,
                       changes={"role": user.role, "email": user.email},
                       remarks=f"User {user.full_name} created")
            messages.success(request, f"User {user.full_name} created successfully.")
            return redirect("accounts:user_list")
        except Exception as e:
            messages.error(request, str(e))

    return render(request, "accounts/user_form.html", {
        "title":       "Add New User",
        "action":      "create",
        "role_choices": User.Role.choices,
        "branches": Branch.objects.filter(is_active=True),
    })


@_ceo_required
def user_edit(request, pk):
    staff = get_object_or_404(User, pk=pk)

    if request.method == "POST":
        d = request.POST
        try:
            staff.first_name = d["first_name"].strip()
            staff.last_name  = d["last_name"].strip()
            staff.email      = d["email"].strip()
            staff.phone      = d.get("phone", "").strip()
            staff.role       = d["role"]
            staff.branch_id  = d.get("branch") or None
            staff.commission_rate = d.get("commission_rate", "0.00")
            staff.is_active  = d.get("is_active") == "on"
            # Only change password if provided
            if d.get("password1"):
                if d["password1"] != d["password2"]:
                    raise ValueError("Passwords do not match.")
                staff.password = make_password(d["password1"])
            staff.save()
            log_action(request.user, AuditLog.Action.UPDATE, staff, request=request,
                       changes={"role": staff.role, "is_active": staff.is_active},
                       remarks=f"User {staff.full_name} updated")
            messages.success(request, f"User {staff.full_name} updated.")
            return redirect("accounts:user_list")
        except Exception as e:
            messages.error(request, str(e))

    return render(request, "accounts/user_form.html", {
        "title":       f"Edit — {staff.full_name}",
        "action":      "edit",
        "staff":       staff,
        "role_choices": User.Role.choices,
        "branches": Branch.objects.filter(is_active=True),
    })


@_ceo_required
def user_toggle_active(request, pk):
    staff = get_object_or_404(User, pk=pk)
    if staff == request.user:
        messages.error(request, "You cannot deactivate your own account.")
        return redirect("accounts:user_list")
    staff.is_active = not staff.is_active
    staff.save()
    state = "activated" if staff.is_active else "deactivated"
    messages.success(request, f"{staff.full_name} has been {state}.")
    return redirect("accounts:user_list")


# ------------------------------------------------------------------ #
# Branch Management                                                    #
# ------------------------------------------------------------------ #

@_ceo_required
def branch_list(request):
    qs = Branch.objects.annotate(
        staff_count=Count("staff_members", filter=Q(staff_members__is_active=True)),
        active_loans=Count("loans", filter=Q(loans__status__in=["ACTIVE", "RESTRUCTURED"])),
    ).order_by("name")

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q))

    return render(request, "accounts/branch_list.html", {
        "branches": qs,
        "q": q,
    })


@_ceo_required
def branch_create(request):
    if request.method == "POST":
        d = request.POST
        try:
            if Branch.objects.filter(code=d["code"].strip().upper()).exists():
                raise ValueError("Branch code already exists.")
            branch = Branch.objects.create(
                name=d["name"].strip(),
                code=d["code"].strip().upper(),
                address=d.get("address", "").strip(),
                phone=d.get("phone", "").strip(),
                email=d.get("email", "").strip(),
                manager_id=d.get("manager") or None,
                approval_limit=d.get("approval_limit", "10000000"),
                is_active=d.get("is_active") == "on",
            )
            messages.success(request, f"Branch '{branch.name}' created.")
            return redirect("accounts:branch_list")
        except Exception as e:
            messages.error(request, f"Could not create branch: {e}")

    return render(request, "accounts/branch_form.html", {
        "title": "Create Branch",
        "action": "create",
        "managers": User.objects.filter(is_active=True, role__in=["MANAGER", "CEO"]),
    })


@_ceo_required
def branch_edit(request, pk):
    branch = get_object_or_404(Branch, pk=pk)

    if request.method == "POST":
        d = request.POST
        try:
            branch.name = d["name"].strip()
            branch.code = d["code"].strip().upper()
            branch.address = d.get("address", "").strip()
            branch.phone = d.get("phone", "").strip()
            branch.email = d.get("email", "").strip()
            branch.manager_id = d.get("manager") or None
            branch.approval_limit = d.get("approval_limit", "10000000")
            branch.is_active = d.get("is_active") == "on"
            branch.save()
            messages.success(request, f"Branch '{branch.name}' updated.")
            return redirect("accounts:branch_list")
        except Exception as e:
            messages.error(request, f"Could not update branch: {e}")

    return render(request, "accounts/branch_form.html", {
        "title": f"Edit Branch — {branch.name}",
        "action": "edit",
        "branch": branch,
        "managers": User.objects.filter(is_active=True, role__in=["MANAGER", "CEO"]),
    })


# ------------------------------------------------------------------ #
# Fee Type Management                                                  #
# ------------------------------------------------------------------ #

@_ceo_required
def fee_type_list(request):
    qs = FeeType.objects.all().order_by("name")

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))

    applied_to = request.GET.get("applied_to", "")
    if applied_to:
        qs = qs.filter(applied_to=applied_to)

    return render(request, "accounts/fee_type_list.html", {
        "fee_types": qs,
        "q": q,
        "applied_to_filter": applied_to,
        "applied_to_choices": FeeType.AppliedTo.choices,
    })


@_ceo_required
def fee_type_create(request):
    if request.method == "POST":
        d = request.POST
        try:
            fee = FeeType.objects.create(
                name=d["name"].strip(),
                description=d.get("description", "").strip(),
                applied_to=d["applied_to"],
                calculation_method=d["calculation_method"],
                amount=d.get("amount", "0"),
                is_active=d.get("is_active") == "on",
                is_mandatory=d.get("is_mandatory") == "on",
                min_amount=d.get("min_amount", "0"),
                max_amount=d.get("max_amount", "0"),
            )
            messages.success(request, f"Fee type '{fee.name}' created.")
            return redirect("accounts:fee_type_list")
        except Exception as e:
            messages.error(request, f"Could not create fee type: {e}")

    return render(request, "accounts/fee_type_form.html", {
        "title": "Create Fee Type",
        "action": "create",
        "calculation_choices": FeeType.CalculationMethod.choices,
        "applied_to_choices": FeeType.AppliedTo.choices,
    })


@_ceo_required
def fee_type_edit(request, pk):
    fee_type = get_object_or_404(FeeType, pk=pk)

    if request.method == "POST":
        d = request.POST
        try:
            fee_type.name = d["name"].strip()
            fee_type.description = d.get("description", "").strip()
            fee_type.applied_to = d["applied_to"]
            fee_type.calculation_method = d["calculation_method"]
            fee_type.amount = d.get("amount", "0")
            fee_type.is_active = d.get("is_active") == "on"
            fee_type.is_mandatory = d.get("is_mandatory") == "on"
            fee_type.min_amount = d.get("min_amount", "0")
            fee_type.max_amount = d.get("max_amount", "0")
            fee_type.save()
            messages.success(request, f"Fee type '{fee_type.name}' updated.")
            return redirect("accounts:fee_type_list")
        except Exception as e:
            messages.error(request, f"Could not update fee type: {e}")

    return render(request, "accounts/fee_type_form.html", {
        "title": f"Edit Fee Type — {fee_type.name}",
        "action": "edit",
        "fee_type": fee_type,
        "calculation_choices": FeeType.CalculationMethod.choices,
        "applied_to_choices": FeeType.AppliedTo.choices,
    })


# ------------------------------------------------------------------ #
# Holiday Management                                                   #
# ------------------------------------------------------------------ #

@_ceo_required
def holiday_list(request):
    qs = Holiday.objects.all().order_by("-date")

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q))

    return render(request, "accounts/holiday_list.html", {
        "holidays": qs,
        "q": q,
    })


@_ceo_required
def holiday_create(request):
    if request.method == "POST":
        d = request.POST
        try:
            holiday = Holiday.objects.create(
                name=d["name"].strip(),
                date=d["date"],
                is_recurring=d.get("is_recurring") == "on",
                description=d.get("description", "").strip(),
                is_active=d.get("is_active") == "on",
            )
            messages.success(request, f"Holiday '{holiday.name}' created.")
            return redirect("accounts:holiday_list")
        except Exception as e:
            messages.error(request, f"Could not create holiday: {e}")

    return render(request, "accounts/holiday_form.html", {
        "title": "Create Holiday",
        "action": "create",
    })


@_ceo_required
def holiday_edit(request, pk):
    holiday = get_object_or_404(Holiday, pk=pk)

    if request.method == "POST":
        d = request.POST
        try:
            holiday.name = d["name"].strip()
            holiday.date = d["date"]
            holiday.is_recurring = d.get("is_recurring") == "on"
            holiday.description = d.get("description", "").strip()
            holiday.is_active = d.get("is_active") == "on"
            holiday.save()
            messages.success(request, f"Holiday '{holiday.name}' updated.")
            return redirect("accounts:holiday_list")
        except Exception as e:
            messages.error(request, f"Could not update holiday: {e}")

    return render(request, "accounts/holiday_form.html", {
        "title": f"Edit Holiday — {holiday.name}",
        "action": "edit",
        "holiday": holiday,
    })


# ------------------------------------------------------------------ #
# Company Settings                                                     #
# ------------------------------------------------------------------ #

@_ceo_required
def company_settings(request):
    settings_obj = CompanySettings.get()

    if request.method == "POST":
        d = request.POST
        try:
            # Company Information
            settings_obj.company_name           = d["company_name"].strip()
            settings_obj.company_address        = d.get("company_address", "").strip()
            settings_obj.company_phone          = d.get("company_phone", "").strip()
            settings_obj.company_email          = d.get("company_email", "").strip()
            settings_obj.company_website        = d.get("company_website", "").strip()
            settings_obj.company_registration   = d.get("company_registration", "").strip()
            settings_obj.tax_identification     = d.get("tax_identification", "").strip()
            settings_obj.currency_symbol        = d.get("currency_symbol", "UGX").strip() or "UGX"

            def _dec(key, default):
                v = d.get(key, "").strip()
                return v if v else default

            def _int(key, default):
                v = d.get(key, "").strip()
                return int(v) if v else default

            # Loan Business Rules
            settings_obj.manager_approval_limit = _dec("manager_approval_limit", "5000000")
            settings_obj.default_penalty_rate   = _dec("default_penalty_rate", "2")
            settings_obj.income_multiplier      = _dec("income_multiplier", "3")
            settings_obj.collateral_haircut     = _dec("collateral_haircut", "50")

            # Fee Settings
            settings_obj.default_processing_fee_percent  = _dec("default_processing_fee_percent", "1")
            settings_obj.processing_fee_method           = d.get("processing_fee_method", "PERCENTAGE")
            settings_obj.processing_fee_ranges           = d.get("processing_fee_ranges", "").strip()
            settings_obj.early_repayment_penalty_percent = _dec("early_repayment_penalty_percent", "0")
            settings_obj.loan_restructure_fee            = _dec("loan_restructure_fee", "10000")
            settings_obj.max_active_loans_per_client     = _int("max_active_loans_per_client", 3)

            # SMS Settings
            settings_obj.sms_reminders_enabled  = d.get("sms_reminders_enabled") == "on"
            settings_obj.reminder_days_before   = _int("reminder_days_before", 3)
            settings_obj.sms_sender_id          = d.get("sms_sender_id", "ABA Uganda").strip() or "ABA Uganda"

            # Due Date Settings
            settings_obj.adjust_due_dates_for_holidays = d.get("adjust_due_dates_for_holidays") == "on"
            settings_obj.grace_period_days      = _int("grace_period_days", 3)

            # Savings Settings
            settings_obj.savings_enabled             = d.get("savings_enabled") == "on"
            settings_obj.default_savings_interest_rate = _dec("default_savings_interest_rate", "3")
            settings_obj.minimum_savings_balance     = _dec("minimum_savings_balance", "10000")

            # Share Settings
            settings_obj.shares_enabled      = d.get("shares_enabled") == "on"
            settings_obj.share_price         = _dec("share_price", "50000")
            settings_obj.minimum_shares      = _int("minimum_shares", 10)
            settings_obj.maximum_shares      = _int("maximum_shares", 1000)
            settings_obj.dividend_frequency  = d.get("dividend_frequency", "ANNUALLY")

            # Risk Management
            settings_obj.max_portfolio_at_risk_percent = _dec("max_portfolio_at_risk_percent", "5")
            settings_obj.auto_write_off_days           = _int("auto_write_off_days", 180)

            settings_obj.updated_by             = request.user
            if request.FILES.get("company_logo"):
                settings_obj.company_logo = request.FILES["company_logo"]
            settings_obj.save()
            log_action(request.user, AuditLog.Action.UPDATE, settings_obj, request=request,
                       changes={"company_name": settings_obj.company_name},
                       remarks="Company settings updated")
            messages.success(request, "Company settings saved.")
            return redirect("accounts:company_settings")
        except Exception as e:
            messages.error(request, f"Error saving settings: {e}")

    return render(request, "accounts/company_settings.html", {"s": settings_obj})


# ------------------------------------------------------------------ #
# Guarantor Management                                                 #
# ------------------------------------------------------------------ #

@_manager_required
def guarantor_list(request):
    qs = Guarantor.objects.select_related("verified_by").order_by("-created_at")

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(first_name__icontains=q) |
            Q(last_name__icontains=q) |
            Q(phone_primary__icontains=q) |
            Q(nin__icontains=q)
        )

    gtype = request.GET.get("type", "")
    if gtype:
        qs = qs.filter(guarantor_type=gtype)

    # Pagination
    paginator = Paginator(qs, 25)
    page = request.GET.get("page", 1)
    guarantors = paginator.get_page(page)

    return render(request, "accounts/guarantor_list.html", {
        "guarantors": guarantors,
        "q": q,
        "type_filter": gtype,
        "type_choices": Guarantor.Type.choices,
    })


@_manager_required
def guarantor_detail(request, pk):
    guarantor = get_object_or_404(Guarantor, pk=pk)
    guarantees = guarantor.guarantees.select_related("loan__client").order_by("-created_at")

    return render(request, "accounts/guarantor_detail.html", {
        "guarantor": guarantor,
        "guarantees": guarantees,
    })


@_ceo_required
def guarantor_create(request):
    if request.method == "POST":
        d = request.POST
        try:
            guarantor = Guarantor.objects.create(
                first_name=d["first_name"].strip(),
                last_name=d["last_name"].strip(),
                other_names=d.get("other_names", "").strip(),
                company_name=d.get("company_name", "").strip(),
                registration_number=d.get("registration_number", "").strip(),
                guarantor_type=d.get("guarantor_type", "INDIVIDUAL"),
                nin=d.get("nin", "").strip().upper(),
                phone_primary=d["phone_primary"].strip(),
                phone_secondary=d.get("phone_secondary", "").strip(),
                email=d.get("email", "").strip(),
                physical_address=d["physical_address"].strip(),
                district=d.get("district", "Kampala").strip(),
                employer_name=d.get("employer_name", "").strip(),
                job_title=d.get("job_title", "").strip(),
                monthly_income=d.get("monthly_income", "0"),
                max_liability=d.get("max_liability", "0"),
                notes=d.get("notes", "").strip(),
            )
            messages.success(request, f"Guarantor '{guarantor.full_name}' created.")
            return redirect("accounts:guarantor_detail", pk=guarantor.pk)
        except Exception as e:
            messages.error(request, f"Could not create guarantor: {e}")

    return render(request, "accounts/guarantor_form.html", {
        "title": "Create Guarantor",
        "action": "create",
        "type_choices": Guarantor.Type.choices,
    })


@login_required
def guarantor_create_ajax(request):
    """AJAX endpoint to create a guarantor and return JSON {id, full_name}.
    Allowed for managers and CEOs only (not cashiers).
    """
    if request.user.is_cashier:
        return JsonResponse({"error": "Insufficient permissions."}, status=403)

    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=400)

    d = request.POST
    try:
        guarantor = Guarantor.objects.create(
            first_name=d.get("first_name", "").strip(),
            last_name=d.get("last_name", "").strip(),
            other_names=d.get("other_names", "").strip(),
            company_name=d.get("company_name", "").strip(),
            registration_number=d.get("registration_number", "").strip(),
            guarantor_type=d.get("guarantor_type", "INDIVIDUAL"),
            nin=d.get("nin", "").strip().upper(),
            phone_primary=d.get("phone_primary", "").strip(),
            phone_secondary=d.get("phone_secondary", "").strip(),
            email=d.get("email", "").strip(),
            physical_address=d.get("physical_address", "").strip(),
            district=d.get("district", "Kampala").strip(),
            employer_name=d.get("employer_name", "").strip(),
            job_title=d.get("job_title", "").strip(),
            monthly_income=d.get("monthly_income", "0") or "0",
            max_liability=d.get("max_liability", "0") or "0",
            notes=d.get("notes", "").strip(),
        )
        return JsonResponse({"id": guarantor.pk, "text": guarantor.full_name})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@_ceo_required
def guarantor_edit(request, pk):
    guarantor = get_object_or_404(Guarantor, pk=pk)

    if request.method == "POST":
        d = request.POST
        try:
            guarantor.first_name = d["first_name"].strip()
            guarantor.last_name = d["last_name"].strip()
            guarantor.other_names = d.get("other_names", "").strip()
            guarantor.company_name = d.get("company_name", "").strip()
            guarantor.registration_number = d.get("registration_number", "").strip()
            guarantor.guarantor_type = d.get("guarantor_type", "INDIVIDUAL")
            guarantor.nin = d.get("nin", "").strip().upper()
            guarantor.phone_primary = d["phone_primary"].strip()
            guarantor.phone_secondary = d.get("phone_secondary", "").strip()
            guarantor.email = d.get("email", "").strip()
            guarantor.physical_address = d["physical_address"].strip()
            guarantor.district = d.get("district", "Kampala").strip()
            guarantor.employer_name = d.get("employer_name", "").strip()
            guarantor.job_title = d.get("job_title", "").strip()
            guarantor.monthly_income = d.get("monthly_income", "0")
            guarantor.max_liability = d.get("max_liability", "0")
            guarantor.notes = d.get("notes", "").strip()

            # CEO can verify
            if request.user.is_ceo and d.get("is_verified"):
                guarantor.is_verified = True
                guarantor.verification_date = timezone.localdate()
                guarantor.verified_by = request.user

            guarantor.save()
            messages.success(request, f"Guarantor '{guarantor.full_name}' updated.")
            return redirect("accounts:guarantor_detail", pk=guarantor.pk)
        except Exception as e:
            messages.error(request, f"Could not update guarantor: {e}")

    return render(request, "accounts/guarantor_form.html", {
        "title": f"Edit Guarantor — {guarantor.full_name}",
        "action": "edit",
        "guarantor": guarantor,
        "type_choices": Guarantor.Type.choices,
    })


# ------------------------------------------------------------------ #
# Audit Log                                                            #
# ------------------------------------------------------------------ #

@_ceo_required
def audit_log(request):
    qs = AuditLog.objects.select_related("user").order_by("-created_at")

    entity_type = request.GET.get("entity_type", "").strip()
    if entity_type:
        qs = qs.filter(entity_type__icontains=entity_type)

    action = request.GET.get("action", "")
    if action:
        qs = qs.filter(action=action)

    user_filter = request.GET.get("user", "").strip()
    if user_filter:
        qs = qs.filter(
            Q(user__first_name__icontains=user_filter) |
            Q(user__last_name__icontains=user_filter) |
            Q(user__email__icontains=user_filter)
        )

    date_from = request.GET.get("date_from", "")
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)

    date_to = request.GET.get("date_to", "")
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)

    paginator = Paginator(qs, 50)
    logs = paginator.get_page(request.GET.get("page", 1))

    return render(request, "accounts/audit_log.html", {
        "logs": logs,
        "entity_type_filter": entity_type,
        "action_filter": action,
        "user_filter": user_filter,
        "date_from": date_from,
        "date_to": date_to,
        "action_choices": AuditLog.Action.choices,
        "total_count": qs.count(),
    })


# ------------------------------------------------------------------ #
# System Parameters                                                    #
# ------------------------------------------------------------------ #

@_ceo_required
def system_parameters(request):
    qs = SystemParameter.objects.order_by("key")

    if request.method == "POST":
        key = request.POST.get("key", "").strip()
        value = request.POST.get("value", "").strip()
        value_type = request.POST.get("value_type", "STRING")
        description = request.POST.get("description", "").strip()

        try:
            param, created = SystemParameter.objects.update_or_create(
                key=key,
                defaults={
                    "value": value,
                    "value_type": value_type,
                    "description": description,
                    "updated_by": request.user,
                }
            )
            messages.success(request, f"Parameter '{key}' {'created' if created else 'updated'}.")
            return redirect("accounts:system_parameters")
        except Exception as e:
            messages.error(request, f"Error saving parameter: {e}")

    return render(request, "accounts/system_parameters.html", {
        "parameters": qs,
    })


@_ceo_required
def system_parameter_delete(request, pk):
    param = get_object_or_404(SystemParameter, pk=pk)
    param.delete()
    messages.success(request, f"Parameter '{param.key}' deleted.")
    return redirect("accounts:system_parameters")


@_ceo_required
def expense_types_list(request):
    """Manage transaction categories and expense types on one page."""
    cat_error = et_error = None

    if request.method == "POST":
        action = request.POST.get("_action", "")
        if action == "save_category":
            name = request.POST.get("name", "").strip()
            if not name:
                cat_error = "Name is required."
            elif TransactionCategory.objects.filter(name__iexact=name).exists():
                cat_error = "Category already exists."
            else:
                TransactionCategory.objects.create(
                    name=name,
                    color=request.POST.get("color", "amber"),
                    description=request.POST.get("description", "").strip(),
                )
                messages.success(request, f"Category '{name}' created.")
                return redirect("accounts:expense_types_list")
        elif action == "save_expense_type":
            cat_id = request.POST.get("category_id", "")
            name   = request.POST.get("name", "").strip()
            if not cat_id or not name:
                et_error = "Category and name are required."
            else:
                try:
                    cat = TransactionCategory.objects.get(pk=cat_id)
                    if ExpenseType.objects.filter(category=cat, name__iexact=name).exists():
                        et_error = "Type already exists in this category."
                    else:
                        ExpenseType.objects.create(
                            category=cat, name=name,
                            description=request.POST.get("description", "").strip(),
                        )
                        messages.success(request, f"Expense type '{name}' created.")
                        return redirect("accounts:expense_types_list")
                except TransactionCategory.DoesNotExist:
                    et_error = "Category not found."
        elif action == "toggle_category":
            cat = get_object_or_404(TransactionCategory, pk=request.POST.get("pk"))
            cat.is_active = not cat.is_active
            cat.save()
            return redirect("accounts:expense_types_list")
        elif action == "toggle_expense_type":
            et = get_object_or_404(ExpenseType, pk=request.POST.get("pk"))
            et.is_active = not et.is_active
            et.save()
            return redirect("accounts:expense_types_list")

    categories = TransactionCategory.objects.prefetch_related("expense_types").order_by("name")
    return render(request, "accounts/expense_types_list.html", {
        "categories": categories,
        "color_choices": ["teal", "amber", "red", "green", "blue", "purple"],
        "cat_error": cat_error,
        "et_error": et_error,
    })


@_ceo_required
def transaction_category_create_ajax(request):
    """AJAX: create a TransactionCategory, return {id, name}."""
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=400)
    name = request.POST.get("name", "").strip()
    if not name:
        return JsonResponse({"error": "Name is required."}, status=400)
    if TransactionCategory.objects.filter(name__iexact=name).exists():
        return JsonResponse({"error": "Category already exists."}, status=400)
    cat = TransactionCategory.objects.create(
        name=name,
        description=request.POST.get("description", "").strip(),
        color=request.POST.get("color", "amber"),
    )
    return JsonResponse({"id": cat.pk, "name": cat.name})


@_ceo_required
def expense_type_create_ajax(request):
    """AJAX: create an ExpenseType under a category, return {id, name, category_id}."""
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=400)
    category_id = request.POST.get("category_id", "")
    name = request.POST.get("name", "").strip()
    if not category_id or not name:
        return JsonResponse({"error": "Category and name are required."}, status=400)
    try:
        category = TransactionCategory.objects.get(pk=category_id)
    except TransactionCategory.DoesNotExist:
        return JsonResponse({"error": "Category not found."}, status=400)
    if ExpenseType.objects.filter(category=category, name__iexact=name).exists():
        return JsonResponse({"error": "Expense type already exists in this category."}, status=400)
    et = ExpenseType.objects.create(
        category=category,
        name=name,
        description=request.POST.get("description", "").strip(),
    )
    return JsonResponse({"id": et.pk, "name": et.name, "category_id": category.pk})


@_ceo_required
def expense_types_for_category(request):
    """AJAX: return expense types for a given category_id."""
    category_id = request.GET.get("category_id", "")
    if not category_id:
        return JsonResponse({"types": []})
    types = list(
        ExpenseType.objects.filter(category_id=category_id, is_active=True)
        .values("id", "name")
    )
    return JsonResponse({"types": types})


# ------------------------------------------------------------------ #
# Expense Management                                                   #
# ------------------------------------------------------------------ #

@_ceo_required
def expense_list(request):
    form_data = {
        "category": "", "expense_type": "", "amount": "",
        "expense_date": timezone.localdate().isoformat(),
        "vendor": "", "payment_method": "CASH", "receipt_number": "", "description": "",
    }
    show_modal = False

    if request.method == "POST":
        d = request.POST
        for k in form_data:
            form_data[k] = d.get(k, form_data[k])
        try:
            from datetime import date as _date
            exp_date = _date.fromisoformat(form_data["expense_date"]) if form_data["expense_date"] else _date.today()
            amount_val = Decimal(str(form_data["amount"] or "0"))
            if amount_val <= 0:
                raise ValueError("Amount must be greater than zero.")
            Expense.objects.create(
                category_id=form_data["category"] or None,
                expense_type_id=form_data["expense_type"] or None,
                amount=amount_val,
                expense_date=exp_date,
                vendor=form_data["vendor"],
                payment_method=form_data["payment_method"],
                receipt_number=form_data["receipt_number"],
                description=form_data["description"],
                status="APPROVED",
                approved_by=request.user,
                approved_at=timezone.now(),
                created_by=request.user,
            )
            messages.success(request, "Expense recorded successfully.")
            return redirect("accounts:expense_list")
        except Exception as e:
            messages.error(request, f"Could not save expense: {e}")
            show_modal = True

    qs = Expense.objects.select_related("category", "expense_type", "created_by", "branch").order_by("-expense_date")

    category = request.GET.get("category", "")
    if category:
        qs = qs.filter(category_id=category)
    status_f = request.GET.get("status", "")
    if status_f:
        qs = qs.filter(status=status_f)
    date_from = request.GET.get("date_from", "")
    if date_from:
        qs = qs.filter(expense_date__gte=date_from)
    date_to = request.GET.get("date_to", "")
    if date_to:
        qs = qs.filter(expense_date__lte=date_to)

    paginator = Paginator(qs, 25)
    expenses = paginator.get_page(request.GET.get("page", 1))
    total_amount = qs.aggregate(total=Sum("amount"))["total"] or 0
    categories = TransactionCategory.objects.filter(is_active=True).prefetch_related("expense_types")

    return render(request, "accounts/expense_list.html", {
        "expenses": expenses,
        "category_filter": category,
        "status_filter": status_f,
        "date_from": date_from,
        "date_to": date_to,
        "total_amount": total_amount,
        "categories": categories,
        "form_data": form_data,
        "show_modal": show_modal,
        "color_choices": ["teal", "amber", "red", "green", "blue", "purple"],
        "status_choices": Expense.Status.choices,
        "payment_method_choices": Expense.PaymentMethod.choices,
    })


@_ceo_required
def expense_create(request):
    if request.method == "POST":
        d = request.POST
        try:
            amount_raw = (d.get("amount") or "").strip()
            if not amount_raw:
                raise ValueError("Amount is required.")
            amount_val = Decimal(amount_raw)
            if amount_val <= 0:
                raise ValueError("Amount must be greater than zero.")
            if not d.get("expense_date"):
                raise ValueError("Date is required.")
            from datetime import date as _date
            expense_date = _date.fromisoformat(d["expense_date"])
            expense = Expense.objects.create(
                category_id=d.get("category") or None,
                expense_type_id=d.get("expense_type") or None,
                amount=amount_val,
                expense_date=expense_date,
                vendor=d.get("vendor", "").strip(),
                payment_method=d.get("payment_method", "CASH"),
                receipt_number=d.get("receipt_number", "").strip(),
                description=d.get("description", "").strip(),
                status="APPROVED",
                approved_by=request.user,
                approved_at=timezone.now(),
                created_by=request.user,
            )
            messages.success(request, f"Expense {expense.reference_number} recorded.")
            return redirect("accounts:expense_list")
        except Exception as e:
            messages.error(request, f"Could not create expense: {e}")

    categories = TransactionCategory.objects.filter(is_active=True).prefetch_related("expense_types")
    return render(request, "accounts/expense_form.html", {
        "title": "Record Expense", "action": "create",
        "categories": categories,
        "payment_method_choices": Expense.PaymentMethod.choices,
    })


@_ceo_required
def expense_edit(request, pk):
    expense = get_object_or_404(Expense, pk=pk)

    if request.method == "POST":
        d = request.POST
        try:
            amount_raw = (d.get("amount") or "").strip()
            if not amount_raw:
                raise ValueError("Amount is required.")
            amount_val = Decimal(amount_raw)
            if amount_val <= 0:
                raise ValueError("Amount must be greater than zero.")
            if not d.get("expense_date"):
                raise ValueError("Date is required.")
            from datetime import date as _date
            expense.category_id = d.get("category") or None
            expense.expense_type_id = d.get("expense_type") or None
            expense.amount = amount_val
            expense.expense_date = _date.fromisoformat(d["expense_date"])
            expense.vendor = d.get("vendor", "").strip()
            expense.payment_method = d.get("payment_method", "CASH")
            expense.receipt_number = d.get("receipt_number", "").strip()
            expense.description = d.get("description", "").strip()
            expense.save()
            messages.success(request, "Expense updated.")
            return redirect("accounts:expense_list")
        except Exception as e:
            messages.error(request, f"Could not update expense: {e}")

    categories = TransactionCategory.objects.filter(is_active=True).prefetch_related("expense_types")
    return render(request, "accounts/expense_form.html", {
        "title": "Edit Expense", "action": "edit",
        "expense": expense,
        "categories": categories,
        "payment_method_choices": Expense.PaymentMethod.choices,
    })


@_ceo_required
def expense_delete(request, pk):
    expense = get_object_or_404(Expense, pk=pk)
    if request.method == "POST":
        expense.delete()
        messages.success(request, "Expense deleted.")
        return redirect("accounts:expense_list")
    return render(request, "accounts/expense_confirm_delete.html", {"expense": expense})


# ------------------------------------------------------------------ #
# Capital Injection Management                                        #
# ------------------------------------------------------------------ #

@_ceo_required
def capital_injection_list(request):
    qs = CapitalInjection.objects.select_related("created_by").order_by("-injected_date")

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(source__icontains=q) | Q(investor__icontains=q))

    date_from = request.GET.get("date_from", "")
    if date_from:
        qs = qs.filter(injected_date__gte=date_from)

    date_to = request.GET.get("date_to", "")
    if date_to:
        qs = qs.filter(injected_date__lte=date_to)

    # Pagination
    paginator = Paginator(qs, 25)
    page = request.GET.get("page", 1)
    injections = paginator.get_page(page)

    total_amount = sum(i.amount for i in qs)

    return render(request, "accounts/capital_injection_list.html", {
        "injections": injections,
        "q": q,
        "date_from": date_from,
        "date_to": date_to,
        "total_amount": total_amount,
    })


@_ceo_required
def capital_injection_create(request):
    if request.method == "POST":
        d = request.POST
        try:
            amount_value = d.get("amount", "")
            injection = CapitalInjection.objects.create(
                source=d["source"].strip(),
                amount=amount_value,
                injected_date=d["injected_date"],
                investor=d.get("investor", "").strip(),
                notes=d.get("notes", "").strip(),
                created_by=request.user,
            )
            amount_display = f"{injection.amount:,.2f}".rstrip("0").rstrip(".") if hasattr(injection.amount, "quantize") else str(injection.amount)
            messages.success(request, f"Capital injection recorded: UGX {amount_display} from {injection.source}")
            return redirect("accounts:capital_injection_list")
        except Exception as e:
            messages.error(request, f"Could not create capital injection: {e}")

    return render(request, "accounts/capital_injection_form.html", {
        "title": "Record Capital Injection",
        "action": "create",
    })


@_ceo_required
def capital_injection_edit(request, pk):
    injection = get_object_or_404(CapitalInjection, pk=pk)

    if request.method == "POST":
        d = request.POST
        try:
            injection.source = d["source"].strip()
            injection.amount = d["amount"]
            injection.injected_date = d["injected_date"]
            injection.investor = d.get("investor", "").strip()
            injection.notes = d.get("notes", "").strip()
            injection.save()
            messages.success(request, f"Capital injection updated.")
            return redirect("accounts:capital_injection_list")
        except Exception as e:
            messages.error(request, f"Could not update capital injection: {e}")

    return render(request, "accounts/capital_injection_form.html", {
        "title": f"Edit Capital Injection — {injection.source}",
        "action": "edit",
        "injection": injection,
    })


@_ceo_required
def capital_injection_delete(request, pk):
    injection = get_object_or_404(CapitalInjection, pk=pk)
    if request.method == "POST":
        injection.delete()
        messages.success(request, "Capital injection deleted.")
        return redirect("accounts:capital_injection_list")
    return render(request, "accounts/capital_injection_confirm_delete.html", {"injection": injection})


# ------------------------------------------------------------------ #
# Bank Account Management                                              #
# ------------------------------------------------------------------ #

@_ceo_required
def bank_account_list(request):
    accounts = BankAccount.objects.all().order_by("bank_name", "account_name")
    total_balance = accounts.filter(is_active=True).aggregate(total=Sum("current_balance"))["total"] or 0
    return render(request, "accounts/bank_account_list.html", {
        "bank_accounts": accounts,
        "total_balance": total_balance,
    })


@_ceo_required
def bank_account_create(request):
    if request.method == "POST":
        d = request.POST
        try:
            acc = BankAccount.objects.create(
                account_name=d["account_name"].strip(),
                account_number=d["account_number"].strip(),
                bank_name=d["bank_name"].strip(),
                branch_name=d.get("branch_name", "").strip(),
                account_type=d.get("account_type", "CURRENT"),
                currency=d.get("currency", "UGX").strip() or "UGX",
                opening_balance=d.get("opening_balance", "0") or "0",
                current_balance=d.get("opening_balance", "0") or "0",
                notes=d.get("notes", "").strip(),
                is_active=d.get("is_active") == "on",
            )
            messages.success(request, f"Bank account '{acc.account_name}' added.")
            return redirect("accounts:bank_account_list")
        except Exception as e:
            messages.error(request, f"Could not create bank account: {e}")

    return render(request, "accounts/bank_account_form.html", {
        "title": "Add Bank Account", "action": "create",
        "account_type_choices": BankAccount.AccountType.choices,
    })


@_ceo_required
def bank_account_edit(request, pk):
    acc = get_object_or_404(BankAccount, pk=pk)
    if request.method == "POST":
        d = request.POST
        try:
            acc.account_name  = d["account_name"].strip()
            acc.account_number = d["account_number"].strip()
            acc.bank_name     = d["bank_name"].strip()
            acc.branch_name   = d.get("branch_name", "").strip()
            acc.account_type  = d.get("account_type", "CURRENT")
            acc.currency      = d.get("currency", "UGX").strip() or "UGX"
            acc.current_balance = d.get("current_balance", acc.current_balance)
            acc.notes         = d.get("notes", "").strip()
            acc.is_active     = d.get("is_active") == "on"
            acc.save()
            messages.success(request, f"Bank account '{acc.account_name}' updated.")
            return redirect("accounts:bank_account_list")
        except Exception as e:
            messages.error(request, f"Could not update bank account: {e}")

    return render(request, "accounts/bank_account_form.html", {
        "title": f"Edit — {acc.account_name}", "action": "edit",
        "account": acc,
        "account_type_choices": BankAccount.AccountType.choices,
    })


@_ceo_required
def bank_transaction_list(request):
    qs = BankTransaction.objects.select_related("branch", "bank_account", "created_by").order_by("-transaction_date")
    branch_filter = request.GET.get("branch", "")
    type_filter = request.GET.get("type", "")
    q = request.GET.get("q", "").strip()
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")

    if branch_filter:
        qs = qs.filter(branch_id=branch_filter)
    if type_filter:
        qs = qs.filter(transaction_type=type_filter)
    if date_from:
        qs = qs.filter(transaction_date__date__gte=date_from)
    if date_to:
        qs = qs.filter(transaction_date__date__lte=date_to)
    if q:
        qs = qs.filter(
            Q(category__icontains=q)
            | Q(reference_number__icontains=q)
            | Q(bank_account__account_name__icontains=q)
            | Q(bank_account__bank_name__icontains=q)
        )

    paginator = Paginator(qs, 25)
    transactions = paginator.get_page(request.GET.get("page", 1))
    total_amount = qs.aggregate(total=Sum("amount"))["total"] or 0
    branches = Branch.objects.filter(is_active=True).order_by("name")
    query_string = urlencode({k: v for k, v in request.GET.items() if k != "page" and v})

    return render(request, "accounts/bank_transaction_list.html", {
        "transactions": transactions,
        "branches": branches,
        "branch_filter": branch_filter,
        "type_filter": type_filter,
        "date_from": date_from,
        "date_to": date_to,
        "q": q,
        "total_amount": total_amount,
        "transaction_type_choices": BankTransaction.TransactionType.choices,
        "query_string": query_string,
    })


@_ceo_required
def bank_transaction_create(request):
    transaction = None
    if request.method == "POST":
        d = request.POST
        try:
            branch_id = d.get("branch") or None
            bank_account = get_object_or_404(BankAccount, pk=d["bank_account"])
            transaction_type = d.get("transaction_type", BankTransaction.TransactionType.CREDIT)
            amount = Decimal(d["amount"])
            transaction_date_value = d.get("transaction_date", "")
            if transaction_date_value:
                transaction_date = datetime.fromisoformat(transaction_date_value)
                if transaction_date.tzinfo is None:
                    transaction_date = timezone.make_aware(transaction_date)
            else:
                transaction_date = timezone.now()

            transaction = BankTransaction.objects.create(
                branch_id=branch_id,
                bank_account=bank_account,
                category=d.get("category", "").strip(),
                transaction_type=transaction_type,
                amount=amount,
                transaction_date=transaction_date,
                reference_number=d.get("reference_number", "").strip(),
                notes=d.get("notes", "").strip(),
                created_by=request.user,
            )

            if transaction_type == BankTransaction.TransactionType.CREDIT:
                bank_account.current_balance += amount
            else:
                bank_account.current_balance -= amount
            bank_account.save()

            messages.success(request, "Bank transaction recorded successfully.")
            return redirect("accounts:bank_transaction_list")
        except Exception as e:
            messages.error(request, f"Could not save bank transaction: {e}")

    return render(request, "accounts/bank_transaction_form.html", {
        "title": "Add Bank Transaction",
        "action": "create",
        "branches": Branch.objects.filter(is_active=True).order_by("name"),
        "bank_accounts": BankAccount.objects.filter(is_active=True).order_by("bank_name", "account_name"),
        "transaction_type_choices": BankTransaction.TransactionType.choices,
        "transaction": transaction,
        "now": timezone.localtime(),
    })


@_ceo_required
def bank_transaction_edit(request, pk):
    transaction = get_object_or_404(BankTransaction, pk=pk)
    if request.method == "POST":
        d = request.POST
        try:
            old_account = transaction.bank_account
            old_type = transaction.transaction_type
            old_amount = transaction.amount

            transaction.branch_id = d.get("branch") or None
            transaction.bank_account = get_object_or_404(BankAccount, pk=d["bank_account"])
            transaction.category = d.get("category", "").strip()
            transaction.transaction_type = d.get("transaction_type", BankTransaction.TransactionType.CREDIT)
            transaction.amount = Decimal(d["amount"])
            transaction_date_value = d.get("transaction_date", "")
            if transaction_date_value:
                updated_date = datetime.fromisoformat(transaction_date_value)
                if updated_date.tzinfo is None:
                    updated_date = timezone.make_aware(updated_date)
                transaction.transaction_date = updated_date
            transaction.reference_number = d.get("reference_number", "").strip()
            transaction.notes = d.get("notes", "").strip()
            transaction.save()

            if old_type == BankTransaction.TransactionType.CREDIT:
                old_account.current_balance -= old_amount
            else:
                old_account.current_balance += old_amount
            old_account.save()

            if transaction.transaction_type == BankTransaction.TransactionType.CREDIT:
                transaction.bank_account.current_balance += transaction.amount
            else:
                transaction.bank_account.current_balance -= transaction.amount
            transaction.bank_account.save()

            messages.success(request, "Bank transaction updated successfully.")
            return redirect("accounts:bank_transaction_list")
        except Exception as e:
            messages.error(request, f"Could not update bank transaction: {e}")

    return render(request, "accounts/bank_transaction_form.html", {
        "title": f"Edit Bank Transaction — {transaction.reference_number or transaction.pk}",
        "action": "edit",
        "branches": Branch.objects.filter(is_active=True).order_by("name"),
        "bank_accounts": BankAccount.objects.filter(is_active=True).order_by("bank_name", "account_name"),
        "transaction_type_choices": BankTransaction.TransactionType.choices,
        "transaction": transaction,
        "now": timezone.localtime(),
    })