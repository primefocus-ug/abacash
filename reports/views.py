"""reports/views.py — all management reports for ABA Uganda.

Every on-screen report and its PDF download are built from the SAME query
helpers below, so the two can never drift apart (scope, statuses, totals).

Conventions used throughout:
  * Dates use timezone.localdate() (Africa/Kampala), never date.today().
  * Branch scoping is applied in one place (_branch / _effective_branch_id).
  * "Cash received" excludes internal client-credit transfers
    (Payment.objects.cash_receipts()); principal/interest/penalty splits
    include them, because that is when the credit is actually earned.
  * "Overdue" = any unpaid installment past due, i.e. PENDING, OVERDUE *or*
    PARTIAL, measured as total_payment + penalty_due - amount_paid.
"""

import logging
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from reportlab.lib.units import mm

from accounts.models import Branch, Expense, CapitalInjection
from accounts.branch_scope import scope_to_branch, can_access_branch_object
from loans.models import Loan, LoanSchedule, LoanProduct
from payments.models import Payment
from clients.models import Client
from .pdf_utils import build_report_pdf, p, CELL_BOLD

logger = logging.getLogger("reports")

ZERO = Decimal("0")
OPEN_SCHEDULE = ["PENDING", "OVERDUE", "PARTIAL"]
LIVE_LOAN = ["ACTIVE", "RESTRUCTURED"]
# Loans whose principal has actually been paid out (keep in sync with accounts/cash.py).
DISBURSED = ["ACTIVE", "COMPLETED", "DEFAULTED", "WRITTEN_OFF", "RESTRUCTURED"]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _ugx(value):
    return f"UGX {value:,.0f}"


def _today():
    return timezone.localdate()


def _stamp():
    return f"{timezone.localtime():%d %b %Y %H:%M}"


def _effective_branch_id(request):
    """Branch a report is scoped to: CEO's ?branch=/switcher, everyone else
    their own branch (-1 = unassigned -> deliberately matches nothing)."""
    from accounts.branch_scope import effective_branch_id
    return effective_branch_id(request)


def _branch(qs, request, field="branch_id"):
    branch_id = _effective_branch_id(request)
    return qs.filter(**{field: branch_id}) if branch_id else qs


def _unpaid(entry):
    """Amount still owed on a schedule row."""
    return max(entry.total_payment + entry.penalty_due - entry.amount_paid, ZERO)


def _sum(qs, field):
    return qs.aggregate(t=Sum(field))["t"] or ZERO


def _period(request):
    today = _today()
    return (
        request.GET.get("date_from", today.replace(day=1).isoformat()),
        request.GET.get("date_to", today.isoformat()),
    )


def _month(request):
    """(month_str, first_day, last_day_inclusive) for the ?month=YYYY-MM picker."""
    today = _today()
    month_str = request.GET.get("month", today.strftime("%Y-%m"))
    try:
        year, month = int(month_str[:4]), int(month_str[5:7])
        first = date(year, month, 1)
    except (ValueError, IndexError):
        first = today.replace(day=1)
        month_str = first.strftime("%Y-%m")
    nxt = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    return month_str, first, nxt - timedelta(days=1)


def _require_manager(view_fn):
    from functools import wraps

    @wraps(view_fn)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.can("can_view_reports"):
            messages.error(request, "You do not have permission to view reports.")
            return redirect("accounts:dashboard")
        return view_fn(request, *args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Shared data builders (used by BOTH the HTML view and the PDF download)
# ---------------------------------------------------------------------------
def _payments_qs(request, date_from, date_to, method=""):
    qs = Payment.objects.filter(
        payment_date__gte=date_from, payment_date__lte=date_to, status="ALLOCATED",
    )
    if method:
        qs = qs.filter(payment_method=method)
    return _branch(qs, request, "loan__branch_id")


def _disbursed_qs(request, date_from, date_to, product_id=""):
    qs = Loan.objects.filter(
        disbursement_date__gte=date_from, disbursement_date__lte=date_to,
        status__in=DISBURSED,
    )
    if product_id:
        qs = qs.filter(product_id=product_id)
    return _branch(qs, request)


def _fees(loans):
    return sum((l.effective_processing_fee for l in loans), ZERO)


def _loan_book_qs(request):
    qs = Loan.objects.filter(status__in=DISBURSED).select_related("client", "product")
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    product_id = request.GET.get("product", "")
    if date_from:
        qs = qs.filter(disbursement_date__gte=date_from)
    if date_to:
        qs = qs.filter(disbursement_date__lte=date_to)
    if product_id:
        qs = qs.filter(product_id=product_id)
    return _branch(qs, request).order_by("-disbursement_date")


def _collections_data(request):
    date_from, date_to = _period(request)
    payments = (
        _payments_qs(request, date_from, date_to).cash_receipts()
        .select_related("loan__client", "recorded_by")
        .order_by("recorded_by__last_name", "-payment_date")
    )
    by_cashier = defaultdict(list)
    for pm in payments:
        by_cashier[pm.recorded_by].append(pm)
    cashier_totals = [
        {"user": user, "payments": pmts,
         "total": sum((x.amount_received for x in pmts), ZERO), "count": len(pmts)}
        for user, pmts in by_cashier.items()
    ]
    return {
        "date_from": date_from, "date_to": date_to,
        "cashier_totals": cashier_totals,
        "grand_total": sum((r["total"] for r in cashier_totals), ZERO),
        "payment_count": sum(r["count"] for r in cashier_totals),
    }


def _overdue_data(request):
    today = _today()
    entries = LoanSchedule.objects.filter(
        due_date__lt=today, status__in=OPEN_SCHEDULE, loan__status__in=LIVE_LOAN,
    ).select_related("loan__client", "loan__product").order_by("due_date")
    entries = _branch(entries, request, "loan__branch_id")
    rows = []
    for entry in entries:
        amount = _unpaid(entry)
        if amount <= 0:
            continue
        rows.append({
            "entry": entry,
            "days_overdue": (today - entry.due_date).days,
            "overdue_amount": amount,
        })
    rows.sort(key=lambda r: r["days_overdue"], reverse=True)
    return {"rows": rows, "total_overdue": sum((r["overdue_amount"] for r in rows), ZERO), "today": today}


PAR_BUCKETS = [
    # (key, label, css, lower_days, upper_days_exclusive)
    ("par1",  "PAR1 — 1 to 30 Days Overdue",   "par1",  1,  31),
    ("par30", "PAR30 — 31 to 60 Days Overdue", "par30", 31, 61),
    ("par60", "PAR60 — 61 to 90 Days Overdue", "par60", 61, 91),
    ("par90", "PAR90 — Over 90 Days Overdue",  "par90", 91, None),
]


def _par_data(request):
    """Portfolio-at-risk. A loan sits in ONE bucket, chosen by its oldest unpaid
    overdue installment. overdue_amount = unpaid part of overdue installments;
    the % is the loan's full outstanding balance over the active portfolio
    (the standard PAR definition)."""
    today = _today()
    loans = _branch(Loan.objects.filter(status__in=LIVE_LOAN), request)
    per_loan = {}
    entries = LoanSchedule.objects.filter(
        loan__in=loans, due_date__lt=today, status__in=OPEN_SCHEDULE,
    ).order_by("due_date")
    for e in entries:
        rec = per_loan.setdefault(e.loan_id, {"oldest": e.due_date, "amount": ZERO})
        rec["amount"] += _unpaid(e)

    loan_map = {l.pk: l for l in loans.filter(pk__in=list(per_loan)).select_related("client", "product")}
    portfolio = _sum(loans, "outstanding_balance")

    buckets = {key: [] for key, *_ in PAR_BUCKETS}
    for loan_id, rec in per_loan.items():
        if rec["amount"] <= 0 or loan_id not in loan_map:
            continue
        days = (today - rec["oldest"]).days
        for key, _label, _css, lo, hi in PAR_BUCKETS:
            if days >= lo and (hi is None or days < hi):
                buckets[key].append({"loan": loan_map[loan_id], "days_overdue": days,
                                     "overdue_amount": rec["amount"]})
                break

    out = []
    for key, label, css, _lo, _hi in PAR_BUCKETS:
        rows = sorted(buckets[key], key=lambda r: r["days_overdue"], reverse=True)
        at_risk = sum((r["loan"].outstanding_balance for r in rows), ZERO)
        pct = round(float(at_risk) / float(portfolio) * 100, 2) if portfolio else 0
        out.append({"key": key, "label": label, "css": css, "rows": rows,
                    "at_risk": at_risk, "pct": pct})
    return {"buckets": out, "portfolio": portfolio, "today": today}


def _defaulted_data(request):
    today = _today()
    qs = _branch(
        Loan.objects.filter(status__in=["DEFAULTED", "WRITTEN_OFF"])
        .select_related("client", "product", "reviewed_by").order_by("-updated_at"),
        request,
    )
    loans = list(qs)

    # Write-off zeroes outstanding_balance, so recover the amount from the
    # installments the write-off waived.
    wo_ids = [l.pk for l in loans if l.status == "WRITTEN_OFF"]
    wo_amounts = defaultdict(lambda: ZERO)
    for e in LoanSchedule.objects.filter(loan_id__in=wo_ids, waived_by_writeoff=True):
        wo_amounts[e.loan_id] += _unpaid(e)
    for l in loans:
        l.written_off_amount = wo_amounts.get(l.pk, ZERO) if l.status == "WRITTEN_OFF" else ZERO

    par90 = [r["loan"] for r in next(b for b in _par_data(request)["buckets"] if b["key"] == "par90")["rows"]]
    return {
        "loans": loans,
        "par90_loans": par90,
        "total_defaulted": sum((l.principal_amount for l in loans), ZERO),
        "total_outstanding": sum((l.outstanding_balance for l in loans), ZERO),
        "total_written_off": sum((l.written_off_amount for l in loans), ZERO),
        "loan_count": len(loans),
        "par90_count": len(par90),
        "today": today,
    }


def _income_data(request):
    month_str, first, last = _month(request)
    payments = _payments_qs(request, first, last)
    cash_payments = payments.cash_receipts()

    total_received = _sum(cash_payments, "amount_received")
    total_principal = _sum(payments, "principal_paid")
    total_interest = _sum(payments, "interest_paid")
    total_penalties = _sum(payments, "penalty_paid")
    total_allocated = total_principal + total_interest + total_penalties

    disbursed = list(_disbursed_qs(request, first, last).select_related("product"))
    total_fees = _fees(disbursed)
    expenses = _branch(Expense.objects.filter(
        expense_date__gte=first, expense_date__lte=last, status="APPROVED"), request)
    total_expenses = _sum(expenses, "amount")

    total_income = total_interest + total_penalties + total_fees
    return {
        "month_str": month_str, "period_start": first, "period_end": last,
        "total_received": total_received,
        "total_principal": total_principal,
        "total_interest": total_interest,
        "total_penalties": total_penalties,
        "total_fees": total_fees,
        "total_income": total_income,
        "total_expenses": total_expenses,
        "net_income": total_income - total_expenses,
        # >0: client credit was consumed this month; <0: overpayments were held as credit.
        "credit_adjustment": total_allocated - total_received,
        "total_disbursed": sum((l.principal_amount for l in disbursed), ZERO),
        "loan_count": len(disbursed),
        "payment_count": cash_payments.count(),
    }


def _cash_flow_data(request):
    date_from, date_to = _period(request)
    sort_by = request.GET.get("sort", "date")
    if sort_by not in {"date", "cash_in", "cash_out"}:
        sort_by = "date"

    payments = list(_branch(
        Payment.objects.cash_receipts().filter(
            payment_date__gte=date_from, payment_date__lte=date_to, status="ALLOCATED",
            payment_method=Payment.PaymentMethod.CASH),
        request, "loan__branch_id",
    ).select_related("loan__client", "client", "recorded_by").order_by("payment_date"))

    disbursements = list(_disbursed_qs(request, date_from, date_to)
                         .select_related("client", "product").order_by("disbursement_date"))

    expenses = list(_branch(Expense.objects.filter(
        expense_date__gte=date_from, expense_date__lte=date_to, status="APPROVED",
        payment_method=Expense.PaymentMethod.CASH,
    ), request).select_related("category", "expense_type").order_by("expense_date"))

    injections = list(_branch(CapitalInjection.objects.filter(
        injected_date__gte=date_from, injected_date__lte=date_to,
        payment_method=CapitalInjection.PaymentMethod.CASH,
    ), request).order_by("injected_date"))

    total_processing_fees = _fees(disbursements)
    total_expenses = sum((e.amount for e in expenses), ZERO)
    total_cash_in = (sum((x.amount_received for x in payments), ZERO)
                     + sum((i.amount for i in injections), ZERO) + total_processing_fees)
    total_cash_out = sum((l.cash_disbursed for l in disbursements), ZERO) + total_expenses

    def row(**kw):
        base = {"loan": None, "client": None, "cash_in": ZERO, "cash_out": ZERO,
                "processing_fee": ZERO, "principal": ZERO, "interest": ZERO, "penalty": ZERO}
        base.update(kw)
        return base

    ledger = []
    for pm in payments:
        ledger.append(row(
            date=pm.payment_date, time=pm.created_at, type="Payment", loan=pm.loan, client=pm.client,
            cash_in=pm.amount_received, principal=pm.principal_paid, interest=pm.interest_paid,
            penalty=pm.penalty_paid, sort_order=1,
            description=f"Payment received ({pm.get_payment_method_display()})"))
    for seq, l in enumerate(disbursements):
        if l.cash_disbursed:
            ledger.append(row(
                date=l.disbursement_date, time=l.created_at, type="Disbursement", loan=l, client=l.client,
                cash_out=l.cash_disbursed, principal=l.principal_amount, sort_order=3 + seq * 2,
                description="Principal disbursed to client"))
        fee = l.effective_processing_fee
        if fee:
            ledger.append(row(
                date=l.disbursement_date, time=l.created_at, type="Processing Fee", loan=l, client=l.client,
                cash_in=fee, sort_order=4 + seq * 2, description="Processing fee collected"))
    for e in expenses:
        category = e.expense_type.name if e.expense_type else (e.category.name if e.category else "Expense")
        ledger.append(row(
            date=e.expense_date, time=e.created_at, type="Expense", cash_out=e.amount, sort_order=2,
            description=category + (f" — {e.vendor}" if e.vendor else "")))
    for i in injections:
        ledger.append(row(
            date=i.injected_date, time=i.created_at, type="Capital Injection", cash_in=i.amount,
            sort_order=0, description=f"Capital injection from {i.source}"))

    if sort_by == "cash_in":
        ledger.sort(key=lambda r: (-r["cash_in"], r["date"], r["sort_order"]))
    elif sort_by == "cash_out":
        ledger.sort(key=lambda r: (-r["cash_out"], r["date"], r["sort_order"]))
    else:
        ledger.sort(key=lambda r: (r["date"], r["sort_order"], r["time"], r["type"]))

    return {
        "date_from": date_from, "date_to": date_to, "ledger": ledger, "sort_by": sort_by,
        "total_cash_in": total_cash_in, "total_cash_out": total_cash_out,
        "total_processing_fees": total_processing_fees, "total_expenses": total_expenses,
        "total_principal": sum((x.principal_paid for x in payments), ZERO),
        "total_interest": sum((x.interest_paid for x in payments), ZERO),
        "total_penalties": sum((x.penalty_paid for x in payments), ZERO),
        "payment_count": len(payments), "disbursement_count": len(disbursements),
        "expense_count": len(expenses),
    }


def _staff_rows(request, date_from, date_to):
    today = _today()
    branch_id = _effective_branch_id(request)
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

    def scoped(qs):
        return qs.filter(branch_id=branch_id) if branch_id else qs

    rows = []
    for user in staff_users:
        disbursed = scoped(Loan.objects.filter(
            disbursement_date__gte=date_from, disbursement_date__lte=date_to,
            applied_by=user, status__in=DISBURSED))
        collected = Payment.objects.cash_receipts().filter(
            payment_date__gte=date_from, payment_date__lte=date_to,
            recorded_by=user, status="ALLOCATED")
        if branch_id:
            collected = collected.filter(loan__branch_id=branch_id)
        overdue = scoped(Loan.objects.filter(
            applied_by=user, status__in=LIVE_LOAN,
            schedule__due_date__lt=today, schedule__status__in=OPEN_SCHEDULE,
        )).distinct()
        overdue_count = overdue.count()
        overdue_amount = sum((l.outstanding_balance for l in overdue), ZERO)
        total_loans = scoped(Loan.objects.filter(applied_by=user)).count()
        defaulted = scoped(Loan.objects.filter(
            applied_by=user, status__in=["DEFAULTED", "WRITTEN_OFF"])).count()
        disbursed_count = disbursed.count()

        quality = Decimal("100")
        if disbursed_count:
            quality -= 5 * min(defaulted, 10)
        if overdue_count:
            quality -= 2 * min(overdue_count, 10)
        quality = max(ZERO, quality)

        rows.append({
            "user": user,
            "disbursed_amount": _sum(disbursed, "principal_amount"),
            "disbursed_count": disbursed_count,
            "collected_amount": _sum(collected, "amount_received"),
            "collected_count": collected.count(),
            "overdue_count": overdue_count, "overdue_amount": overdue_amount,
            "total_loans": total_loans,
            "defaulted_loans": defaulted, "defaulted_count": defaulted,
            "quality_score": quality, "performance_percentage": quality,
        })
    rows.sort(key=lambda r: (-r["disbursed_amount"], r["user"].last_name))
    return rows


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------
@_require_manager
def report_index(request):
    return render(request, "reports/index.html")


# ---------------------------------------------------------------------------
# Loan book
# ---------------------------------------------------------------------------
@_require_manager
def loan_book(request):
    loans = list(_loan_book_qs(request))
    return render(request, "reports/loan_book.html", {
        "loans": loans,
        "total_principal": sum((l.principal_amount for l in loans), ZERO),
        "total_outstanding": sum((l.outstanding_balance for l in loans), ZERO),
        "total_paid": sum((l.total_paid for l in loans), ZERO),
        "products": LoanProduct.objects.filter(is_active=True),
        "date_from": request.GET.get("date_from", ""),
        "date_to": request.GET.get("date_to", ""),
        "product_id": request.GET.get("product", ""),
    })


@_require_manager
def loan_book_download(request):
    loans = list(_loan_book_qs(request))
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    period = f"{date_from or 'Start'} to {date_to or 'End'}" if (date_from or date_to) else "All Loans"

    body_rows = [
        [p(l.loan_number), p(l.client.full_name), p(l.product.name), p(_ugx(l.principal_amount)),
         p(_ugx(l.outstanding_balance)), p(_ugx(l.total_paid)), p(l.get_status_display())]
        for l in loans
    ]
    totals_row = [
        p(""), p(""), p("<b>TOTAL</b>", CELL_BOLD),
        p(f"<b>{_ugx(sum((l.principal_amount for l in loans), ZERO))}</b>", CELL_BOLD),
        p(f"<b>{_ugx(sum((l.outstanding_balance for l in loans), ZERO))}</b>", CELL_BOLD),
        p(f"<b>{_ugx(sum((l.total_paid for l in loans), ZERO))}</b>", CELL_BOLD), p(""),
    ]
    return build_report_pdf(
        request, filename=f"LoanBook-{_today()}.pdf", title="Loan Book Report",
        subtitle=f"Period: {period} | {len(loans)} loans | Generated: {_stamp()}",
        landscape=True,
        sections=[{
            "heading": None,
            "head_row": ["Loan #", "Client", "Product", "Principal", "Outstanding", "Paid", "Status"],
            "col_widths": [28*mm, 60*mm, 40*mm, 34*mm, 34*mm, 34*mm, 30*mm],
            "body_rows": body_rows, "totals_row": totals_row,
        }],
    )


# ---------------------------------------------------------------------------
# Collections by cashier
# ---------------------------------------------------------------------------
@_require_manager
def collections_report(request):
    return render(request, "reports/collections.html", _collections_data(request))


@_require_manager
def collections_download(request):
    d = _collections_data(request)
    body_rows = [
        [p(r["user"].get_full_name() if r["user"] else "Unknown"), p(r["count"]), p(_ugx(r["total"]))]
        for r in d["cashier_totals"]
    ]
    totals_row = [p("<b>TOTAL</b>", CELL_BOLD), p(f"<b>{d['payment_count']}</b>", CELL_BOLD),
                  p(f"<b>{_ugx(d['grand_total'])}</b>", CELL_BOLD)]
    return build_report_pdf(
        request, filename=f"Collections-{_today()}.pdf", title="Collections by Cashier",
        subtitle=f"Period: {d['date_from']} to {d['date_to']} | Generated: {_stamp()}",
        sections=[{"heading": None, "head_row": ["Cashier", "Payments", "Total Collected"],
                   "col_widths": [90*mm, 40*mm, 50*mm], "body_rows": body_rows, "totals_row": totals_row}],
    )


# ---------------------------------------------------------------------------
# Overdue installments
# ---------------------------------------------------------------------------
@_require_manager
def overdue_report(request):
    return render(request, "reports/overdue.html", _overdue_data(request))


@_require_manager
def overdue_download(request):
    d = _overdue_data(request)
    body_rows = [
        [p(r["entry"].loan.loan_number), p(r["entry"].loan.client.full_name),
         p(r["entry"].due_date.isoformat()), p(r["days_overdue"]), p(_ugx(r["overdue_amount"]))]
        for r in d["rows"]
    ]
    totals_row = [p(""), p(""), p(""), p("<b>TOTAL</b>"), p(f"<b>{_ugx(d['total_overdue'])}</b>")]
    return build_report_pdf(
        request, filename=f"Overdue-{d['today']}.pdf", title="Overdue Installments Report",
        subtitle=f"As at {d['today']:%d %b %Y} | Generated: {_stamp()}",
        sections=[{"heading": None,
                   "head_row": ["Loan #", "Client", "Due Date", "Days Overdue", "Amount Overdue"],
                   "col_widths": [28*mm, 55*mm, 28*mm, 28*mm, 41*mm],
                   "body_rows": body_rows, "totals_row": totals_row}],
    )


# ---------------------------------------------------------------------------
# Monthly income statement
# ---------------------------------------------------------------------------
@_require_manager
def income_statement(request):
    return render(request, "reports/income_statement.html", _income_data(request))


@_require_manager
def income_download(request):
    d = _income_data(request)
    body_rows = [
        [p("Interest Income"), p(_ugx(d["total_interest"]))],
        [p("Penalty Income"), p(_ugx(d["total_penalties"]))],
        [p("Processing Fee Income"), p(_ugx(d["total_fees"]))],
        [p("<b>Total Income</b>", CELL_BOLD), p(f"<b>{_ugx(d['total_income'])}</b>", CELL_BOLD)],
        [p("Operating Expenses (approved)"), p(f"- {_ugx(d['total_expenses'])}")],
        [p("<b>Net Income</b>", CELL_BOLD), p(f"<b>{_ugx(d['net_income'])}</b>", CELL_BOLD)],
        [p("Principal Recovered"), p(_ugx(d["total_principal"]))],
        [p("Cash Received (excl. credit transfers)"), p(_ugx(d["total_received"]))],
        [p("Client credit applied / (held) — reconciles cash to allocations"), p(_ugx(d["credit_adjustment"]))],
        [p("Loans Disbursed (count)"), p(d["loan_count"])],
        [p("Total Principal Disbursed"), p(_ugx(d["total_disbursed"]))],
    ]
    return build_report_pdf(
        request, filename=f"IncomeStatement-{d['month_str']}.pdf", title="Monthly Income Statement",
        subtitle=f"Period: {d['period_start']:%d %b %Y} – {d['period_end']:%d %b %Y} | Generated: {_stamp()}",
        sections=[{"heading": None, "head_row": ["Item", "Amount"],
                   "col_widths": [110*mm, 60*mm], "body_rows": body_rows}],
    )


# ---------------------------------------------------------------------------
# Cash in / cash out
# ---------------------------------------------------------------------------
@_require_manager
def cash_flow_report(request):
    return render(request, "reports/cash_flow.html", _cash_flow_data(request))


@_require_manager
def cash_flow_download(request):
    d = _cash_flow_data(request)
    body_rows = [
        [p(r["date"].isoformat()), p(timezone.localtime(r["time"]).strftime("%H:%M:%S")), p(r["type"]),
         p(r["client"].full_name if r["client"] else "—"), p(r["description"]),
         p(_ugx(r["cash_in"])), p(_ugx(r["cash_out"]))]
        for r in d["ledger"]
    ]
    totals_row = [p(""), p(""), p(""), p(""), p("<b>TOTAL</b>"),
                  p(f"<b>{_ugx(d['total_cash_in'])}</b>"), p(f"<b>{_ugx(d['total_cash_out'])}</b>")]
    return build_report_pdf(
        request, filename=f"CashFlow-{_today()}.pdf", title="Cash In / Cash Out Ledger",
        subtitle=f"Period: {d['date_from']} to {d['date_to']} | Generated: {_stamp()}",
        landscape=True,
        sections=[{"heading": None,
                   "head_row": ["Date", "Time", "Type", "Client", "Description", "Cash In", "Cash Out"],
                   "col_widths": [24*mm, 18*mm, 30*mm, 55*mm, 70*mm, 35*mm, 35*mm],
                   "body_rows": body_rows, "totals_row": totals_row}],
    )


# ---------------------------------------------------------------------------
# Disbursements
# ---------------------------------------------------------------------------
def _disbursements_data(request):
    date_from, date_to = _period(request)
    product_id = request.GET.get("product", "")
    loans = list(_disbursed_qs(request, date_from, date_to, product_id)
                 .select_related("client", "product", "applied_by", "reviewed_by")
                 .order_by("-disbursement_date"))
    return {
        "loans": loans,
        "total_disbursed": sum((l.principal_amount for l in loans), ZERO),
        "total_interest_exp": sum((l.total_interest for l in loans), ZERO),
        "total_fees": _fees(loans),
        "loan_count": len(loans),
        "product_id": product_id, "date_from": date_from, "date_to": date_to,
    }


@_require_manager
def disbursements_report(request):
    d = _disbursements_data(request)
    d["products"] = LoanProduct.objects.filter(is_active=True)
    return render(request, "reports/disbursements.html", d)


@_require_manager
def disbursements_download(request):
    d = _disbursements_data(request)
    body_rows = [
        [p(l.loan_number), p(l.client.full_name), p(l.product.name),
         p(l.applied_by.get_full_name() if l.applied_by else "—"),
         p(_ugx(l.principal_amount)), p(_ugx(l.effective_processing_fee)),
         p(l.disbursement_date.isoformat() if l.disbursement_date else "—")]
        for l in d["loans"]
    ]
    totals_row = [p(""), p(""), p(""), p("<b>TOTAL</b>"), p(f"<b>{_ugx(d['total_disbursed'])}</b>"),
                  p(f"<b>{_ugx(d['total_fees'])}</b>"), p("")]
    return build_report_pdf(
        request, filename=f"Disbursements-{_today()}.pdf", title="Disbursements Report",
        subtitle=f"Period: {d['date_from']} to {d['date_to']} | Total Interest Expected: "
                 f"{_ugx(d['total_interest_exp'])} | Generated: {_stamp()}",
        landscape=True,
        sections=[{"heading": None,
                   "head_row": ["Loan #", "Client", "Product", "Loan Officer", "Principal", "Fees", "Disbursed"],
                   "col_widths": [24*mm, 50*mm, 35*mm, 40*mm, 32*mm, 28*mm, 28*mm],
                   "body_rows": body_rows, "totals_row": totals_row}],
    )


# ---------------------------------------------------------------------------
# Repayments
# ---------------------------------------------------------------------------
def _repayments_data(request):
    date_from, date_to = _period(request)
    method = request.GET.get("method", "")
    qs = (_payments_qs(request, date_from, date_to, method)
          .select_related("loan__client", "loan__product", "recorded_by").order_by("-payment_date"))
    return {
        "payments": qs,
        "total_received": _sum(qs.cash_receipts(), "amount_received"),
        "total_principal": _sum(qs, "principal_paid"),
        "total_interest": _sum(qs, "interest_paid"),
        "total_penalty": _sum(qs, "penalty_paid"),
        "payment_count": qs.count(),
        "date_from": date_from, "date_to": date_to, "method_filter": method,
    }


@_require_manager
def repayments_report(request):
    d = _repayments_data(request)
    d["methods"] = Payment.PaymentMethod.choices
    return render(request, "reports/repayments.html", d)


@_require_manager
def repayments_download(request):
    d = _repayments_data(request)
    body_rows = [
        [p(pm.payment_date.isoformat()), p(pm.loan.loan_number), p(pm.loan.client.full_name),
         p(pm.get_payment_method_display()), p(_ugx(pm.amount_received)),
         p(_ugx(pm.principal_paid)), p(_ugx(pm.interest_paid)), p(_ugx(pm.penalty_paid))]
        for pm in d["payments"]
    ]
    totals_row = [p(""), p(""), p(""), p("<b>TOTAL</b>"), p(f"<b>{_ugx(d['total_received'])}</b>"),
                  p(f"<b>{_ugx(d['total_principal'])}</b>"), p(f"<b>{_ugx(d['total_interest'])}</b>"),
                  p(f"<b>{_ugx(d['total_penalty'])}</b>")]
    return build_report_pdf(
        request, filename=f"Repayments-{_today()}.pdf", title="Repayments Report",
        subtitle=f"Period: {d['date_from']} to {d['date_to']} | Cash total excludes internal credit "
                 f"transfers | Generated: {_stamp()}",
        landscape=True,
        sections=[{"heading": None,
                   "head_row": ["Date", "Loan #", "Client", "Method", "Received", "Principal", "Interest", "Penalty"],
                   "col_widths": [22*mm, 22*mm, 45*mm, 25*mm, 28*mm, 28*mm, 25*mm, 25*mm],
                   "body_rows": body_rows, "totals_row": totals_row}],
    )


# ---------------------------------------------------------------------------
# Defaulted / written-off
# ---------------------------------------------------------------------------
@_require_manager
def defaulted_loans_report(request):
    return render(request, "reports/defaulted.html", _defaulted_data(request))


@_require_manager
def defaulted_download(request):
    d = _defaulted_data(request)
    defaulted_rows = [
        [p(l.loan_number), p(l.client.full_name), p(l.product.name), p(l.get_status_display()),
         p(_ugx(l.principal_amount)),
         p(_ugx(l.written_off_amount if l.status == "WRITTEN_OFF" else l.outstanding_balance))]
        for l in d["loans"]
    ]
    defaulted_totals = [p(""), p(""), p(""), p("<b>TOTAL</b>"), p(f"<b>{_ugx(d['total_defaulted'])}</b>"),
                        p(f"<b>{_ugx(d['total_outstanding'] + d['total_written_off'])}</b>")]
    par90_rows = [[p(l.loan_number), p(l.client.full_name), p(l.product.name), p(_ugx(l.outstanding_balance))]
                  for l in d["par90_loans"]]
    return build_report_pdf(
        request, filename=f"Defaulted-{d['today']}.pdf", title="Defaulted & Written-Off Loans",
        subtitle=f"As at {d['today']:%d %b %Y} | Generated: {_stamp()}", landscape=True,
        sections=[
            {"heading": "Defaulted / Written Off Loans (amount = outstanding, or amount written off)",
             "head_row": ["Loan #", "Client", "Product", "Status", "Principal", "Outstanding / Written off"],
             "col_widths": [24*mm, 55*mm, 35*mm, 30*mm, 35*mm, 45*mm],
             "body_rows": defaulted_rows, "totals_row": defaulted_totals},
            {"heading": "Active Loans Over 90 Days Overdue (PAR90)",
             "head_row": ["Loan #", "Client", "Product", "Outstanding"],
             "col_widths": [24*mm, 70*mm, 45*mm, 35*mm], "body_rows": par90_rows},
        ],
    )


# ---------------------------------------------------------------------------
# Closed loans
# ---------------------------------------------------------------------------
def _closed_data(request):
    qs = Loan.objects.filter(status="COMPLETED").select_related("client", "product").order_by("-completion_date")
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    product_id = request.GET.get("product", "")
    if date_from:
        qs = qs.filter(completion_date__gte=date_from)
    if date_to:
        qs = qs.filter(completion_date__lte=date_to)
    if product_id:
        qs = qs.filter(product_id=product_id)
    qs = _branch(qs, request)
    return {
        "loans": qs,
        "total_principal": _sum(qs, "principal_amount"),
        "total_interest": _sum(qs, "total_interest"),
        "total_collected": _sum(qs, "total_paid"),
        "loan_count": qs.count(),
        "product_id": product_id, "date_from": date_from, "date_to": date_to,
    }


@_require_manager
def closed_loans_report(request):
    d = _closed_data(request)
    d["products"] = LoanProduct.objects.filter(is_active=True)
    return render(request, "reports/closed_loans.html", d)


@_require_manager
def closed_loans_download(request):
    d = _closed_data(request)
    body_rows = [
        [p(l.loan_number), p(l.client.full_name), p(l.product.name),
         p(l.completion_date.isoformat() if l.completion_date else "—"),
         p(_ugx(l.principal_amount)), p(_ugx(l.total_interest)), p(_ugx(l.total_paid))]
        for l in d["loans"]
    ]
    totals_row = [p(""), p(""), p(""), p("<b>TOTAL</b>"), p(f"<b>{_ugx(d['total_principal'])}</b>"),
                  p(f"<b>{_ugx(d['total_interest'])}</b>"), p(f"<b>{_ugx(d['total_collected'])}</b>")]
    return build_report_pdf(
        request, filename=f"ClosedLoans-{_today()}.pdf", title="Closed (Fully Repaid) Loans",
        subtitle=f"Period: {d['date_from'] or 'Any'} to {d['date_to'] or 'Any'} | Generated: {_stamp()}",
        landscape=True,
        sections=[{"heading": None,
                   "head_row": ["Loan #", "Client", "Product", "Completed", "Principal", "Interest Earned", "Total Collected"],
                   "col_widths": [22*mm, 45*mm, 30*mm, 25*mm, 30*mm, 33*mm, 33*mm],
                   "body_rows": body_rows, "totals_row": totals_row}],
    )


# ---------------------------------------------------------------------------
# Portfolio at risk
# ---------------------------------------------------------------------------
@_require_manager
def par_report(request):
    d = _par_data(request)
    ctx = {"active_portfolio": d["portfolio"], "today": d["today"], "par_data": []}
    for b in d["buckets"]:
        ctx[b["key"]] = b["rows"]
        ctx[f"{b['key']}_total"] = b["at_risk"]      # outstanding balance at risk
        ctx[f"{b['key']}_pct"] = b["pct"]
        ctx["par_data"].append((b["rows"], b["rows"], b["label"], b["css"], b["at_risk"], b["pct"]))
    return render(request, "reports/par.html", ctx)


@_require_manager
def par_download(request):
    d = _par_data(request)
    sections = []
    for b in d["buckets"]:
        sections.append({
            "heading": f"{b['label']}  —  {_ugx(b['at_risk'])} outstanding at risk  ({b['pct']}% of portfolio)",
            "head_row": ["Loan #", "Client", "Product", "Outstanding", "Overdue Amount", "Days Overdue"],
            "col_widths": [24*mm, 55*mm, 35*mm, 35*mm, 35*mm, 25*mm],
            "body_rows": [
                [p(r["loan"].loan_number), p(r["loan"].client.full_name), p(r["loan"].product.name),
                 p(_ugx(r["loan"].outstanding_balance)), p(_ugx(r["overdue_amount"])), p(r["days_overdue"])]
                for r in b["rows"]
            ],
        })
    return build_report_pdf(
        request, filename=f"PAR-{d['today']}.pdf", title="Portfolio at Risk (PAR)",
        subtitle=f"As at {d['today']:%d %b %Y} | Active Portfolio: {_ugx(d['portfolio'])} | Generated: {_stamp()}",
        landscape=True, sections=sections,
    )


# ---------------------------------------------------------------------------
# Client statement
# ---------------------------------------------------------------------------
@_require_manager
def client_statement(request):
    """Per-client loan & payment statement."""
    client_id = request.GET.get("client", "")
    client = None
    loans = []
    payments = []

    all_clients = scope_to_branch(Client.objects.filter(is_active=True), request.user).order_by("last_name", "first_name")

    if client_id:
        client = get_object_or_404(Client, pk=client_id)
        if not can_access_branch_object(request.user, client):
            messages.error(request, "That client belongs to a different branch.")
            return redirect("reports:client_statement")
        loans = Loan.objects.filter(client=client).select_related("product").order_by("-application_date")
        payments = Payment.objects.filter(client=client, status="ALLOCATED").select_related("loan").order_by("-payment_date")

    return render(request, "reports/client_statement.html", {
        "all_clients": all_clients, "client": client, "loans": loans,
        "payments": payments, "client_id": client_id,
    })


@_require_manager
def client_statement_download(request):
    client_id = request.GET.get("client", "")
    client = get_object_or_404(Client, pk=client_id) if client_id else None
    today = _today()

    if client and not can_access_branch_object(request.user, client):
        messages.error(request, "That client belongs to a different branch.")
        return redirect("reports:client_statement")

    if not client:
        return build_report_pdf(
            request, filename=f"ClientStatement-{today}.pdf", title="Client Account Statement",
            subtitle="No client selected.",
            sections=[{"heading": None, "head_row": ["—"], "col_widths": [170*mm], "body_rows": []}],
        )

    loans = Loan.objects.filter(client=client).select_related("product").order_by("-application_date")
    payments = Payment.objects.filter(client=client, status="ALLOCATED").select_related("loan").order_by("-payment_date")

    loan_rows = [[p(l.loan_number), p(l.product.name), p(_ugx(l.principal_amount)),
                  p(_ugx(l.outstanding_balance)), p(l.get_status_display())] for l in loans]
    payment_rows = [[p(pm.payment_date.isoformat()), p(pm.loan.loan_number), p(_ugx(pm.amount_received)),
                     p(pm.get_payment_method_display())] for pm in payments]

    return build_report_pdf(
        request, filename=f"ClientStatement-{client.full_name.replace(' ', '')}-{today}.pdf",
        title=f"Client Account Statement — {client.full_name}",
        subtitle=f"Phone: {client.phone_primary} | Generated: {_stamp()}",
        sections=[
            {"heading": "Loans", "head_row": ["Loan #", "Product", "Principal", "Outstanding", "Status"],
             "col_widths": [26*mm, 40*mm, 35*mm, 35*mm, 34*mm], "body_rows": loan_rows},
            {"heading": "Payment History", "head_row": ["Date", "Loan #", "Amount", "Method"],
             "col_widths": [35*mm, 35*mm, 50*mm, 50*mm], "body_rows": payment_rows},
        ],
    )


# ---------------------------------------------------------------------------
# Staff performance
# ---------------------------------------------------------------------------
@_require_manager
def staff_performance_report(request):
    date_from, date_to = _period(request)
    branch_id = _effective_branch_id(request)
    rows = _staff_rows(request, date_from, date_to)
    User = get_user_model()
    return render(request, "reports/staff_performance.html", {
        "rows": rows, "date_from": date_from, "date_to": date_to, "today": _today(),
        "branches": Branch.objects.filter(is_active=True).order_by("name"),
        "selected_branch": str(branch_id) if branch_id and branch_id != -1 else "",
        "roles": User.Role.choices, "selected_role": request.GET.get("role", ""),
        "staff_members": User.objects.filter(is_active=True).order_by("last_name", "first_name"),
        "selected_staff": request.GET.get("staff", ""),
    })


@_require_manager
def staff_performance_download(request):
    date_from, date_to = _period(request)
    rows = _staff_rows(request, date_from, date_to)
    body_rows = [
        [p(r["user"].get_full_name()), p(r["disbursed_count"]), p(_ugx(r["disbursed_amount"])),
         p(_ugx(r["collected_amount"])), p(r["overdue_count"]), p(r["defaulted_count"]),
         p(f"{r['quality_score']}%")]
        for r in rows
    ]
    return build_report_pdf(
        request, filename=f"StaffPerformance-{_today()}.pdf", title="Staff Performance Report",
        subtitle=f"Period: {date_from} to {date_to} | Generated: {_stamp()}", landscape=True,
        sections=[{"heading": None,
                   "head_row": ["Staff", "Loans Disbursed", "Amount Disbursed", "Amount Collected",
                                "Overdue Loans", "Defaulted", "Quality Score"],
                   "col_widths": [40*mm, 25*mm, 35*mm, 35*mm, 25*mm, 22*mm, 25*mm],
                   "body_rows": body_rows}],
    )
