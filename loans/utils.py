"""
loans/utils.py
==============

Two interest methods are supported:

  FLAT_RATE        – Interest = Principal × monthly_rate × term
                     This total interest is split equally across all periods.
                     Each period: same principal chunk + same interest chunk.
                     Common in Ugandan microfinance (simpler for clients to understand).

  REDUCING_BALANCE – Each period's interest = outstanding_balance × monthly_rate
                     Principal portion increases as balance drops.
                     True amortisation — total interest is lower than flat rate.

Usage
-----
    from loans.utils import generate_schedule

    schedule, totals = generate_schedule(
        principal=Decimal("2000000"),
        annual_rate=Decimal("60"),       # 60% per year = 5% per month
        term_months=6,
        start_date=date(2024, 1, 15),
        method="FLAT",
        frequency="MONTHLY",
    )
    # schedule  → list of dicts, one per period
    # totals    → dict with total_repayable, total_interest, effective_apr
"""

from decimal import Decimal, ROUND_HALF_UP
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def _round(amount: Decimal) -> Decimal:
    """Round to 2 decimal places using ROUND_HALF_UP (standard financial rounding)."""
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _next_due_date(current: date, frequency: str, period: int) -> date:
    """
    Calculate the due date for a given period.
    Period 1 = first payment after start_date.
    """
    if frequency == "DAILY":
        return current + timedelta(days=period)
    elif frequency == "WEEKLY":
        return current + timedelta(weeks=period)
    elif frequency == "BIWEEKLY":
        return current + timedelta(weeks=period * 2)
    else:  # MONTHLY
        return current + relativedelta(months=period)


def _periods_for_term(term_months: int, frequency: str) -> int:
    """Convert a term in months to number of repayment periods."""
    if frequency == "DAILY":
        return term_months * 30         # approx 30 days per month
    elif frequency == "WEEKLY":
        return term_months * 4          # approx 4 weeks per month
    elif frequency == "BIWEEKLY":
        return term_months * 2
    else:
        return term_months


# ------------------------------------------------------------------ #
# Main calculator                                                      #
# ------------------------------------------------------------------ #

def _parse_processing_fee_range_amount(principal: Decimal, ranges_text: str) -> Decimal:
    """Parse company-configured processing fee ranges and return the matching amount."""
    principal = Decimal(str(principal or "0"))
    if principal <= 0:
        return Decimal("0")

    for line in (ranges_text or "").splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue

        range_part, amount_part = line.split(":", 1)
        range_part = range_part.strip()
        amount_part = amount_part.strip()
        if not range_part or not amount_part:
            continue

        try:
            fee_amount = Decimal(amount_part)
        except Exception:
            continue

        if "-" in range_part:
            start_text, end_text = range_part.split("-", 1)
            start_text = start_text.strip()
            end_text = end_text.strip()

            min_amount = Decimal(start_text) if start_text else None
            max_amount = Decimal(end_text) if end_text else None

            if min_amount is not None and principal < min_amount:
                continue
            if max_amount is not None and principal > max_amount:
                continue
            return fee_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return Decimal("0")


