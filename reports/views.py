"""reports/views.py — all management reports for ABA Uganda."""

import logging
from datetime import date, datetime
from decimal import Decimal
from collections import defaultdict

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.contrib import messages
from django.db.models import Sum
from django.contrib.auth import get_user_model

from accounts.models import Branch, Expense
from loans.models import Loan, LoanSchedule, LoanProduct
from payments.models import Payment
from clients.models import Client

logger = logging.getLogger("reports")



def _require_manager(view_fn):
    from functools import wraps
    @wraps(view_fn)
    @login_required
    def wrapper(request, *args, **kwargs):
        if request.user.is_cashier:
            messages.error(request, "Reports are available to Managers and CEO only.")
            return redirect("accounts:dashboard")
        return view_fn(request, *args, **kwargs)
    return wrapper


@_require_manager
def report_index(request):
    return render(request, "reports/index.html")


@_require_manager
def loan_book(request):
    today      = date.today()
    date_from  = request.GET.get("date_from", "")
    date_to    = request.GET.get("date_to",   "")
    product_id = request.GET.get("product",   "")

    from loans.models import LoanProduct
    products = LoanProduct.objects.filter(is_active=True)

    qs = Loan.objects.filter(
        status__in=["ACTIVE", "COMPLETED", "DEFAULTED"]
    ).select_related("client", "product").order_by("-disbursement_date")

    if date_from:
        qs = qs.filter(disbursement_date__gte=date_from)
    if date_to:
        qs = qs.filter(disbursement_date__lte=date_to)
    if product_id:
        qs = qs.filter(product_id=product_id)

    total_principal   = sum(l.principal_amount    for l in qs)
    total_outstanding = sum(l.outstanding_balance for l in qs)
    total_paid        = sum(l.total_paid          for l in qs)

    return render(request, "reports/loan_book.html", {
        "loans":             qs,
        "total_principal":   total_principal,
        "total_outstanding": total_outstanding,
        "total_paid":        total_paid,
        "products":          products,
        "date_from":         date_from,
        "date_to":           date_to,
        "product_id":        product_id,
    })


@_require_manager
def loan_book_download(request):
    """Download loan book as PDF."""
    from datetime import datetime
    from django.http import HttpResponse
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib import colors
    from io import BytesIO
    from loans.models import Loan, LoanProduct

    today      = date.today()
    date_from  = request.GET.get("date_from", "")
    date_to    = request.GET.get("date_to",   "")
    product_id = request.GET.get("product",   "")

    qs = Loan.objects.filter(
        status__in=["ACTIVE", "COMPLETED", "DEFAULTED"]
    ).select_related("client", "product").order_by("-disbursement_date")

    if date_from:
        qs = qs.filter(disbursement_date__gte=date_from)
    if date_to:
        qs = qs.filter(disbursement_date__lte=date_to)
    if product_id:
        qs = qs.filter(product_id=product_id)

    styles = getSampleStyleSheet()
    header_style = ParagraphStyle("Header", parent=styles["Heading1"], fontSize=14, alignment=TA_CENTER, spaceAfter=8)
    normal = ParagraphStyle("Normal", parent=styles["Normal"], fontSize=8, spaceAfter=2)

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=12*mm, leftMargin=12*mm, topMargin=15*mm, bottomMargin=15*mm)
    story = []

    story.append(Paragraph("Loan Book Report", header_style))
    filters_text = "All Loans"
    if date_from or date_to:
        filters_text = f"{date_from or 'Start'} to {date_to or 'End'}"
    story.append(Paragraph(f"Period: {filters_text} | Generated: {datetime.now():%d %b %Y %H:%M}", normal))
    story.append(Spacer(1, 6))

    table_data = [[
        Paragraph("<b>Loan #</b>", normal),
        Paragraph("<b>Client</b>", normal),
        Paragraph("<b>Product</b>", normal),
        Paragraph("<b>Principal</b>", normal),
        Paragraph("<b>Outstanding</b>", normal),
        Paragraph("<b>Paid</b>", normal),
        Paragraph("<b>Status</b>", normal),
    ]]

    for loan in qs[:100]:
        table_data.append([
            Paragraph(loan.loan_number, normal),
            Paragraph(loan.client.full_name, normal),
            Paragraph(loan.product.name, normal),
            Paragraph(f"UGX {loan.principal_amount:,.0f}", normal),
            Paragraph(f"UGX {loan.outstanding_balance:,.0f}", normal),
            Paragraph(f"UGX {loan.total_paid:,.0f}", normal),
            Paragraph(loan.get_status_display(), normal),
        ])

    table = Table(table_data, colWidths=[18*mm, 28*mm, 20*mm, 20*mm, 20*mm, 18*mm, 16*mm])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E5E7EB")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (1, -1), "LEFT"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
    ]))
    story.append(table)

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="LoanBook-{today}.pdf"'
    return response


@_require_manager
def collections_report(request):
    today      = date.today()
    date_from  = request.GET.get("date_from", today.replace(day=1).isoformat())
    date_to    = request.GET.get("date_to",   today.isoformat())

    payments = Payment.objects.filter(
        payment_date__gte=date_from,
        payment_date__lte=date_to,
        status="ALLOCATED",
    ).select_related("loan__client", "recorded_by").order_by("recorded_by__last_name", "-payment_date")

    by_cashier = defaultdict(list)
    for p in payments:
        by_cashier[p.recorded_by].append(p)

    cashier_totals = [
        {
            "user":     user,
            "payments": pmts,
            "total":    sum(p.amount_received for p in pmts),
            "count":    len(pmts),
        }
        for user, pmts in by_cashier.items()
    ]

    grand_total = sum(r["total"] for r in cashier_totals)

    return render(request, "reports/collections.html", {
        "cashier_totals": cashier_totals,
        "grand_total":    grand_total,
        "date_from":      date_from,
        "date_to":        date_to,
        "payment_count":  payments.count(),
    })


@_require_manager
def overdue_report(request):
    today = date.today()

    overdue = LoanSchedule.objects.filter(
        due_date__lt=today,
        status__in=["PENDING", "PARTIAL"],
        loan__status="ACTIVE",
    ).select_related("loan__client", "loan__product").order_by("due_date")

    # Annotate days overdue
    rows = []
    for entry in overdue:
        days = (today - entry.due_date).days
        rows.append({
            "entry":         entry,
            "days_overdue":  days,
            "overdue_amount": entry.total_payment - entry.amount_paid,
        })

    rows.sort(key=lambda r: r["days_overdue"], reverse=True)
    total_overdue = sum(r["overdue_amount"] for r in rows)

    return render(request, "reports/overdue.html", {
        "rows":          rows,
        "total_overdue": total_overdue,
        "today":         today,
    })


@_require_manager
def income_statement(request):
    today      = date.today()
    month_str  = request.GET.get("month", today.strftime("%Y-%m"))

    try:
        year, month = int(month_str[:4]), int(month_str[5:7])
    except (ValueError, IndexError):
        year, month = today.year, today.month

    from dateutil.relativedelta import relativedelta as rd
    period_start = date(year, month, 1)
    period_end   = period_start + rd(months=1)

    payments = Payment.objects.filter(
        payment_date__gte=period_start,
        payment_date__lt=period_end,
        status="ALLOCATED",
    )

    total_received  = sum(p.amount_received for p in payments)
    total_principal = sum(p.principal_paid  for p in payments)
    total_interest  = sum(p.interest_paid   for p in payments)
    total_penalties = sum(p.penalty_paid    for p in payments)

    # Loans disbursed this month
    disbursed = Loan.objects.filter(
        disbursement_date__gte=period_start,
        disbursement_date__lt=period_end,
    )
    total_disbursed = sum(l.principal_amount for l in disbursed)

    return render(request, "reports/income_statement.html", {
        "month_str":       month_str,
        "period_start":    period_start,
        "period_end":      period_end - rd(days=1),
        "total_received":  total_received,
        "total_principal": total_principal,
        "total_interest":  total_interest,
        "total_penalties": total_penalties,
        "total_disbursed": total_disbursed,
        "loan_count":      disbursed.count(),
        "payment_count":   payments.count(),
    })


@_require_manager
def cash_flow_report(request):
    today      = date.today()
    date_from  = request.GET.get("date_from", today.replace(day=1).isoformat())
    date_to    = request.GET.get("date_to", today.isoformat())

    payments = list(Payment.objects.filter(
        payment_date__gte=date_from,
        payment_date__lte=date_to,
        status="ALLOCATED",
    ).select_related("loan__client", "recorded_by").order_by("payment_date"))

    disbursements = list(Loan.objects.filter(
        disbursement_date__gte=date_from,
        disbursement_date__lte=date_to,
        status__in=[Loan.Status.ACTIVE, Loan.Status.COMPLETED],
    ).select_related("client", "product").order_by("disbursement_date"))

    expenses = list(Expense.objects.filter(
        expense_date__gte=date_from,
        expense_date__lte=date_to,
        status="APPROVED",
    ).select_related("category", "expense_type").order_by("expense_date"))

    total_cash_in = sum(p.amount_received for p in payments)
    total_principal = sum(p.principal_paid for p in payments)
    total_interest = sum(p.interest_paid for p in payments)
    total_penalties = sum(p.penalty_paid for p in payments)
    total_cash_out = sum(l.cash_disbursed for l in disbursements)
    total_processing_fees = sum(l.effective_processing_fee for l in disbursements)
    total_cash_in += total_processing_fees
    total_expenses = sum(e.amount for e in expenses)
    total_cash_out += total_expenses

    ledger = []
    for p in payments:
        ledger.append({
            "date": p.payment_date,
            "type": "Payment",
            "loan": p.loan,
            "client": p.client,
            "cash_in": p.amount_received,
            "cash_out": Decimal("0"),
            "processing_fee": Decimal("0"),
            "principal": p.principal_paid,
            "interest": p.interest_paid,
            "penalty": p.penalty_paid,
            "description": f"Payment received ({p.get_payment_method_display()})",
            "sort_order": 1,
        })

    for l in disbursements:
        if l.cash_disbursed:
            ledger.append({
                "date": l.disbursement_date,
                "type": "Disbursement",
                "loan": l,
                "client": l.client,
                "cash_in": Decimal("0"),
                "cash_out": l.cash_disbursed,
                "principal": l.principal_amount,
                "interest": Decimal("0"),
                "penalty": Decimal("0"),
                "description": "Principal disbursed to client",
                "sort_order": 0,
            })
        if l.effective_processing_fee:
            ledger.append({
                "date": l.disbursement_date,
                "type": "Processing Fee",
                "loan": l,
                "client": l.client,
                "cash_in": l.effective_processing_fee,
                "cash_out": Decimal("0"),
                "principal": Decimal("0"),
                "interest": Decimal("0"),
                "penalty": Decimal("0"),
                "description": "Processing fee collected",
                "sort_order": 0,
            })

    for e in expenses:
        category = e.expense_type.name if e.expense_type else (e.category.name if e.category else "Expense")
        ledger.append({
            "date": e.expense_date,
            "type": "Expense",
            "loan": None,
            "client": None,
            "cash_in": Decimal("0"),
            "cash_out": e.amount,
            "processing_fee": Decimal("0"),
            "principal": Decimal("0"),
            "interest": Decimal("0"),
            "penalty": Decimal("0"),
            "description": category + (f" — {e.vendor}" if e.vendor else ""),
            "sort_order": 2,
        })

    ledger.sort(key=lambda row: (row["date"], row["sort_order"], row["type"]))

    return render(request, "reports/cash_flow.html", {
        "date_from": date_from,
        "date_to": date_to,
        "ledger": ledger,
        "total_cash_in": total_cash_in,
        "total_cash_out": total_cash_out,
        "total_processing_fees": total_processing_fees,
        "total_expenses": total_expenses,
        "total_principal": total_principal,
        "total_interest": total_interest,
        "total_penalties": total_penalties,
        "payment_count": len(payments),
        "disbursement_count": len(disbursements),
        "expense_count": len(expenses),
    })


@_require_manager
def disbursements_report(request):
    today     = date.today()
    date_from = request.GET.get("date_from", today.replace(day=1).isoformat())
    date_to   = request.GET.get("date_to",   today.isoformat())
    product_id = request.GET.get("product", "")

    products = LoanProduct.objects.filter(is_active=True)

    qs = Loan.objects.filter(
        disbursement_date__gte=date_from,
        disbursement_date__lte=date_to,
        status__in=["ACTIVE", "COMPLETED", "DEFAULTED", "WRITTEN_OFF", "RESTRUCTURED"],
    ).select_related("client", "product", "applied_by", "reviewed_by").order_by("-disbursement_date")

    if product_id:
        qs = qs.filter(product_id=product_id)

    total_disbursed    = qs.aggregate(t=Sum("principal_amount"))["t"] or Decimal("0")
    total_interest_exp = qs.aggregate(t=Sum("total_interest"))["t"] or Decimal("0")
    total_fees         = qs.aggregate(t=Sum("processing_fee"))["t"] or Decimal("0")

    return render(request, "reports/disbursements.html", {
        "loans":             qs,
        "total_disbursed":   total_disbursed,
        "total_interest_exp": total_interest_exp,
        "total_fees":        total_fees,
        "loan_count":        qs.count(),
        "products":          products,
        "product_id":        product_id,
        "date_from":         date_from,
        "date_to":           date_to,
    })


@_require_manager
def repayments_report(request):
    today     = date.today()
    date_from = request.GET.get("date_from", today.replace(day=1).isoformat())
    date_to   = request.GET.get("date_to",   today.isoformat())
    method    = request.GET.get("method", "")

    qs = Payment.objects.filter(
        payment_date__gte=date_from,
        payment_date__lte=date_to,
        status="ALLOCATED",
    ).select_related("loan__client", "loan__product", "recorded_by").order_by("-payment_date")

    if method:
        qs = qs.filter(payment_method=method)

    total_received  = qs.aggregate(t=Sum("amount_received"))["t"] or Decimal("0")
    total_principal = qs.aggregate(t=Sum("principal_paid"))["t"] or Decimal("0")
    total_interest  = qs.aggregate(t=Sum("interest_paid"))["t"] or Decimal("0")
    total_penalty   = qs.aggregate(t=Sum("penalty_paid"))["t"] or Decimal("0")

    from payments.models import Payment as P
    methods = P.PaymentMethod.choices

    return render(request, "reports/repayments.html", {
        "payments":       qs,
        "total_received": total_received,
        "total_principal": total_principal,
        "total_interest": total_interest,
        "total_penalty":  total_penalty,
        "payment_count":  qs.count(),
        "date_from":      date_from,
        "date_to":        date_to,
        "method_filter":  method,
        "methods":        methods,
    })


@_require_manager
def defaulted_loans_report(request):
    today = date.today()

    qs = Loan.objects.filter(
        status__in=["DEFAULTED", "WRITTEN_OFF"],
    ).select_related("client", "product", "reviewed_by").order_by("-updated_at")

    # Also include active loans with 90+ days overdue
    par90 = Loan.objects.filter(
        status="ACTIVE",
        par_category="PAR90",
    ).select_related("client", "product")

    total_defaulted   = qs.aggregate(t=Sum("principal_amount"))["t"] or Decimal("0")
    total_outstanding = qs.aggregate(t=Sum("outstanding_balance"))["t"] or Decimal("0")
    total_written_off = qs.filter(status="WRITTEN_OFF").aggregate(t=Sum("outstanding_balance"))["t"] or Decimal("0")

    return render(request, "reports/defaulted.html", {
        "loans":            qs,
        "par90_loans":      par90,
        "total_defaulted":  total_defaulted,
        "total_outstanding": total_outstanding,
        "total_written_off": total_written_off,
        "loan_count":       qs.count(),
        "par90_count":      par90.count(),
        "today":            today,
    })


@_require_manager
def closed_loans_report(request):
    today     = date.today()
    date_from = request.GET.get("date_from", "")
    date_to   = request.GET.get("date_to",   "")
    product_id = request.GET.get("product", "")

    products = LoanProduct.objects.filter(is_active=True)

    qs = Loan.objects.filter(
        status="COMPLETED",
    ).select_related("client", "product").order_by("-completion_date")

    if date_from:
        qs = qs.filter(completion_date__gte=date_from)
    if date_to:
        qs = qs.filter(completion_date__lte=date_to)
    if product_id:
        qs = qs.filter(product_id=product_id)

    total_principal = qs.aggregate(t=Sum("principal_amount"))["t"] or Decimal("0")
    total_interest  = qs.aggregate(t=Sum("total_interest"))["t"] or Decimal("0")
    total_collected = qs.aggregate(t=Sum("total_paid"))["t"] or Decimal("0")

    return render(request, "reports/closed_loans.html", {
        "loans":           qs,
        "total_principal": total_principal,
        "total_interest":  total_interest,
        "total_collected": total_collected,
        "loan_count":      qs.count(),
        "products":        products,
        "product_id":      product_id,
        "date_from":       date_from,
        "date_to":         date_to,
    })


@_require_manager
def par_report(request):
    """Portfolio at Risk report — loans with overdue schedule entries."""
    today = date.today()

    def _par_loans(days_min, days_max=None):
        qs = Loan.objects.filter(status__in=["ACTIVE", "RESTRUCTURED"])
        qs = qs.filter(
            schedule__due_date__lt=today,
            schedule__status__in=["PENDING", "OVERDUE", "PARTIAL"],
        ).distinct()
        result = []
        for loan in qs.select_related("client", "product"):
            oldest = loan.schedule.filter(
                due_date__lt=today,
                status__in=["PENDING", "OVERDUE", "PARTIAL"],
            ).order_by("due_date").first()
            if not oldest:
                continue
            days = (today - oldest.due_date).days
            if days >= days_min and (days_max is None or days < days_max):
                overdue_amt = loan.schedule.filter(
                    due_date__lt=today,
                    status__in=["PENDING", "OVERDUE", "PARTIAL"],
                ).aggregate(
                    t=Sum("total_payment")
                )["t"] or Decimal("0")
                result.append({
                    "loan": loan,
                    "days_overdue": days,
                    "overdue_amount": overdue_amt,
                })
        return result

    par1  = _par_loans(1,  31)
    par30 = _par_loans(31, 61)
    par60 = _par_loans(61, 91)
    par90 = _par_loans(91)

    active_portfolio = Loan.objects.filter(
        status__in=["ACTIVE", "RESTRUCTURED"]
    ).aggregate(t=Sum("outstanding_balance"))["t"] or Decimal("1")

    def _total(rows):
        return sum(r["overdue_amount"] for r in rows)

    def _pct(amt):
        return round(float(amt) / float(active_portfolio) * 100, 2) if active_portfolio else 0

    t1, t30, t60, t90 = _total(par1), _total(par30), _total(par60), _total(par90)
    return render(request, "reports/par.html", {
        "par1":  par1,  "par1_total":  t1,  "par1_pct":  _pct(t1),
        "par30": par30, "par30_total": t30, "par30_pct": _pct(t30),
        "par60": par60, "par60_total": t60, "par60_pct": _pct(t60),
        "par90": par90, "par90_total": t90, "par90_pct": _pct(t90),
        "par_data": [
            (par1,  par1,  "PAR1 — 1 to 30 Days Overdue",  "par1",  t1,  _pct(t1)),
            (par30, par30, "PAR30 — 31 to 60 Days Overdue", "par30", t30, _pct(t30)),
            (par60, par60, "PAR60 — 61 to 90 Days Overdue", "par60", t60, _pct(t60)),
            (par90, par90, "PAR90 — 90+ Days Overdue",      "par90", t90, _pct(t90)),
        ],
        "active_portfolio": active_portfolio,
        "today": today,
    })


@_require_manager
def client_statement(request):
    """Per-client loan & payment statement."""
    client_id = request.GET.get("client", "")
    client    = None
    loans     = []
    payments  = []

    all_clients = Client.objects.filter(is_active=True).order_by("last_name", "first_name")

    if client_id:
        from django.shortcuts import get_object_or_404
        client   = get_object_or_404(Client, pk=client_id)
        loans    = Loan.objects.filter(client=client).select_related("product").order_by("-application_date")
        payments = Payment.objects.filter(client=client).select_related("loan").order_by("-payment_date")

    return render(request, "reports/client_statement.html", {
        "all_clients": all_clients,
        "client":      client,
        "loans":       loans,
        "payments":    payments,
        "client_id":   client_id,
    })


@_require_manager
def staff_performance_report(request):
    """Simple staff performance report based on disbursements, collections, and overdue risk."""
    today = date.today()
    date_from = request.GET.get("date_from", today.replace(day=1).isoformat())
    date_to = request.GET.get("date_to", today.isoformat())
    branch_id = request.GET.get("branch", "")
    role = request.GET.get("role", "")
    staff_id = request.GET.get("staff", "")

    logger.info(
        "Staff performance report requested with filters: date_from=%s date_to=%s branch=%s role=%s staff=%s",
        date_from,
        date_to,
        branch_id or "all",
        role or "all",
        staff_id or "all",
    )

    User = get_user_model()
    all_staff = User.objects.filter(is_active=True).order_by("last_name", "first_name")
    branches = Branch.objects.filter(is_active=True).order_by("name")
    roles = User.Role.choices

    staff_users = all_staff
    if branch_id:
        staff_users = staff_users.filter(branch_id=branch_id)
    if role:
        staff_users = staff_users.filter(role=role)
    if staff_id:
        staff_users = staff_users.filter(pk=staff_id)

    rows = []
    for user in staff_users:
        disbursed_loans = Loan.objects.filter(
            disbursement_date__gte=date_from,
            disbursement_date__lte=date_to,
            applied_by=user,
            status__in=[Loan.Status.ACTIVE, Loan.Status.COMPLETED, Loan.Status.DEFAULTED, Loan.Status.RESTRUCTURED, Loan.Status.WRITTEN_OFF],
        )
        if branch_id:
            disbursed_loans = disbursed_loans.filter(branch_id=branch_id)

        disbursed_amount = disbursed_loans.aggregate(t=Sum("principal_amount"))["t"] or Decimal("0")
        disbursed_count = disbursed_loans.count()

        collected_payments = Payment.objects.filter(
            payment_date__gte=date_from,
            payment_date__lte=date_to,
            recorded_by=user,
            status="ALLOCATED",
        )
        if branch_id:
            collected_payments = collected_payments.filter(loan__branch_id=branch_id)
        collected_amount = collected_payments.aggregate(t=Sum("amount_received"))["t"] or Decimal("0")
        collected_count = collected_payments.count()

        overdue_loans = Loan.objects.filter(
            applied_by=user,
            status__in=[Loan.Status.ACTIVE, Loan.Status.RESTRUCTURED],
            schedule__due_date__lt=today,
            schedule__status__in=[Loan.Status.ACTIVE, "PENDING", "OVERDUE", "PARTIAL"],
        ).distinct()
        if branch_id:
            overdue_loans = overdue_loans.filter(branch_id=branch_id)

        overdue_count = overdue_loans.count()
        overdue_amount = overdue_loans.aggregate(t=Sum("outstanding_balance"))["t"] or Decimal("0")

        total_loans = Loan.objects.filter(applied_by=user)
        if branch_id:
            total_loans = total_loans.filter(branch_id=branch_id)
        total_loans = total_loans.count()

        defaulted_loans = Loan.objects.filter(applied_by=user, status__in=[Loan.Status.DEFAULTED, Loan.Status.WRITTEN_OFF])
        if branch_id:
            defaulted_loans = defaulted_loans.filter(branch_id=branch_id)
        defaulted_loans = defaulted_loans.count()

        quality_score = Decimal("100")
        if disbursed_count:
            quality_score -= Decimal("5") * min(defaulted_loans, Decimal("10"))
        if overdue_count:
            quality_score -= Decimal("2") * min(overdue_count, Decimal("10"))
        quality_score = max(Decimal("0"), quality_score)
        performance_percentage = quality_score

        rows.append({
            "user": user,
            "disbursed_amount": disbursed_amount,
            "disbursed_count": disbursed_count,
            "collected_amount": collected_amount,
            "collected_count": collected_count,
            "overdue_count": overdue_count,
            "overdue_amount": overdue_amount,
            "total_loans": total_loans,
            "defaulted_loans": defaulted_loans,
            "quality_score": quality_score,
            "performance_percentage": performance_percentage,
        })

    rows.sort(key=lambda item: (-item["disbursed_amount"], item["user"].last_name))
    logger.info("Staff performance report completed with %s staff rows", len(rows))

    return render(request, "reports/staff_performance.html", {
        "rows": rows,
        "date_from": date_from,
        "date_to": date_to,
        "today": today,
        "branches": branches,
        "selected_branch": branch_id,
        "roles": roles,
        "selected_role": role,
        "staff_members": all_staff,
        "selected_staff": staff_id,
    })

"""
views_additions.py
===================
Append everything below to the bottom of reports/views.py.

Also add this import near the top of reports/views.py, with the other imports:

    from reportlab.lib.units import mm
    from .pdf_utils import build_report_pdf, p

(You can remove the inline `from reportlab...` imports inside loan_book_download
if you want — they still work fine left as-is, this just avoids duplicate imports.)

Every function below mirrors the exact filtering logic already used by its
matching page view (collections_report, overdue_report, etc.) so the PDF
always matches what's on screen for the same querystring filters.
"""

from django.shortcuts import get_object_or_404
from reportlab.lib.units import mm
from .pdf_utils import build_report_pdf, p, CELL_BOLD


def _ugx(value):
    return f"UGX {value:,.0f}"


# ---------------------------------------------------------------------------
# Collections by Cashier
# ---------------------------------------------------------------------------
@_require_manager
def collections_download(request):
    today     = date.today()
    date_from = request.GET.get("date_from", today.replace(day=1).isoformat())
    date_to   = request.GET.get("date_to",   today.isoformat())

    payments = Payment.objects.filter(
        payment_date__gte=date_from,
        payment_date__lte=date_to,
        status="ALLOCATED",
    ).select_related("loan__client", "recorded_by").order_by("recorded_by__last_name", "-payment_date")

    by_cashier = defaultdict(list)
    for pm in payments:
        by_cashier[pm.recorded_by].append(pm)

    cashier_totals = [
        {"user": user, "payments": pmts, "total": sum(x.amount_received for x in pmts), "count": len(pmts)}
        for user, pmts in by_cashier.items()
    ]
    grand_total = sum(r["total"] for r in cashier_totals)

    body_rows = [
        [p(r["user"].get_full_name() if r["user"] else "Unknown"), p(r["count"]), p(_ugx(r["total"]))]
        for r in cashier_totals
    ]
    totals_row = [p("<b>TOTAL</b>", CELL_BOLD), p(f"<b>{payments.count()}</b>", CELL_BOLD), p(f"<b>{_ugx(grand_total)}</b>", CELL_BOLD)]

    return build_report_pdf(
        request,
        filename=f"Collections-{today}.pdf",
        title="Collections by Cashier",
        subtitle=f"Period: {date_from} to {date_to} | Generated: {datetime.now():%d %b %Y %H:%M}",
        sections=[{
            "heading": None,
            "head_row": ["Cashier", "Payments", "Total Collected"],
            "col_widths": [90*mm, 40*mm, 50*mm],
            "body_rows": body_rows,
            "totals_row": totals_row,
        }],
    )


# ---------------------------------------------------------------------------
# Overdue Installments
# ---------------------------------------------------------------------------
@_require_manager
def overdue_download(request):
    today = date.today()

    overdue = LoanSchedule.objects.filter(
        due_date__lt=today,
        status__in=["PENDING", "PARTIAL"],
        loan__status="ACTIVE",
    ).select_related("loan__client", "loan__product").order_by("due_date")

    rows = []
    for entry in overdue:
        days = (today - entry.due_date).days
        rows.append({
            "entry": entry,
            "days_overdue": days,
            "overdue_amount": entry.total_payment - entry.amount_paid,
        })
    rows.sort(key=lambda r: r["days_overdue"], reverse=True)
    total_overdue = sum(r["overdue_amount"] for r in rows)

    body_rows = [
        [
            p(r["entry"].loan.loan_number),
            p(r["entry"].loan.client.full_name),
            p(r["entry"].due_date.isoformat()),
            p(r["days_overdue"]),
            p(_ugx(r["overdue_amount"])),
        ]
        for r in rows
    ]
    totals_row = [p(""), p(""), p(""), p("<b>TOTAL</b>"), p(f"<b>{_ugx(total_overdue)}</b>")]

    return build_report_pdf(
        request,
        filename=f"Overdue-{today}.pdf",
        title="Overdue Installments Report",
        subtitle=f"As at {today:%d %b %Y} | Generated: {datetime.now():%d %b %Y %H:%M}",
        sections=[{
            "heading": None,
            "head_row": ["Loan #", "Client", "Due Date", "Days Overdue", "Amount Overdue"],
            "col_widths": [28*mm, 55*mm, 28*mm, 28*mm, 41*mm],
            "body_rows": body_rows,
            "totals_row": totals_row,
        }],
    )


# ---------------------------------------------------------------------------
# Monthly Income Statement
# ---------------------------------------------------------------------------
@_require_manager
def income_download(request):
    today     = date.today()
    month_str = request.GET.get("month", today.strftime("%Y-%m"))

    try:
        year, month = int(month_str[:4]), int(month_str[5:7])
    except (ValueError, IndexError):
        year, month = today.year, today.month

    from dateutil.relativedelta import relativedelta as rd
    period_start = date(year, month, 1)
    period_end   = period_start + rd(months=1)

    payments = Payment.objects.filter(
        payment_date__gte=period_start, payment_date__lt=period_end, status="ALLOCATED",
    )
    total_received  = sum(pm.amount_received for pm in payments)
    total_principal = sum(pm.principal_paid  for pm in payments)
    total_interest  = sum(pm.interest_paid   for pm in payments)
    total_penalties = sum(pm.penalty_paid    for pm in payments)

    disbursed = Loan.objects.filter(
        disbursement_date__gte=period_start, disbursement_date__lt=period_end,
    )
    total_disbursed = sum(l.principal_amount for l in disbursed)

    body_rows = [
        [p("Interest Income"),          p(_ugx(total_interest))],
        [p("Penalty Income"),           p(_ugx(total_penalties))],
        [p("Principal Recovered"),      p(_ugx(total_principal))],
        [p("Total Cash Received"),      p(_ugx(total_received))],
        [p("Loans Disbursed (count)"),  p(disbursed.count())],
        [p("Total Principal Disbursed"), p(_ugx(total_disbursed))],
    ]

    return build_report_pdf(
        request,
        filename=f"IncomeStatement-{month_str}.pdf",
        title="Monthly Income Statement",
        subtitle=f"Period: {period_start:%d %b %Y} – {period_end - rd(days=1):%d %b %Y} | "
                  f"Generated: {datetime.now():%d %b %Y %H:%M}",
        sections=[{
            "heading": None,
            "head_row": ["Item", "Amount"],
            "col_widths": [110*mm, 60*mm],
            "body_rows": body_rows,
        }],
    )


# ---------------------------------------------------------------------------
# Cash In / Cash Out
# ---------------------------------------------------------------------------
@_require_manager
def cash_flow_download(request):
    today     = date.today()
    date_from = request.GET.get("date_from", today.replace(day=1).isoformat())
    date_to   = request.GET.get("date_to", today.isoformat())

    payments = list(Payment.objects.filter(
        payment_date__gte=date_from, payment_date__lte=date_to, status="ALLOCATED",
    ).select_related("loan__client", "recorded_by").order_by("payment_date"))

    disbursements = list(Loan.objects.filter(
        disbursement_date__gte=date_from, disbursement_date__lte=date_to,
        status__in=[Loan.Status.ACTIVE, Loan.Status.COMPLETED],
    ).select_related("client", "product").order_by("disbursement_date"))

    expenses = list(Expense.objects.filter(
        expense_date__gte=date_from, expense_date__lte=date_to, status="APPROVED",
    ).select_related("category", "expense_type").order_by("expense_date"))

    total_cash_in = sum(pm.amount_received for pm in payments)
    total_cash_out = sum(l.cash_disbursed for l in disbursements)
    total_processing_fees = sum(l.effective_processing_fee for l in disbursements)
    total_cash_in += total_processing_fees
    total_cash_out += sum(e.amount for e in expenses)

    ledger = []
    for pm in payments:
        ledger.append({
            "date": pm.payment_date, "type": "Payment", "client": pm.client,
            "cash_in": pm.amount_received, "cash_out": Decimal("0"),
            "description": f"Payment received ({pm.get_payment_method_display()})",
            "sort_order": 1,
        })
    for l in disbursements:
        ledger.append({
            "date": l.disbursement_date, "type": "Disbursement", "client": l.client,
            "cash_in": l.effective_processing_fee, "cash_out": l.cash_disbursed,
            "description": "Loan disbursed", "sort_order": 0,
        })
    for e in expenses:
        category = e.expense_type.name if e.expense_type else (e.category.name if e.category else "Expense")
        ledger.append({
            "date": e.expense_date, "type": "Expense", "client": None,
            "cash_in": Decimal("0"), "cash_out": e.amount,
            "description": category + (f" — {e.vendor}" if e.vendor else ""),
            "sort_order": 2,
        })
    ledger.sort(key=lambda row: (row["date"], row["sort_order"], row["type"]))

    body_rows = [
        [
            p(row["date"].isoformat()), p(row["type"]),
            p(row["client"].full_name if row["client"] else "—"),
            p(row["description"]), p(_ugx(row["cash_in"])), p(_ugx(row["cash_out"])),
        ]
        for row in ledger
    ]
    totals_row = [p(""), p(""), p(""), p("<b>TOTAL</b>"), p(f"<b>{_ugx(total_cash_in)}</b>"), p(f"<b>{_ugx(total_cash_out)}</b>")]

    return build_report_pdf(
        request,
        filename=f"CashFlow-{today}.pdf",
        title="Cash In / Cash Out Ledger",
        subtitle=f"Period: {date_from} to {date_to} | Generated: {datetime.now():%d %b %Y %H:%M}",
        landscape=True,
        sections=[{
            "heading": None,
            "head_row": ["Date", "Type", "Client / Description", "Description", "Cash In", "Cash Out"],
            "col_widths": [24*mm, 30*mm, 55*mm, 70*mm, 35*mm, 35*mm],
            "body_rows": body_rows,
            "totals_row": totals_row,
        }],
    )


# ---------------------------------------------------------------------------
# Disbursements
# ---------------------------------------------------------------------------
@_require_manager
def disbursements_download(request):
    today      = date.today()
    date_from  = request.GET.get("date_from", today.replace(day=1).isoformat())
    date_to    = request.GET.get("date_to",   today.isoformat())
    product_id = request.GET.get("product", "")

    qs = Loan.objects.filter(
        disbursement_date__gte=date_from, disbursement_date__lte=date_to,
        status__in=["ACTIVE", "COMPLETED", "DEFAULTED", "WRITTEN_OFF", "RESTRUCTURED"],
    ).select_related("client", "product", "applied_by").order_by("-disbursement_date")
    if product_id:
        qs = qs.filter(product_id=product_id)

    total_disbursed    = qs.aggregate(t=Sum("principal_amount"))["t"] or Decimal("0")
    total_interest_exp = qs.aggregate(t=Sum("total_interest"))["t"] or Decimal("0")
    total_fees         = qs.aggregate(t=Sum("processing_fee"))["t"] or Decimal("0")

    body_rows = [
        [
            p(l.loan_number), p(l.client.full_name), p(l.product.name),
            p(l.applied_by.get_full_name() if l.applied_by else "—"),
            p(_ugx(l.principal_amount)), p(_ugx(l.processing_fee)),
            p(l.disbursement_date.isoformat() if l.disbursement_date else "—"),
        ]
        for l in qs
    ]
    totals_row = [p(""), p(""), p(""), p("<b>TOTAL</b>"), p(f"<b>{_ugx(total_disbursed)}</b>"), p(f"<b>{_ugx(total_fees)}</b>"), p("")]

    return build_report_pdf(
        request,
        filename=f"Disbursements-{today}.pdf",
        title="Disbursements Report",
        subtitle=f"Period: {date_from} to {date_to} | Total Interest Expected: {_ugx(total_interest_exp)} | "
                  f"Generated: {datetime.now():%d %b %Y %H:%M}",
        landscape=True,
        sections=[{
            "heading": None,
            "head_row": ["Loan #", "Client", "Product", "Loan Officer", "Principal", "Fees", "Disbursed"],
            "col_widths": [24*mm, 50*mm, 35*mm, 40*mm, 32*mm, 28*mm, 28*mm],
            "body_rows": body_rows,
            "totals_row": totals_row,
        }],
    )


# ---------------------------------------------------------------------------
# Repayments
# ---------------------------------------------------------------------------
@_require_manager
def repayments_download(request):
    today     = date.today()
    date_from = request.GET.get("date_from", today.replace(day=1).isoformat())
    date_to   = request.GET.get("date_to",   today.isoformat())
    method    = request.GET.get("method", "")

    qs = Payment.objects.filter(
        payment_date__gte=date_from, payment_date__lte=date_to, status="ALLOCATED",
    ).select_related("loan__client", "loan__product", "recorded_by").order_by("-payment_date")
    if method:
        qs = qs.filter(payment_method=method)

    total_received  = qs.aggregate(t=Sum("amount_received"))["t"] or Decimal("0")
    total_principal = qs.aggregate(t=Sum("principal_paid"))["t"] or Decimal("0")
    total_interest  = qs.aggregate(t=Sum("interest_paid"))["t"] or Decimal("0")
    total_penalty   = qs.aggregate(t=Sum("penalty_paid"))["t"] or Decimal("0")

    body_rows = [
        [
            p(pm.payment_date.isoformat()), p(pm.loan.loan_number), p(pm.loan.client.full_name),
            p(pm.get_payment_method_display()), p(_ugx(pm.amount_received)),
            p(_ugx(pm.principal_paid)), p(_ugx(pm.interest_paid)), p(_ugx(pm.penalty_paid)),
        ]
        for pm in qs
    ]
    totals_row = [
        p(""), p(""), p(""), p("<b>TOTAL</b>"), p(f"<b>{_ugx(total_received)}</b>"),
        p(f"<b>{_ugx(total_principal)}</b>"), p(f"<b>{_ugx(total_interest)}</b>"), p(f"<b>{_ugx(total_penalty)}</b>"),
    ]

    return build_report_pdf(
        request,
        filename=f"Repayments-{today}.pdf",
        title="Repayments Report",
        subtitle=f"Period: {date_from} to {date_to} | Generated: {datetime.now():%d %b %Y %H:%M}",
        landscape=True,
        sections=[{
            "heading": None,
            "head_row": ["Date", "Loan #", "Client", "Method", "Received", "Principal", "Interest", "Penalty"],
            "col_widths": [22*mm, 22*mm, 45*mm, 25*mm, 28*mm, 28*mm, 25*mm, 25*mm],
            "body_rows": body_rows,
            "totals_row": totals_row,
        }],
    )


# ---------------------------------------------------------------------------
# Defaulted Loans
# ---------------------------------------------------------------------------
@_require_manager
def defaulted_download(request):
    today = date.today()

    qs = Loan.objects.filter(
        status__in=["DEFAULTED", "WRITTEN_OFF"],
    ).select_related("client", "product").order_by("-updated_at")

    par90 = Loan.objects.filter(status="ACTIVE", par_category="PAR90").select_related("client", "product")

    total_defaulted   = qs.aggregate(t=Sum("principal_amount"))["t"] or Decimal("0")
    total_outstanding = qs.aggregate(t=Sum("outstanding_balance"))["t"] or Decimal("0")

    defaulted_rows = [
        [p(l.loan_number), p(l.client.full_name), p(l.product.name), p(l.get_status_display()),
         p(_ugx(l.principal_amount)), p(_ugx(l.outstanding_balance))]
        for l in qs
    ]
    defaulted_totals = [p(""), p(""), p(""), p("<b>TOTAL</b>"), p(f"<b>{_ugx(total_defaulted)}</b>"), p(f"<b>{_ugx(total_outstanding)}</b>")]

    par90_rows = [
        [p(l.loan_number), p(l.client.full_name), p(l.product.name), p(_ugx(l.outstanding_balance))]
        for l in par90
    ]

    return build_report_pdf(
        request,
        filename=f"Defaulted-{today}.pdf",
        title="Defaulted & Written-Off Loans",
        subtitle=f"As at {today:%d %b %Y} | Generated: {datetime.now():%d %b %Y %H:%M}",
        landscape=True,
        sections=[
            {
                "heading": "Defaulted / Written Off Loans",
                "head_row": ["Loan #", "Client", "Product", "Status", "Principal", "Outstanding"],
                "col_widths": [24*mm, 55*mm, 35*mm, 30*mm, 35*mm, 35*mm],
                "body_rows": defaulted_rows,
                "totals_row": defaulted_totals,
            },
            {
                "heading": "Active Loans 90+ Days Overdue (PAR90)",
                "head_row": ["Loan #", "Client", "Product", "Outstanding"],
                "col_widths": [24*mm, 70*mm, 45*mm, 35*mm],
                "body_rows": par90_rows,
            },
        ],
    )


# ---------------------------------------------------------------------------
# Closed (Fully Repaid) Loans
# ---------------------------------------------------------------------------
@_require_manager
def closed_loans_download(request):
    today      = date.today()
    date_from  = request.GET.get("date_from", "")
    date_to    = request.GET.get("date_to",   "")
    product_id = request.GET.get("product", "")

    qs = Loan.objects.filter(status="COMPLETED").select_related("client", "product").order_by("-completion_date")
    if date_from:
        qs = qs.filter(completion_date__gte=date_from)
    if date_to:
        qs = qs.filter(completion_date__lte=date_to)
    if product_id:
        qs = qs.filter(product_id=product_id)

    total_principal = qs.aggregate(t=Sum("principal_amount"))["t"] or Decimal("0")
    total_interest  = qs.aggregate(t=Sum("total_interest"))["t"] or Decimal("0")
    total_collected = qs.aggregate(t=Sum("total_paid"))["t"] or Decimal("0")

    body_rows = [
        [p(l.loan_number), p(l.client.full_name), p(l.product.name),
         p(l.completion_date.isoformat() if l.completion_date else "—"),
         p(_ugx(l.principal_amount)), p(_ugx(l.total_interest)), p(_ugx(l.total_paid))]
        for l in qs
    ]
    totals_row = [p(""), p(""), p(""), p("<b>TOTAL</b>"), p(f"<b>{_ugx(total_principal)}</b>"),
                  p(f"<b>{_ugx(total_interest)}</b>"), p(f"<b>{_ugx(total_collected)}</b>")]

    return build_report_pdf(
        request,
        filename=f"ClosedLoans-{today}.pdf",
        title="Closed (Fully Repaid) Loans",
        subtitle=f"Period: {date_from or 'Any'} to {date_to or 'Any'} | Generated: {datetime.now():%d %b %Y %H:%M}",
        landscape=True,
        sections=[{
            "heading": None,
            "head_row": ["Loan #", "Client", "Product", "Completed", "Principal", "Interest Earned", "Total Collected"],
            "col_widths": [22*mm, 45*mm, 30*mm, 25*mm, 30*mm, 33*mm, 33*mm],
            "body_rows": body_rows,
            "totals_row": totals_row,
        }],
    )


# ---------------------------------------------------------------------------
# Portfolio at Risk (PAR)
# ---------------------------------------------------------------------------
@_require_manager
def par_download(request):
    today = date.today()

    def _par_loans(days_min, days_max=None):
        qs = Loan.objects.filter(status__in=["ACTIVE", "RESTRUCTURED"])
        qs = qs.filter(
            schedule__due_date__lt=today,
            schedule__status__in=["PENDING", "OVERDUE", "PARTIAL"],
        ).distinct()
        result = []
        for loan in qs.select_related("client", "product"):
            oldest = loan.schedule.filter(
                due_date__lt=today, status__in=["PENDING", "OVERDUE", "PARTIAL"],
            ).order_by("due_date").first()
            if not oldest:
                continue
            days = (today - oldest.due_date).days
            if days >= days_min and (days_max is None or days < days_max):
                overdue_amt = loan.schedule.filter(
                    due_date__lt=today, status__in=["PENDING", "OVERDUE", "PARTIAL"],
                ).aggregate(t=Sum("total_payment"))["t"] or Decimal("0")
                result.append({"loan": loan, "days_overdue": days, "overdue_amount": overdue_amt})
        return result

    buckets = [
        ("PAR1 — 1 to 30 Days Overdue",  _par_loans(1, 31)),
        ("PAR30 — 31 to 60 Days Overdue", _par_loans(31, 61)),
        ("PAR60 — 61 to 90 Days Overdue", _par_loans(61, 91)),
        ("PAR90 — 90+ Days Overdue",      _par_loans(91)),
    ]

    active_portfolio = Loan.objects.filter(
        status__in=["ACTIVE", "RESTRUCTURED"]
    ).aggregate(t=Sum("outstanding_balance"))["t"] or Decimal("1")

    sections = []
    for label, rows in buckets:
        bucket_total = sum(r["overdue_amount"] for r in rows)
        pct = round(float(bucket_total) / float(active_portfolio) * 100, 2) if active_portfolio else 0
        body_rows = [
            [p(r["loan"].loan_number), p(r["loan"].client.full_name), p(r["loan"].product.name),
             p(r["days_overdue"]), p(_ugx(r["overdue_amount"]))]
            for r in rows
        ]
        sections.append({
            "heading": f"{label}  —  {_ugx(bucket_total)}  ({pct}% of portfolio)",
            "head_row": ["Loan #", "Client", "Product", "Days Overdue", "Amount"],
            "col_widths": [24*mm, 55*mm, 35*mm, 30*mm, 42*mm],
            "body_rows": body_rows,
        })

    return build_report_pdf(
        request,
        filename=f"PAR-{today}.pdf",
        title="Portfolio at Risk (PAR)",
        subtitle=f"As at {today:%d %b %Y} | Active Portfolio: {_ugx(active_portfolio)} | "
                  f"Generated: {datetime.now():%d %b %Y %H:%M}",
        landscape=True,
        sections=sections,
    )


# ---------------------------------------------------------------------------
# Client Account Statement
# ---------------------------------------------------------------------------
@_require_manager
def client_statement_download(request):
    client_id = request.GET.get("client", "")
    client = get_object_or_404(Client, pk=client_id) if client_id else None
    today = date.today()

    if not client:
        # Nothing selected — return a near-empty PDF rather than error out.
        return build_report_pdf(
            request,
            filename=f"ClientStatement-{today}.pdf",
            title="Client Account Statement",
            subtitle="No client selected.",
            sections=[{"heading": None, "head_row": ["—"], "col_widths": [170*mm], "body_rows": []}],
        )

    loans = Loan.objects.filter(client=client).select_related("product").order_by("-application_date")
    payments = Payment.objects.filter(client=client).select_related("loan").order_by("-payment_date")

    loan_rows = [
        [p(l.loan_number), p(l.product.name), p(_ugx(l.principal_amount)),
         p(_ugx(l.outstanding_balance)), p(l.get_status_display())]
        for l in loans
    ]
    payment_rows = [
        [p(pm.payment_date.isoformat()), p(pm.loan.loan_number), p(_ugx(pm.amount_received)),
         p(pm.get_payment_method_display())]
        for pm in payments
    ]

    return build_report_pdf(
        request,
        filename=f"ClientStatement-{client.full_name.replace(' ', '')}-{today}.pdf",
        title=f"Client Account Statement — {client.full_name}",
        subtitle=f"Phone: {client.phone_primary} | Generated: {datetime.now():%d %b %Y %H:%M}",
        sections=[
            {
                "heading": "Loans",
                "head_row": ["Loan #", "Product", "Principal", "Outstanding", "Status"],
                "col_widths": [26*mm, 40*mm, 35*mm, 35*mm, 34*mm],
                "body_rows": loan_rows,
            },
            {
                "heading": "Payment History",
                "head_row": ["Date", "Loan #", "Amount", "Method"],
                "col_widths": [35*mm, 35*mm, 50*mm, 50*mm],
                "body_rows": payment_rows,
            },
        ],
    )


# ---------------------------------------------------------------------------
# Staff Performance
# ---------------------------------------------------------------------------
@_require_manager
def staff_performance_download(request):
    today = date.today()
    date_from = request.GET.get("date_from", today.replace(day=1).isoformat())
    date_to = request.GET.get("date_to", today.isoformat())
    branch_id = request.GET.get("branch", "")
    role = request.GET.get("role", "")
    staff_id = request.GET.get("staff", "")

    User = get_user_model()
    staff_users = User.objects.filter(is_active=True).order_by("last_name", "first_name")
    if branch_id:
        staff_users = staff_users.filter(branch_id=branch_id)
    if role:
        staff_users = staff_users.filter(role=role)
    if staff_id:
        staff_users = staff_users.filter(pk=staff_id)

    rows = []
    for user in staff_users:
        disbursed_loans = Loan.objects.filter(
            disbursement_date__gte=date_from, disbursement_date__lte=date_to, applied_by=user,
            status__in=[Loan.Status.ACTIVE, Loan.Status.COMPLETED, Loan.Status.DEFAULTED,
                        Loan.Status.RESTRUCTURED, Loan.Status.WRITTEN_OFF],
        )
        if branch_id:
            disbursed_loans = disbursed_loans.filter(branch_id=branch_id)
        disbursed_amount = disbursed_loans.aggregate(t=Sum("principal_amount"))["t"] or Decimal("0")
        disbursed_count = disbursed_loans.count()

        collected_payments = Payment.objects.filter(
            payment_date__gte=date_from, payment_date__lte=date_to, recorded_by=user, status="ALLOCATED",
        )
        if branch_id:
            collected_payments = collected_payments.filter(loan__branch_id=branch_id)
        collected_amount = collected_payments.aggregate(t=Sum("amount_received"))["t"] or Decimal("0")

        overdue_loans = Loan.objects.filter(
            applied_by=user, status__in=[Loan.Status.ACTIVE, Loan.Status.RESTRUCTURED],
            schedule__due_date__lt=today, schedule__status__in=["PENDING", "OVERDUE", "PARTIAL"],
        ).distinct()
        if branch_id:
            overdue_loans = overdue_loans.filter(branch_id=branch_id)
        overdue_count = overdue_loans.count()

        defaulted_loans = Loan.objects.filter(
            applied_by=user, status__in=[Loan.Status.DEFAULTED, Loan.Status.WRITTEN_OFF],
        )
        if branch_id:
            defaulted_loans = defaulted_loans.filter(branch_id=branch_id)
        defaulted_count = defaulted_loans.count()

        quality_score = Decimal("100")
        if disbursed_count:
            quality_score -= Decimal("5") * min(defaulted_count, 10)
        if overdue_count:
            quality_score -= Decimal("2") * min(overdue_count, 10)
        quality_score = max(Decimal("0"), quality_score)

        rows.append({
            "user": user, "disbursed_amount": disbursed_amount, "disbursed_count": disbursed_count,
            "collected_amount": collected_amount, "overdue_count": overdue_count,
            "defaulted_count": defaulted_count, "quality_score": quality_score,
        })

    rows.sort(key=lambda item: (-item["disbursed_amount"], item["user"].last_name))

    body_rows = [
        [
            p(r["user"].get_full_name()), p(r["disbursed_count"]), p(_ugx(r["disbursed_amount"])),
            p(_ugx(r["collected_amount"])), p(r["overdue_count"]), p(r["defaulted_count"]),
            p(f"{r['quality_score']}%"),
        ]
        for r in rows
    ]

    return build_report_pdf(
        request,
        filename=f"StaffPerformance-{today}.pdf",
        title="Staff Performance Report",
        subtitle=f"Period: {date_from} to {date_to} | Generated: {datetime.now():%d %b %Y %H:%M}",
        landscape=True,
        sections=[{
            "heading": None,
            "head_row": ["Staff", "Loans Disbursed", "Amount Disbursed", "Amount Collected",
                         "Overdue Loans", "Defaulted", "Quality Score"],
            "col_widths": [40*mm, 25*mm, 35*mm, 35*mm, 25*mm, 22*mm, 25*mm],
            "body_rows": body_rows,
        }],
    )