def calculate_processing_fee_amount(principal, product=None, company_settings=None) -> Decimal:
    """Calculate the processing fee respecting CompanySettings.processing_fee_method.

    PERCENTAGE → default_processing_fee_percent (company) or product rate
    RANGE      → parse processing_fee_ranges text field
    """
    principal = Decimal(str(principal or "0"))
    if principal <= 0:
        return Decimal("0")

    if company_settings is None:
        try:
            from accounts.models import CompanySettings as SettingsModel
            company_settings = SettingsModel.get()
        except Exception:
            return Decimal("0")

    method = getattr(company_settings, "processing_fee_method", "PERCENTAGE") or "PERCENTAGE"

    if method == "RANGE":
        return _parse_processing_fee_range_amount(
            principal,
            getattr(company_settings, "processing_fee_ranges", "") or "",
        )

    rate = resolve_processing_fee_rate(product, company_settings)
    return (principal * rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def resolve_processing_fee_rate(product=None, company_settings=None) -> Decimal:
    """Return the processing fee percentage to use.

    Priority:
    1. Company settings default_processing_fee_percent (if set and method is PERCENTAGE)
    2. Product-level processing_fee_percent
    3. Zero
    """
    if company_settings is None:
        try:
            from accounts.models import CompanySettings as SettingsModel
            company_settings = SettingsModel.get()
        except Exception:
            company_settings = None

    # If company uses RANGE method, percentage rate is not applicable
    if company_settings and getattr(company_settings, "processing_fee_method", "PERCENTAGE") == "RANGE":
        return Decimal("0")

    company_rate = getattr(company_settings, "default_processing_fee_percent", None) if company_settings else None
    if company_rate and company_rate > Decimal("0"):
        return company_rate

    if product and getattr(product, "processing_fee_percent", None) not in (None, Decimal("0")):
        return product.processing_fee_percent

    return Decimal("0")




def generate_schedule(
    principal: Decimal,
    annual_rate: Decimal,
    term_months: int,
    start_date: date,
    method: str = "FLAT",
    frequency: str = "MONTHLY",
) -> tuple[list[dict], dict]:
    """
    Generate a full amortization schedule.

    Parameters
    ----------
    principal    : loan principal in UGX
    annual_rate  : annual interest rate as a percentage (e.g. 60 for 60%/year)
    term_months  : loan term in months
    start_date   : disbursement date (first due date is calculated from this)
    method       : "FLAT" or "REDUCING"
    frequency    : "WEEKLY", "BIWEEKLY", or "MONTHLY"

    Returns
    -------
    (schedule, totals)

    schedule : list of dicts with keys:
        period_number, due_date, opening_balance,
        principal_due, interest_due, total_payment, closing_balance

    totals : dict with keys:
        total_repayable, total_interest, effective_apr
    """
    # Convert annual rate to monthly rate (decimal, not percentage)
    monthly_rate = (annual_rate / Decimal("100")) / Decimal("12")

    num_periods = _periods_for_term(term_months, frequency)

    if method == "FLAT":
        schedule, totals = _flat_rate_schedule(
            principal, monthly_rate, term_months, num_periods, start_date, frequency
        )
    else:  # REDUCING
        schedule, totals = _reducing_balance_schedule(
            principal, monthly_rate, term_months, num_periods, start_date, frequency
        )

    return schedule, totals


def _flat_rate_schedule(
    principal, monthly_rate, term_months, num_periods, start_date, frequency
):
    """
    Flat rate: total interest is fixed, split equally across all periods.
    Equal total payment every period (simple and predictable for clients).
    """
    total_interest   = _round(principal * monthly_rate * Decimal(str(term_months)))
    total_repayable  = _round(principal + total_interest)
    period_principal = _round(principal / Decimal(str(num_periods)))
    period_interest  = _round(total_interest / Decimal(str(num_periods)))
    period_payment   = _round(period_principal + period_interest)

    schedule           = []
    running_total_paid = Decimal("0")
    running_total_p    = Decimal("0")
    running_total_i    = Decimal("0")

    for i in range(1, num_periods + 1):
        due_date        = _next_due_date(start_date, frequency, i)
        # Opening balance = full amount owed at start of this period
        opening_balance = _round(total_repayable - running_total_paid)

        # Last period: absorb any rounding remainders
        if i == num_periods:
            p        = principal - running_total_p
            interest = total_interest - running_total_i
        else:
            p        = period_principal
            interest = period_interest

        p        = _round(p)
        interest = _round(interest)
        payment  = _round(p + interest)
        closing  = _round(opening_balance - payment)

        schedule.append({
            "period_number":   i,
            "due_date":        due_date,
            "opening_balance": opening_balance,
            "principal_due":   p,
            "interest_due":    interest,
            "total_payment":   payment,
            "closing_balance": max(closing, Decimal("0")),
        })

        running_total_paid += payment
        running_total_p    += p
        running_total_i    += interest

    totals = {
        "total_repayable": total_repayable,
        "total_interest":  total_interest,
        "effective_apr":   _round(monthly_rate * Decimal("12") * Decimal("100")),
    }
    return schedule, totals


def _reducing_balance_schedule(
    principal, monthly_rate, term_months, num_periods, start_date, frequency
):
    """
    Reducing balance: interest calculated on outstanding balance each period.
    Higher early interest, lower later. Total interest < flat rate equivalent.
    """
    # Calculate fixed period payment using annuity formula:
    # PMT = P × r / (1 - (1 + r)^-n)
    # where r = period rate, n = number of periods
    if monthly_rate == 0:
        period_payment = _round(principal / Decimal(str(num_periods)))
    else:
        r   = monthly_rate
        n   = Decimal(str(num_periods))
        pmt = principal * r / (1 - (1 + r) ** (-n))
        period_payment = _round(pmt)

    schedule           = []
    balance            = principal
    total_interest     = Decimal("0")
    running_total_paid = Decimal("0")

    for i in range(1, num_periods + 1):
        due_date = _next_due_date(start_date, frequency, i)
        interest = _round(balance * monthly_rate)

        if i == num_periods:
            p       = balance
            payment = _round(p + interest)
        else:
            payment = period_payment
            p       = _round(payment - interest)

        p               = _round(p)
        opening_balance = _round(balance + interest)  # what client owes at period start
        closing         = _round(opening_balance - payment)

        schedule.append({
            "period_number":   i,
            "due_date":        due_date,
            "opening_balance": opening_balance,
            "principal_due":   p,
            "interest_due":    interest,
            "total_payment":   payment,
            "closing_balance": max(closing, Decimal("0")),
        })

        balance            = max(_round(balance - p), Decimal("0"))
        total_interest    += interest
        running_total_paid += payment

    # Override total interest to be principal × monthly_rate × term_months
    total_interest_calc = _round(principal * monthly_rate * Decimal(str(term_months)))
    total_repayable = _round(principal + total_interest_calc)

    totals = {
        "total_repayable": total_repayable,
        "total_interest":  total_interest_calc,
        "effective_apr":   _round(monthly_rate * Decimal("12") * Decimal("100")),
    }
    return schedule, totals


# ------------------------------------------------------------------ #
# Eligibility calculator                                               #
# ------------------------------------------------------------------ #

def calculate_eligibility(client, product) -> dict:
    """
    Assess how much a client can borrow based on income and collateral.

    Rules
    -----
    * Income cap  : max loan = monthly_income × 3  (conservative microfinance ratio)
    * Product cap : capped further by product.max_amount
    * Minimum     : product.min_amount  OR  total declared collateral value (whichever is higher)
    * Risk flags  : active loans reduce the income cap by the outstanding balance

    Returns a dict with:
        income_based_max   – raw income × 3
        active_debt        – sum of outstanding balances on active loans
        net_eligible_max   – income_based_max − active_debt, capped by product
        product_min        – product.min_amount
        eligible           – True if net_eligible_max >= product.min_amount
        flags              – list of warning strings
    """
    from decimal import Decimal

    income = Decimal(str(client.monthly_income or 0))
    income_based_max = income * Decimal("3")

    # Sum outstanding balances on active loans
    active_loans = client.loans.filter(status__in=["ACTIVE", "APPROVED"])
    active_debt  = sum((l.outstanding_balance for l in active_loans), Decimal("0"))

    net_max = max(income_based_max - active_debt, Decimal("0"))
    net_max = min(net_max, product.max_amount)   # never exceed product ceiling

    flags = []
    if income == 0:
        flags.append("No income recorded — eligibility cannot be confirmed.")
    if active_debt > 0:
        flags.append(f"Client has UGX {active_debt:,.0f} outstanding on active loan(s).")
    if net_max < product.min_amount:
        flags.append(
            f"Net eligible amount (UGX {net_max:,.0f}) is below the product minimum "
            f"(UGX {product.min_amount:,.0f})."
        )

    return {
        "income_based_max": income_based_max,
        "active_debt":      active_debt,
        "net_eligible_max": net_max,
        "product_min":      product.min_amount,
        "eligible":         net_max >= product.min_amount,
        "flags":            flags,
    }


def collateral_minimum(collateral_items: list[dict]) -> Decimal:
    """
    Given a list of {description, estimated_value} dicts,
    return the total estimated collateral value.
    This is used as the floor for the minimum loan amount:
        min_borrow = max(product.min_amount, total_collateral_value × 0.5)
    The 50% haircut is standard microfinance practice.
    """
    total = sum(
        Decimal(str(item.get("estimated_value") or 0))
        for item in collateral_items
    )
    return _round(total * Decimal("0.5"))


def calculate_penalty(overdue_amount: Decimal, monthly_penalty_rate: Decimal, months_overdue: int) -> Decimal:
    """
    Calculate late payment penalty.
    penalty = overdue_amount × (monthly_penalty_rate / 100) × months_overdue
    """
    rate    = monthly_penalty_rate / Decimal("100")
    penalty = overdue_amount * rate * Decimal(str(max(months_overdue, 1)))
    return _round(penalty)


# ------------------------------------------------------------------ #
# PDF generation (schedule preview, pre-approval)                    #
# ------------------------------------------------------------------ #

FREQUENCY_LABELS = {
    "DAILY":    "Daily",
    "WEEKLY":   "Weekly",
    "BIWEEKLY": "Bi-Weekly",
    "MONTHLY":  "Monthly",
}


def generate_schedule_preview_pdf(
    client,
    product,
    principal: Decimal,
    term_months: int,
    frequency: str,
    schedule_rows: list,
    totals: dict,
    processing_fee=None,
    fee_source=None,
) -> bytes:
    """
    Render an amortization schedule *preview* (not yet an approved/disbursed
    loan) as a PDF using reportlab. Used from the loan-application wizard so
    the client can be handed a printable schedule before the loan is saved.
    """
    import io
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        title="Loan Schedule Preview",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("PreviewTitle", parent=styles["Title"], fontSize=16, spaceAfter=2)
    sub_style = ParagraphStyle(
        "PreviewSub", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#666666")
    )

    elements = [
        Paragraph("Loan Repayment Schedule — Preview", title_style),
        Paragraph(
            "Indicative schedule based on the details entered. Figures are subject to change "
            "until the loan is approved and disbursed.",
            sub_style,
        ),
        Spacer(1, 10),
    ]

    freq_label = FREQUENCY_LABELS.get((frequency or "").upper(), (frequency or "").title())

    meta_rows = [
        ["Client:", getattr(client, "full_name", ""), "Client No.:", getattr(client, "client_number", "")],
        ["Product:", product.name, "Interest Method:", product.get_interest_method_display()],
        ["Principal:", f"UGX {Decimal(principal):,.0f}", "Term:", f"{term_months} month(s)"],
        ["Frequency:", freq_label, "Monthly Rate:", f"{product.interest_rate_monthly}%"],
    ]
    if processing_fee is not None:
        meta_rows.append(
            ["Processing Fee:", f"UGX {Decimal(processing_fee):,.0f}", "Fee Source:", fee_source or "—"]
        )

    meta_table = Table(meta_rows, colWidths=[28 * mm, 60 * mm, 32 * mm, 50 * mm])
    meta_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 14))

    header = ["#", "Due Date", "Opening Bal.", "Principal", "Interest", "Payment", "Closing Bal."]
    table_data = [header]
    for row in schedule_rows:
        table_data.append([
            str(row["period_number"]),
            row["due_date"].strftime("%d %b %Y"),
            f"{row['opening_balance']:,.0f}",
            f"{row['principal_due']:,.0f}",
            f"{row['interest_due']:,.0f}",
            f"{row['total_payment']:,.0f}",
            f"{row['closing_balance']:,.0f}",
        ])

    schedule_table = Table(
        table_data,
        colWidths=[10 * mm, 26 * mm, 28 * mm, 26 * mm, 24 * mm, 26 * mm, 28 * mm],
        repeatRows=1,
    )
    schedule_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563eb")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f7fb")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    elements.append(schedule_table)
    elements.append(Spacer(1, 12))

    total_interest = totals.get("total_interest", Decimal("0"))
    total_repayable = totals.get("total_repayable", Decimal("0"))
    fee_amount = processing_fee or Decimal("0")
    grand_total = Decimal(total_repayable) + Decimal(fee_amount)

    totals_rows = [
        ["Total Interest:", f"UGX {Decimal(total_interest):,.0f}"],
        ["Total Principal + Interest:", f"UGX {Decimal(total_repayable):,.0f}"],
    ]
    if processing_fee:
        totals_rows.append(["Processing Fee:", f"UGX {Decimal(fee_amount):,.0f}"])
        totals_rows.append(["Grand Total Repayable:", f"UGX {grand_total:,.0f}"])

    totals_table = Table(totals_rows, colWidths=[60 * mm, 40 * mm])
    totals_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    elements.append(totals_table)

    doc.build(elements)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes