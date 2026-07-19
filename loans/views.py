"""
loans/views.py
==============
Loan application, approval workflow, and detail views for ABA Uganda.
"""

from decimal import Decimal, ROUND_HALF_UP
from datetime import date

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import CompanySettings
from clients.models import Client
from .models import (
    Loan,
    LoanProduct,
    LoanSchedule,
    LoanRenewal,
    CollateralItem,
    Guarantor,
    LoanGuarantee,
    LoanDisbursementAudit,
)
from .utils import (
    build_loan_schedule_context,
    calculate_eligibility,
    calculate_processing_fee_amount,
    collateral_minimum,
    generate_schedule,
    resolve_processing_fee_rate,
)
from payments.models import Payment


def _require_role(*roles):
    """Decorator factory: restrict view to given roles."""
    from functools import wraps
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapper(request, *args, **kwargs):
            if request.user.role not in roles:
                messages.error(request, "You do not have permission to access that page.")
                return redirect("accounts:dashboard")
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def _get_client_loan_draft(client):
    return Loan.objects.filter(client=client, status=Loan.Status.DRAFT).order_by("-application_date").first()


def _build_loan_basic_data(loan=None):
    if not loan:
        return {}
    return {
        "product": loan.product,
        "principal": loan.principal_amount,
        "term_months": loan.term_months,
        "frequency": loan.repayment_frequency,
        "purpose": loan.purpose,
    }


def _build_security_data(loan=None):
    if not loan:
        return {
            "collateral_items": [],
            "guarantor_rows": [],
        }
    collateral_items = list(loan.collateral_items.values("description", "estimated_value"))
    guarantor_rows = [
        {"guarantor_id": str(g.guarantor_id), "amount": str(g.guaranteed_amount)}
        for g in loan.guarantees.filter(is_active=False)
    ]
    return {
        "collateral_items": collateral_items,
        "guarantor_rows": guarantor_rows,
    }


# ------------------------------------------------------------------ #
# Loan list                                                            #
# ------------------------------------------------------------------ #

@login_required
def loan_list(request):
    qs = Loan.objects.select_related("client", "product", "applied_by").order_by("-application_date")

    # Cashiers only see loans they applied
    if request.user.is_cashier:
        qs = qs.filter(applied_by=request.user)

    status_filter = request.GET.get("status", "")
    if status_filter:
        qs = qs.filter(status=status_filter)

    staff_filter = request.GET.get("staff", "").strip()
    if staff_filter:
        qs = qs.filter(applied_by_id=staff_filter)

    search = request.GET.get("q", "").strip()
    if search:
        qs = qs.filter(
            loan_number__icontains=search
        ) | qs.filter(
            client__first_name__icontains=search
        ) | qs.filter(
            client__last_name__icontains=search
        )

    User = get_user_model()
    staff_choices = User.objects.filter(is_active=True).order_by("first_name", "last_name", "username")

    context = {
        "loans":          qs[:100],
        "status_choices": Loan.Status.choices,
        "status_filter":  status_filter,
        "staff_choices":  staff_choices,
        "staff_filter":   staff_filter,
        "search":         search,
    }
    return render(request, "loans/loan_list.html", context)


@login_required
def loan_search(request):
    """AJAX endpoint for Select2 loan search. Returns JSON in Select2 format."""
    q = request.GET.get('q', '').strip()
    qs = Loan.objects.select_related('client').order_by('-application_date')
    if q:
        qs = qs.filter(loan_number__icontains=q) | qs.filter(client__first_name__icontains=q) | qs.filter(client__last_name__icontains=q)

    results = []
    for l in qs[:50]:
        text = f"{l.loan_number} — {l.client.full_name} (UGX {int(l.outstanding_balance):,})"
        results.append({"id": str(l.pk), "text": text})

    return JsonResponse({"results": results})


# ------------------------------------------------------------------ #
# Apply for a loan (multi-step)                                        #
# ------------------------------------------------------------------ #

@_require_role("CASHIER", "MANAGER", "CEO")
def loan_apply_step1(request):
    """Step 1: Select or search for the client."""
    return render(request, "loans/apply_step1.html")


@_require_role("CASHIER", "MANAGER", "CEO")
def client_search_htmx(request):
    """HTMX endpoint: instant client search returning a table partial."""
    q = request.GET.get("q", "").strip()
    if q:
        qs = Client.objects.filter(is_active=True).filter(
            first_name__icontains=q
        ) | Client.objects.filter(
            is_active=True, last_name__icontains=q
        ) | Client.objects.filter(
            is_active=True, client_number__icontains=q
        ) | Client.objects.filter(
            is_active=True, nin__icontains=q
        )
        clients = qs.distinct()[:30]
    else:
        clients = Client.objects.filter(is_active=True).order_by("-created_at")[:30]
    return render(request, "partials/client_search_results.html", {"clients": clients, "q": q})


@_require_role("CASHIER", "MANAGER", "CEO")
def loan_apply_step2(request, client_id):
    """Step 2: Enter loan terms and preview amortization schedule."""
    client = get_object_or_404(Client, pk=client_id, is_active=True, is_blacklisted=False)
    active_loan = None
    can_renew = False
    if client.active_loan_count > 0:
        # show existing active loan and allow rollover option when product and user permit
        active_loan = client.loans.filter(status=Loan.Status.ACTIVE).order_by("-disbursement_date").first()
        can_renew = bool(active_loan and active_loan.product and active_loan.product.allows_renewal and (request.user.is_manager or request.user.is_ceo))

    products = LoanProduct.objects.filter(is_active=True)
    company_default_fee = CompanySettings.get().default_processing_fee_percent
    
    loan = _get_client_loan_draft(client)
    form_data = _build_loan_basic_data(loan)
    schedule_rows = []
    totals = {}
    processing_fee = None
    processing_fee_percent = None
    fee_source = None

    if request.method == "POST":
        data = request.POST
        try:
            product_id = int(data.get("product", 0))
            principal = Decimal(str(data.get("principal", "0") or "0"))
            term_months = int(data.get("term_months", 1) or 1)
            frequency = data.get("frequency", Loan.RepaymentFrequency.MONTHLY)
            purpose = data.get("purpose", "").strip()

            product = get_object_or_404(LoanProduct, pk=product_id, is_active=True)

            if principal < product.min_amount or principal > product.max_amount:
                raise ValueError(
                    f"Loan amount must be between UGX {product.min_amount:,.0f} and {product.max_amount:,.0f}."
                )
            if term_months < product.min_term_months or term_months > product.max_term_months:
                raise ValueError(
                    f"Loan term must be between {product.min_term_months} and {product.max_term_months} months for this product."
                )

            if not loan:
                loan = Loan(
                    client=client,
                    applied_by=request.user,
                    status=Loan.Status.DRAFT,
                    application_date=date.today(),
                )

            loan.product = product
            loan.principal_amount = principal
            loan.interest_rate_monthly = product.interest_rate_monthly
            loan.interest_method = product.interest_method
            loan.penalty_rate_monthly = product.penalty_rate_monthly
            loan.term_months = term_months
            loan.repayment_frequency = frequency
            loan.purpose = purpose

            schedule_rows, totals, processing_fee, fee_percent, fee_source = build_loan_schedule_context(
                principal=principal,
                product=product,
                term_months=term_months,
                frequency=frequency,
                start_date=date.today(),
                include_processing_fee=True,
            )
            processing_fee_percent = fee_percent

            loan.processing_fee = processing_fee
            loan.processing_fee_percent = fee_percent if fee_percent else None
            loan.total_interest = totals["total_interest"]
            loan.total_repayable = totals["total_repayable_exclusive"]
            loan.outstanding_balance = loan.total_repayable
            loan.save()

            form_data = {
                "product": product,
                "principal": principal,
                "term_months": term_months,
                "frequency": frequency,
                "purpose": purpose,
            }

            if data.get("action") == "continue":
                return redirect(reverse("loans:apply_step3", kwargs={"client_id": client.pk}))

            messages.success(request, "Loan draft saved. Continue to security details when ready.")

        except (ValueError, TypeError) as e:
            messages.error(request, f"Invalid input: {e}")

    elif loan and loan.product and loan.principal_amount and loan.term_months:
        try:
            schedule_rows, totals, processing_fee, fee_percent, fee_source = build_loan_schedule_context(
                principal=loan.principal_amount,
                product=loan.product,
                term_months=loan.term_months,
                frequency=loan.repayment_frequency,
                start_date=date.today(),
                include_processing_fee=True,
            )
            processing_fee_percent = fee_percent
            form_data = _build_loan_basic_data(loan)
        except Exception as e:
            import logging
            logging.error(f"Error generating schedule for loan {loan.id}: {e}")

    return render(request, "loans/apply_step2.html", {
        "client": client,
        "products": products,
        "schedule_rows": schedule_rows,
        "totals": totals,
        "form_data": form_data,
        "loan": loan,
        "active_loan": active_loan,
        "can_renew": can_renew,
        "processing_fee": processing_fee,
        "processing_fee_percent": processing_fee_percent,
        "fee_source": fee_source,
        "company_default_processing_fee_percent": company_default_fee,
    })


def _calculate_loan_fees(principal, product):
    fee_amount = calculate_processing_fee_amount(principal, product=product)
    fee_percent = resolve_processing_fee_rate(product)
    source = "Company settings (range)" if (fee_amount and not fee_percent) else (product.name if fee_percent else "Company settings")
    return fee_amount, fee_percent, source


def _generate_schedule_correct(principal, monthly_rate, term_months, start_date, method, frequency):
    """
    Generate amortization schedule with CORRECT interest calculation.
    """
    from decimal import Decimal, ROUND_HALF_UP
    from dateutil.relativedelta import relativedelta

    # Convert monthly rate to periodic rate based on frequency
    if frequency == Loan.RepaymentFrequency.MONTHLY:
        total_periods = term_months
        period_rate = monthly_rate
    elif frequency == Loan.RepaymentFrequency.WEEKLY:
        total_periods = term_months * 4  # 4 weeks per month
        # Use compound equivalent: (1 + monthly_rate)^(1/4) - 1
        # Or simple: monthly_rate / 4
        period_rate = monthly_rate / Decimal('4')  # Simple division
    elif frequency == Loan.RepaymentFrequency.BIWEEKLY:
        total_periods = term_months * 2
        period_rate = monthly_rate / Decimal('2')
    elif frequency == Loan.RepaymentFrequency.DAILY:
        total_periods = term_months * 30
        period_rate = monthly_rate / Decimal('30')
    else:
        total_periods = term_months
        period_rate = monthly_rate

    schedule_rows = []
    remaining_balance = principal
    total_interest = Decimal('0')

    if method == LoanProduct.InterestMethod.FLAT_RATE:
        # Flat Rate: Simple interest
        total_interest_flat = principal * monthly_rate * term_months
        total_payment_flat = principal + total_interest_flat
        payment_per_period = (total_payment_flat / total_periods).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        interest_per_period = (total_interest_flat / total_periods).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        principal_per_period = (principal / total_periods).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        for period in range(1, total_periods + 1):
            due_date = start_date + relativedelta(days=period * (30 // (total_periods // term_months if term_months > 0 else 1)))

            if period == total_periods:
                # Last period - adjust for rounding
                principal_due = remaining_balance
                interest_due = total_interest_flat - (interest_per_period * (total_periods - 1))
                total_payment = principal_due + interest_due
            else:
                principal_due = principal_per_period
                interest_due = interest_per_period
                total_payment = payment_per_period

            opening_balance = remaining_balance
            remaining_balance -= principal_due
            closing_balance = max(remaining_balance, Decimal('0'))

            schedule_rows.append({
                'period_number': period,
                'due_date': due_date,
                'opening_balance': opening_balance,
                'principal_due': principal_due,
                'interest_due': interest_due,
                'total_payment': total_payment,
                'closing_balance': closing_balance,
            })

            total_interest += interest_due

    elif method == LoanProduct.InterestMethod.REDUCING_BALANCE:
        # Reducing Balance: Calculate payment using PMT formula
        if period_rate > 0:
            # PMT = P * r * (1+r)^n / ((1+r)^n - 1)
            r = period_rate
            n = total_periods
            # Use Decimal for precision
            one_plus_r = Decimal('1') + r
            payment_per_period = principal * r * (one_plus_r ** n) / ((one_plus_r ** n) - Decimal('1'))
            payment_per_period = payment_per_period.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        else:
            payment_per_period = (principal / total_periods).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        for period in range(1, total_periods + 1):
            due_date = start_date + relativedelta(days=period * (30 // (total_periods // term_months if term_months > 0 else 1)))

            opening_balance = remaining_balance
            # Calculate interest on current balance
            interest_due = (remaining_balance * period_rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            if period == total_periods:
                # Last payment - pay off remaining balance
                principal_due = remaining_balance
                total_payment = principal_due + interest_due
            else:
                principal_due = payment_per_period - interest_due
                # Ensure principal doesn't exceed remaining balance
                if principal_due > remaining_balance:
                    principal_due = remaining_balance
                    total_payment = principal_due + interest_due
                else:
                    total_payment = payment_per_period

            remaining_balance -= principal_due
            closing_balance = max(remaining_balance, Decimal('0'))

            schedule_rows.append({
                'period_number': period,
                'due_date': due_date,
                'opening_balance': opening_balance,
                'principal_due': principal_due,
                'interest_due': interest_due,
                'total_payment': total_payment,
                'closing_balance': closing_balance,
            })

            total_interest += interest_due

    # Calculate processing fee using company default
    fee_amount = _get_processing_fee_amount(principal)

    # Total interest should be principal × monthly_rate × term_months
    total_interest = (principal * monthly_rate * term_months).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    total_repayable = (principal + total_interest).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    totals = {
        'total_repayable': total_repayable,
        'total_interest': total_interest,
        'total_principal': principal,
        'number_of_periods': total_periods,
        'processing_fee': fee_amount,
    }

    return schedule_rows, totals


def _get_processing_fee_amount(principal):
    return calculate_processing_fee_amount(principal)

@_require_role("CASHIER", "MANAGER", "CEO")
def loan_apply_step3(request, client_id):
    """Step 3: Attach collateral and guarantors for the loan draft."""
    client = get_object_or_404(Client, pk=client_id, is_active=True, is_blacklisted=False)
    loan = None
    draft_id = request.POST.get("draft_id") or request.GET.get("draft_id")
    if draft_id:
        loan = get_object_or_404(Loan, pk=draft_id, client=client, status=Loan.Status.DRAFT)
    else:
        loan = _get_client_loan_draft(client)

    if not loan:
        messages.error(request, "No loan draft found for this client. Please complete loan details first.")
        return redirect("loans:apply_step2", client_id=client.pk)

    products = LoanProduct.objects.filter(is_active=True)
    available_guarantors = Guarantor.objects.filter(is_active=True)
    security_data = _build_security_data(loan)
    schedule_rows = []
    totals = {}
    processing_fee = Decimal("0")
    fee_percent = Decimal("0")
    fee_source = "Company settings"

    if loan.product and loan.principal_amount and loan.term_months:
        try:
            schedule_rows, totals, processing_fee, fee_percent, fee_source = build_loan_schedule_context(
                principal=loan.principal_amount,
                product=loan.product,
                term_months=loan.term_months,
                frequency=loan.repayment_frequency,
                start_date=date.today(),
                include_processing_fee=True,
            )
        except Exception:
            pass

    # Preliminary eligibility check (income + active debt). Will be refreshed after collateral input.
    eligibility = None
    effective_min = None
    if loan and loan.product:
        eligibility = calculate_eligibility(client, loan.product)
        coll_items = list(loan.collateral_items.values("description", "estimated_value"))
        coll_floor = collateral_minimum(coll_items)
        effective_min = max(loan.product.min_amount, coll_floor)

    if request.method == "POST":
        data = request.POST
        collateral_descs = data.getlist("collateral_desc")
        collateral_values = data.getlist("collateral_value")
        collateral_items = [
            {"description": d.strip(), "estimated_value": v}
            for d, v in zip(collateral_descs, collateral_values)
            if d.strip() and v
        ]

        guarantor_ids = data.getlist("guarantor_id")
        guarantor_amounts = data.getlist("guarantor_amount")
        guarantor_rows = [
            {"guarantor_id": gid, "amount": amt}
            for gid, amt in zip(guarantor_ids, guarantor_amounts)
            if gid and amt
        ]

        try:
            CollateralItem.objects.filter(loan=loan).delete()
            CollateralItem.objects.bulk_create([
                CollateralItem(
                    loan=loan,
                    description=item["description"],
                    estimated_value=Decimal(str(item["estimated_value"])),
                )
                for item in collateral_items
            ])

            LoanGuarantee.objects.filter(loan=loan).delete()
            draft_guarantees = []
            for row in guarantor_rows:
                try:
                    g = Guarantor.objects.get(pk=row["guarantor_id"], is_active=True)
                except Guarantor.DoesNotExist:
                    continue
                ga = Decimal(str(row["amount"]))
                draft_guarantees.append(LoanGuarantee(
                    guarantor=g,
                    loan=loan,
                    guaranteed_amount=ga,
                    is_active=False,
                ))
            if draft_guarantees:
                LoanGuarantee.objects.bulk_create(draft_guarantees)

            security_data = {
                "collateral_items": collateral_items,
                "guarantor_rows": guarantor_rows,
            }

            # Re-evaluate eligibility taking new collateral into account
            try:
                eligibility = calculate_eligibility(client, loan.product) if loan and loan.product else None
                coll_floor = collateral_minimum(collateral_items)
                effective_min = max(loan.product.min_amount, coll_floor) if loan and loan.product else None

                principal = loan.principal_amount or Decimal("0")
                if eligibility and principal > eligibility.get("net_eligible_max", Decimal("0")):
                    messages.warning(request, f"Principal UGX {principal:,.0f} exceeds recommended limit UGX {eligibility.get('net_eligible_max'):,.0f} based on income and active debt.")
                if effective_min and principal < effective_min:
                    messages.warning(request, f"Principal UGX {principal:,.0f} is below effective minimum UGX {effective_min:,.0f} after collateral floor.")
            except Exception:
                pass

            if data.get("action") == "continue":
                messages.success(request, "Security details saved. Review loan application next.")
                return redirect(reverse("loans:apply_review", kwargs={"client_id": client.pk}) + f"?draft_id={loan.pk}")

            messages.success(request, "Draft security details saved.")
        except (ValueError, TypeError) as e:
            messages.error(request, f"Invalid input: {e}")

    return render(request, "loans/apply_step3.html", {
        "client": client,
        "loan": loan,
        "available_guarantors": available_guarantors,
        "security_data": security_data,
        "schedule_rows": schedule_rows,
        "totals": totals,
        "processing_fee": processing_fee,
        "processing_fee_percent": fee_percent,
        "processing_fee_rate_text": f"{fee_percent}%" if fee_percent else ("Fixed range" if processing_fee else ""),
        "fee_source": "Company settings (range)" if (processing_fee and not fee_percent) else (loan.product.name if fee_percent else "Company settings"),
        "eligibility": eligibility,
        "effective_min": effective_min,
    })


@_require_role("CASHIER", "MANAGER", "CEO")
def loan_apply_review(request, client_id):
    """Step 4: Review loan application draft and submit for approval."""
    client = get_object_or_404(Client, pk=client_id, is_active=True, is_blacklisted=False)
    draft_id = request.POST.get("draft_id") or request.GET.get("draft_id")
    loan = None
    if draft_id:
        loan = get_object_or_404(Loan, pk=draft_id, client=client, status=Loan.Status.DRAFT)
    else:
        loan = _get_client_loan_draft(client)

    if not loan:
        messages.error(request, "No loan draft found to review. Please complete the application details first.")
        return redirect("loans:apply_step2", client_id=client.pk)

    schedule_rows = []
    totals = {}
    processing_fee = Decimal("0")
    fee_percent = Decimal("0")
    fee_source = "Company settings"
    if loan.product and loan.principal_amount and loan.term_months:
        try:
            schedule_rows, totals, processing_fee, fee_percent, fee_source = build_loan_schedule_context(
                principal=loan.principal_amount,
                product=loan.product,
                term_months=loan.term_months,
                frequency=loan.repayment_frequency,
                start_date=date.today(),
                include_processing_fee=True,
            )
        except Exception:
            pass

    collateral_items = list(loan.collateral_items.values("description", "estimated_value"))
    guarantor_rows = [
        {"guarantor": g.guarantor, "amount": g.guaranteed_amount}
        for g in loan.guarantees.filter(is_active=False)
    ]

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "save_draft":
            messages.success(request, "Loan draft saved. You can continue later.")
        elif action == "submit":
            try:
                if not loan.product:
                    raise ValueError("Loan product is required.")
                if loan.product.requires_guarantor and not guarantor_rows:
                    raise ValueError("This product requires at least one guarantor.")
                if loan.product and (loan.principal_amount < loan.product.min_amount or loan.principal_amount > loan.product.max_amount):
                    raise ValueError(
                        f"Loan amount must be between UGX {loan.product.min_amount:,.0f} and {loan.product.max_amount:,.0f}."
                    )
                schedule_rows, totals, processing_fee, _, _ = build_loan_schedule_context(
                    principal=loan.principal_amount,
                    product=loan.product,
                    term_months=loan.term_months,
                    frequency=loan.repayment_frequency,
                    start_date=date.today(),
                    include_processing_fee=True,
                )

                loan.total_repayable = totals["total_repayable_exclusive"]
                loan.total_interest = totals["total_interest"]
                loan.outstanding_balance = totals["total_repayable_exclusive"]
                loan.status = Loan.Status.PENDING
                loan.save()

                LoanSchedule.objects.filter(loan=loan).delete()
                LoanSchedule.objects.bulk_create([
                    LoanSchedule(
                        loan=loan,
                        period_number=row["period_number"],
                        due_date=row["due_date"],
                        opening_balance=row["opening_balance"],
                        principal_due=row["principal_due"],
                        interest_due=row["interest_due"],
                        total_payment=row["total_payment"],
                        closing_balance=row["closing_balance"],
                    )
                    for row in schedule_rows
                ])

                for guarantee in loan.guarantees.filter(is_active=False):
                    g = guarantee.guarantor
                    if g.available_capacity < guarantee.guaranteed_amount and g.max_liability != 0:
                        raise ValueError(f"Guarantor {g} does not have enough available capacity for UGX {guarantee.guaranteed_amount}")
                    guarantee.is_active = True
                    guarantee.save()
                    g.current_liability = g.current_liability + guarantee.guaranteed_amount
                    g.save()

                messages.success(request, f"Loan {loan.loan_number} submitted for approval.")
                return redirect("loans:detail", pk=loan.pk)
            except (ValueError, TypeError) as e:
                messages.error(request, f"Could not submit loan: {e}")

    return render(request, "loans/apply_review.html", {
        "client": client,
        "loan": loan,
        "schedule_rows": schedule_rows,
        "totals": totals,
        "processing_fee": processing_fee,
        "processing_fee_percent": fee_percent,
        "processing_fee_rate_text": f"{fee_percent}%" if fee_percent else ("Fixed range" if processing_fee else ""),
        "fee_source": "Company settings (range)" if (processing_fee and not fee_percent) else (loan.product.name if fee_percent else "Company settings"),
        "collateral_items": collateral_items,
        "guarantor_rows": guarantor_rows,
        "eligibility": calculate_eligibility(client, loan.product) if loan and loan.product else None,
        "effective_min": max(loan.product.min_amount, collateral_minimum(collateral_items)) if loan and loan.product else None,
    })


@_require_role("CASHIER", "MANAGER", "CEO")
def loan_edit(request, pk):
    """Edit an existing loan application while it is DRAFT or PENDING.

    Deleting and recreating collateral, schedule and guarantees on update.
    """
    loan = get_object_or_404(Loan.objects.select_related("client", "product"), pk=pk)

    if loan.status == Loan.Status.REJECTED:
        messages.error(request, "Rejected loans cannot be edited.")
        return redirect("loans:detail", pk=loan.pk)

    # Only allow edits for DRAFT or PENDING applications
    if loan.status not in (Loan.Status.DRAFT, Loan.Status.PENDING):
        messages.error(request, "Only draft or pending applications can be edited.")
        return redirect("loans:detail", pk=loan.pk)

    client = loan.client
    products = LoanProduct.objects.filter(is_active=True)
    available_guarantors = Guarantor.objects.filter(is_active=True)

    schedule_rows = []
    totals = {}
    form_data = {
        "product": loan.product,
        "principal": loan.principal_amount,
        "term_months": loan.term_months,
        "frequency": loan.repayment_frequency,
        "purpose": loan.purpose,
        "collateral_items": list(loan.collateral_items.values("description", "estimated_value")) if hasattr(loan, 'collateral_items') else [],
        "guarantor_rows": [
            {"guarantor_id": str(g.guarantor_id), "amount": str(g.guaranteed_amount)} for g in loan.guarantees.all()
        ],
    }

    if request.method == "POST" or request.GET.get("preview"):
        data = request.POST or request.GET
        try:
            product_id = int(data.get("product", loan.product_id or 0))
            principal = Decimal(str(data.get("principal", loan.principal_amount)))
            term_months = int(data.get("term_months", loan.term_months) or loan.term_months)
            frequency = data.get("frequency", loan.repayment_frequency)
            purpose = data.get("purpose", loan.purpose or "")

            product = get_object_or_404(LoanProduct, pk=product_id, is_active=True)

            # Parse collateral
            collateral_descs = data.getlist("collateral_desc")
            collateral_values = data.getlist("collateral_value")
            collateral_items = [
                {"description": d.strip(), "estimated_value": v}
                for d, v in zip(collateral_descs, collateral_values)
                if d.strip() and v
            ]

            # Validate limits
            if principal < product.min_amount or principal > product.max_amount:
                raise ValueError(
                    f"Loan amount must be between UGX {product.min_amount:,.0f} and {product.max_amount:,.0f}."
                )
            if term_months < product.min_term_months or term_months > product.max_term_months:
                raise ValueError(
                    f"Loan term must be between {product.min_term_months} and {product.max_term_months} months for this product."
                )

            schedule_rows, totals, processing_fee, _, _ = build_loan_schedule_context(
                principal=principal,
                product=product,
                term_months=term_months,
                frequency=frequency,
                start_date=date.today(),
                include_processing_fee=True,
            )

            guarantor_ids = data.getlist("guarantor_id")
            guarantor_amounts = data.getlist("guarantor_amount")

            # Handle full POST submit
            if request.method == "POST" and data.get("action") == "submit":
                # Update loan fields
                loan.product = product
                loan.principal_amount = principal
                loan.interest_rate_monthly = product.interest_rate_monthly
                loan.interest_method = product.interest_method
                loan.penalty_rate_monthly = product.penalty_rate_monthly
                loan.term_months = term_months
                loan.repayment_frequency = frequency
                fee_percent = resolve_processing_fee_rate(product)
                loan.processing_fee_percent = fee_percent if fee_percent else None
                loan.processing_fee = processing_fee
                loan.total_repayable = totals["total_repayable_exclusive"]
                loan.total_interest = totals["total_interest"]
                loan.outstanding_balance = loan.total_repayable
                loan.total_fees = processing_fee
                loan.purpose = purpose
                loan.applied_by = request.user if not loan.applied_by else loan.applied_by
                loan.save()

                # Replace collateral items: delete existing and recreate
                CollateralItem.objects.filter(loan=loan).delete()
                CollateralItem.objects.bulk_create([
                    CollateralItem(
                        loan=loan,
                        description=item["description"],
                        estimated_value=Decimal(str(item["estimated_value"])),
                    )
                    for item in collateral_items
                ])

                # Replace schedule rows
                LoanSchedule.objects.filter(loan=loan).delete()
                LoanSchedule.objects.bulk_create([
                    LoanSchedule(
                        loan=loan,
                        period_number=row["period_number"],
                        due_date=row["due_date"],
                        opening_balance=row["opening_balance"],
                        principal_due=row["principal_due"],
                        interest_due=row["interest_due"],
                        total_payment=row["total_payment"],
                        closing_balance=row["closing_balance"],
                    )
                    for row in schedule_rows
                ])

                # Replace guarantees: adjust guarantor liabilities safely
                # Subtract old guarantees from guarantors
                for lg in LoanGuarantee.objects.filter(loan=loan):
                    g = lg.guarantor
                    g.current_liability = max(Decimal("0"), g.current_liability - lg.guaranteed_amount)
                    g.save()
                LoanGuarantee.objects.filter(loan=loan).delete()

                # Create new guarantees
                new_guarantees = []
                for gid, amt in zip(guarantor_ids, guarantor_amounts):
                    if not gid or not amt:
                        continue
                    try:
                        g = Guarantor.objects.get(pk=gid, is_active=True)
                    except Guarantor.DoesNotExist:
                        continue
                    ga = Decimal(str(amt))
                    if g.available_capacity < ga and g.max_liability != 0:
                        raise ValueError(f"Guarantor {g} does not have enough available capacity for UGX {ga}")
                    new_guarantees.append(LoanGuarantee(guarantor=g, loan=loan, guaranteed_amount=ga))

                if new_guarantees:
                    LoanGuarantee.objects.bulk_create(new_guarantees)
                    for lg in LoanGuarantee.objects.filter(loan=loan):
                        g = lg.guarantor
                        g.current_liability = g.current_liability + lg.guaranteed_amount
                        g.save()

                messages.success(request, f"Loan {loan.loan_number} updated.")
                return redirect("loans:detail", pk=loan.pk)

        except (ValueError, TypeError) as e:
            messages.error(request, f"Invalid input: {e}")

    return render(request, "loans/apply_step2.html", {
        "client": client,
        "products": products,
        "available_guarantors": available_guarantors,
        "schedule_rows": schedule_rows,
        "totals": totals,
        "form_data": form_data,
        "eligibility": None,
        "editing": True,
        "loan": loan,
    })


# ------------------------------------------------------------------ #
# Loan detail                                                          #
# ------------------------------------------------------------------ #

@login_required
def loan_detail(request, pk):
    loan = get_object_or_404(Loan.objects.select_related("client", "product", "applied_by", "reviewed_by"), pk=pk)
    schedule  = loan.schedule.order_by("period_number")
    payments  = loan.payments.order_by("-payment_date")
    renewals  = loan.renewal_records.select_related("new_loan").order_by("-renewal_date")

    # Attempt to fetch recent disbursement audits; tolerate missing table (migrations not yet applied)
    recent_audits = []
    audits_total = 0
    try:
        from django.db import ProgrammingError, OperationalError
        recent_qs = LoanDisbursementAudit.objects.filter(loan=loan).order_by('-created_at')
        recent_audits = list(recent_qs[:3])
        audits_total = recent_qs.count()
    except (Exception,) as e:
        # Catch broad exceptions to avoid breaking the loan detail view before migrations.
        # Specifically ProgrammingError/OperationalError may occur when table doesn't exist.
        import logging
        logging.debug('Could not fetch disbursement audit entries: %s', e)
        recent_audits = []
        audits_total = 0

    return render(request, "loans/loan_detail.html", {
        "loan":     loan,
        "schedule": schedule,
        "payments": payments,
        "renewals": renewals,
        "today":    date.today(),
        "recent_disbursement_audits": recent_audits,
        "disbursement_audits_total": audits_total,
    })

@_require_role("MANAGER", "CEO")
def loan_reschedule(request, pk):
    """Handle payment rescheduling separately from renewals.

    This view accepts both regular and HTMX requests. When requested
    via HTMX it returns the small form fragment (renew_loan_fragment.html)
    suitable for modal display. On POST it validates input, optionally
    accepts a disbursement_date (CEOs may back-date), regenerates the
    repayment schedule for the outstanding balance and replaces the
    loan's schedule rows.
    """
    loan = get_object_or_404(
        Loan.objects.select_related("client", "product"),
        pk=pk,
        status=Loan.Status.ACTIVE,
    )

    # If a POST request, handle the reschedule submission
    if request.method == "POST":
        try:
            term_months = int(request.POST.get("term_months", loan.term_months) or loan.term_months)
            frequency = request.POST.get("frequency", loan.repayment_frequency)
            reason = request.POST.get("reason", "").strip()

            if not reason:
                raise ValueError("Rescheduling reason is required.")

            if term_months < loan.product.min_term_months or term_months > loan.product.max_term_months:
                raise ValueError(
                    f"Term must be between {loan.product.min_term_months} and {loan.product.max_term_months} months."
                )

            if frequency not in dict(Loan.RepaymentFrequency.choices):
                raise ValueError("Invalid repayment frequency selected.")

            outstanding_amount = loan.outstanding_balance
            if outstanding_amount <= Decimal("0"):
                raise ValueError("Loan has no outstanding balance to reschedule.")

            # Allow optional disbursement_date from the form (CEOs may back-date)
            provided_disb = request.POST.get('disbursement_date', '').strip()
            if provided_disb:
                try:
                    chosen_disbursement = date.fromisoformat(provided_disb)
                except Exception:
                    raise ValueError("Invalid disbursement date format. Use YYYY-MM-DD.")
                if chosen_disbursement < date.today() and not request.user.is_ceo:
                    raise ValueError("Only the CEO may set a past disbursement date.")
            else:
                chosen_disbursement = date.today()

            # Generate new schedule
            schedule_rows, totals, _, _, _ = build_loan_schedule_context(
                principal=outstanding_amount,
                product=loan.product,
                term_months=term_months,
                frequency=frequency,
                start_date=chosen_disbursement,
                include_processing_fee=False,
            )

            # Update the loan's schedule instead of creating a new loan
            old_date = loan.disbursement_date
            loan.term_months = term_months
            loan.repayment_frequency = frequency
            loan.disbursement_date = chosen_disbursement
            loan.maturity_date = schedule_rows[-1]["due_date"]
            loan.total_repayable = totals["total_repayable_exclusive"]
            loan.total_interest = totals["total_interest"]
            loan.outstanding_balance = totals["total_repayable_exclusive"]
            loan.save()

            # Create an audit record if the disbursement date changed
            try:
                if old_date != loan.disbursement_date:
                    LoanDisbursementAudit.objects.create(
                        loan=loan,
                        changed_by=request.user,
                        old_disbursement_date=old_date,
                        new_disbursement_date=loan.disbursement_date,
                        action='reschedule',
                        reason=reason[:2000],
                    )
            except Exception:
                import logging
                logging.exception('Failed to create disbursement audit for loan %s', loan.pk)

            # Delete old schedule and create new one
            LoanSchedule.objects.filter(loan=loan).delete()
            LoanSchedule.objects.bulk_create([
                LoanSchedule(
                    loan=loan,
                    period_number=row["period_number"],
                    due_date=row["due_date"],
                    opening_balance=row["opening_balance"],
                    principal_due=row["principal_due"],
                    interest_due=row["interest_due"],
                    total_payment=row["total_payment"],
                    closing_balance=row["closing_balance"],
                )
                for row in schedule_rows
            ])

            messages.success(request, f"Loan {loan.loan_number} has been rescheduled.")
            # HTMX: return small fragment to close modal and refresh
            if request.headers.get('HX-Request') == 'true' or request.META.get('HTTP_HX_REQUEST') == 'true':
                from django.urls import reverse
                return render(request, 'loans/htmx_success.html', {
                    'message': f'Loan {loan.loan_number} has been rescheduled.',
                    'redirect': '"' + reverse('loans:detail', kwargs={'pk': loan.pk}) + '"',
                })
            return redirect("loans:detail", pk=loan.pk)

        except Exception as e:
            messages.error(request, f"Rescheduling Error: {e}")

    # For GET (or after errors), render the form (fragment for HTMX)
    frequency_choices = Loan.RepaymentFrequency.choices
    context = {
        "loan": loan,
        "frequency_choices": frequency_choices,
        "default_term": loan.term_months,
        "min_term": loan.product.min_term_months,
        "max_term": loan.product.max_term_months,
        "is_reschedule": True,
        "action_title": "Reschedule Loan",
        "submit_label": "Reschedule Loan",
        "helper_text": "This creates a new repayment schedule for the existing loan.",
        "today": date.today(),
    }
    if request.headers.get('HX-Request') == 'true' or request.META.get('HTTP_HX_REQUEST') == 'true':
        return render(request, 'loans/renew_loan_fragment.html', context)
    return render(request, "loans/renew_loan.html", context)


@login_required
def loan_regenerate_schedule(request, pk):
    """HTMX endpoint to GET a small form and POST to regenerate the repayment schedule.

    GET: returns a small fragment with a date input (modal body)
    POST: regenerates schedule using the provided disbursement_date and returns the updated
          schedule card fragment so the page can update via HTMX.
    """
    loan = get_object_or_404(Loan.objects.select_related("product", "client"), pk=pk)

    # GET -> return the small form fragment
    if request.method == "GET":
        return render(request, "loans/htmx_regenerate_schedule_form.html", {
            "loan": loan,
            "today": date.today(),
        })

    # POST -> perform regeneration
    if request.method == "POST":
        provided = request.POST.get("disbursement_date", "").strip()
        if not provided:
            messages.error(request, "Please provide a disbursement date.")
            return redirect("loans:detail", pk=loan.pk)

        try:
            parsed = date.fromisoformat(provided)
        except Exception:
            messages.error(request, "Invalid disbursement date format. Use YYYY-MM-DD.")
            return redirect("loans:detail", pk=loan.pk)

        # Non-CEOs may not back-date; CEOs may
        if not request.user.is_ceo and parsed < date.today():
            messages.error(request, "Only the CEO may set a past disbursement date.")
            return redirect("loans:detail", pk=loan.pk)

        # Decide principal: for ACTIVE loans use outstanding_balance, otherwise use principal_amount
        principal_to_use = loan.outstanding_balance if loan.status == Loan.Status.ACTIVE else loan.principal_amount

        try:
            schedule_rows, totals, _, _, _ = build_loan_schedule_context(
                principal=principal_to_use,
                product=loan.product,
                term_months=loan.term_months,
                frequency=loan.repayment_frequency,
                start_date=parsed,
                include_processing_fee=False,
            )

            # Replace schedule rows
            LoanSchedule.objects.filter(loan=loan).delete()
            LoanSchedule.objects.bulk_create([
                LoanSchedule(
                    loan=loan,
                    period_number=row["period_number"],
                    due_date=row["due_date"],
                    opening_balance=row["opening_balance"],
                    principal_due=row["principal_due"],
                    interest_due=row["interest_due"],
                    total_payment=row["total_payment"],
                    closing_balance=row["closing_balance"],
                )
                for row in schedule_rows
            ])

            old_date = loan.disbursement_date
            loan.disbursement_date = parsed
            loan.first_repayment_date = schedule_rows[0]["due_date"]
            loan.maturity_date = schedule_rows[-1]["due_date"]
            loan.total_repayable = totals.get("total_repayable", loan.total_repayable)
            loan.total_interest = totals.get("total_interest", loan.total_interest)
            loan.outstanding_balance = loan.total_repayable
            loan.save()

            # Create an audit record if the disbursement date changed
            try:
                if old_date != loan.disbursement_date:
                    LoanDisbursementAudit.objects.create(
                        loan=loan,
                        changed_by=request.user,
                        old_disbursement_date=old_date,
                        new_disbursement_date=loan.disbursement_date,
                        action='regenerate',
                        reason=request.POST.get('reason', '')[:2000],
                    )
            except Exception:
                # Never raise audit failures to the user flow
                import logging
                logging.exception('Failed to create disbursement audit for loan %s', loan.pk)

            # Return updated schedule fragment so HTMX can replace the card
            schedule = loan.schedule.order_by("period_number")
            return render(request, "loans/loan_detail_schedule_fragment.html", {
                "loan": loan,
                "schedule": schedule,
                "user": request.user,
            })

        except Exception as e:
            import logging
            logging.exception("Failed to regenerate schedule for loan %s: %s", loan.pk, e)
            messages.error(request, "Failed to regenerate schedule. See logs.")
            return redirect("loans:detail", pk=loan.pk)

    if loan.outstanding_balance <= Decimal("0"):
        messages.error(request, "This loan has no outstanding balance to reschedule.")
        return redirect("loans:detail", pk=loan.pk)

    if request.method == "POST":
        try:
            term_months = int(request.POST.get("term_months", loan.term_months) or loan.term_months)
            frequency = request.POST.get("frequency", loan.repayment_frequency)
            reason = request.POST.get("reason", "").strip()

            if not reason:
                raise ValueError("Rescheduling reason is required.")

            if term_months < loan.product.min_term_months or term_months > loan.product.max_term_months:
                raise ValueError(
                    f"Term must be between {loan.product.min_term_months} and {loan.product.max_term_months} months."
                )

            if frequency not in dict(Loan.RepaymentFrequency.choices):
                raise ValueError("Invalid repayment frequency selected.")

            outstanding_amount = loan.outstanding_balance
            if outstanding_amount <= Decimal("0"):
                raise ValueError("Loan has no outstanding balance to reschedule.")

            # Allow optional disbursement_date from the form (CEOs may back-date)
            provided_disb = request.POST.get('disbursement_date', '').strip()
            if provided_disb:
                try:
                    chosen_disbursement = date.fromisoformat(provided_disb)
                except Exception:
                    raise ValueError("Invalid disbursement date format. Use YYYY-MM-DD.")
                if chosen_disbursement < date.today() and not request.user.is_ceo:
                    raise ValueError("Only the CEO may set a past disbursement date.")
            else:
                chosen_disbursement = date.today()

            # Generate new schedule
            schedule_rows, totals, _, _, _ = build_loan_schedule_context(
                principal=outstanding_amount,
                product=loan.product,
                term_months=term_months,
                frequency=frequency,
                start_date=chosen_disbursement,
                include_processing_fee=False,
            )

            # Update the loan's schedule instead of creating a new loan
            loan.term_months = term_months
            loan.repayment_frequency = frequency
            loan.maturity_date = schedule_rows[-1]["due_date"]
            loan.total_repayable = totals["total_repayable_exclusive"]
            loan.total_interest = totals["total_interest"]
            loan.outstanding_balance = totals["total_repayable_exclusive"]
            loan.save()

            # Delete old schedule and create new one
            LoanSchedule.objects.filter(loan=loan).delete()
            LoanSchedule.objects.bulk_create([
                LoanSchedule(
                    loan=loan,
                    period_number=row["period_number"],
                    due_date=row["due_date"],
                    opening_balance=row["opening_balance"],
                    principal_due=row["principal_due"],
                    interest_due=row["interest_due"],
                    total_payment=row["total_payment"],
                    closing_balance=row["closing_balance"],
                )
                for row in schedule_rows
            ])

            messages.success(request, f"Loan {loan.loan_number} has been rescheduled.")
            # HTMX: return small fragment to close modal and refresh
            if request.headers.get('HX-Request') == 'true' or request.META.get('HTTP_HX_REQUEST') == 'true':
                from django.urls import reverse
                return render(request, 'loans/htmx_success.html', {
                    'message': f'Loan {loan.loan_number} has been rescheduled.',
                    'redirect': '"' + reverse('loans:detail', kwargs={'pk': loan.pk}) + '"',
                })
            return redirect("loans:detail", pk=loan.pk)

        except Exception as e:
            messages.error(request, f"Rescheduling Error: {e}")

    frequency_choices = Loan.RepaymentFrequency.choices
    context = {
        "loan": loan,
        "frequency_choices": frequency_choices,
        "default_term": loan.term_months,
        "min_term": loan.product.min_term_months,
        "max_term": loan.product.max_term_months,
        "is_reschedule": True,
        "action_title": "Reschedule Loan",
        "submit_label": "Reschedule Loan",
        "helper_text": "This creates a new repayment schedule for the existing loan.",
        "today": date.today(),
    }
    if request.headers.get('HX-Request') == 'true' or request.META.get('HTTP_HX_REQUEST') == 'true':
        return render(request, 'loans/renew_loan_fragment.html', context)
    return render(request, "loans/renew_loan.html", context)

# ------------------------------------------------------------------ #
# Loan renewal / roll-over                                              #
# ------------------------------------------------------------------ #

@_require_role("MANAGER", "CEO")
def loan_renew(request, pk):
    loan = get_object_or_404(
        Loan.objects.select_related("client", "product"),
        pk=pk,
        status=Loan.Status.ACTIVE,
    )

    if not loan.product.allows_renewal:
        messages.error(request, "This loan product does not allow renewal.")
        return redirect("loans:detail", pk=loan.pk)

    if loan.outstanding_balance <= Decimal("0"):
        messages.error(request, "This loan has no outstanding balance to renew.")
        return redirect("loans:detail", pk=loan.pk)

    if request.method == "POST":
        try:
            term_months = int(request.POST.get("term_months", loan.term_months) or loan.term_months)
            frequency = request.POST.get("frequency", loan.repayment_frequency)
            additional_amount = Decimal(request.POST.get("additional_amount", "0") or "0")
            reason = request.POST.get("reason", "").strip()

            if not reason:
                raise ValueError("Renewal reason is required.")

            if term_months < loan.product.min_term_months or term_months > loan.product.max_term_months:
                raise ValueError(
                    f"Term must be between {loan.product.min_term_months} and {loan.product.max_term_months} months."
                )

            if frequency not in dict(Loan.RepaymentFrequency.choices):
                raise ValueError("Invalid repayment frequency selected.")

            outstanding_amount = loan.outstanding_balance
            if outstanding_amount <= Decimal("0"):
                raise ValueError("Loan has no outstanding balance to renew.")

            total_new_principal = outstanding_amount + additional_amount
            if total_new_principal <= Decimal("0"):
                raise ValueError("Total new principal must be greater than zero.")

            # Allow optional disbursement_date from the form (CEOs may back-date)
            provided_disb = request.POST.get('disbursement_date', '').strip()
            if provided_disb:
                try:
                    chosen_disbursement = date.fromisoformat(provided_disb)
                except Exception:
                    raise ValueError("Invalid disbursement date format. Use YYYY-MM-DD.")
                if chosen_disbursement < date.today() and not request.user.is_ceo:
                    raise ValueError("Only the CEO may set a past disbursement date.")
            else:
                chosen_disbursement = date.today()

            schedule_rows, totals, processing_fee, _, _ = build_loan_schedule_context(
                principal=total_new_principal,
                product=loan.product,
                term_months=term_months,
                frequency=frequency,
                start_date=chosen_disbursement,
                include_processing_fee=True,
            )

            new_loan = Loan.objects.create(
                client=loan.client,
                product=loan.product,
                applied_by=request.user,
                reviewed_by=request.user,
                disbursed_by=request.user,
                application_date=date.today(),
                approval_date=date.today(),
                disbursement_date=chosen_disbursement,
                first_repayment_date=schedule_rows[0]["due_date"],
                maturity_date=schedule_rows[-1]["due_date"],
                principal_amount=total_new_principal,
                interest_rate_monthly=loan.product.interest_rate_monthly,
                interest_method=loan.product.interest_method,
                penalty_rate_monthly=loan.product.penalty_rate_monthly,
                term_months=term_months,
                repayment_frequency=frequency,
                total_repayable=totals["total_repayable_exclusive"],
                total_interest=totals["total_interest"],
                outstanding_balance=totals["total_repayable_exclusive"],
                total_fees=processing_fee,
                processing_fee=processing_fee,
                purpose=f"Renewal of {loan.loan_number}. {reason}",
                status=Loan.Status.ACTIVE,
                is_renewal=True,
                renewal_count=loan.renewal_count + 1,
                renewed_from=loan,
            )

            LoanSchedule.objects.bulk_create([
                LoanSchedule(
                    loan=new_loan,
                    period_number=row["period_number"],
                    due_date=row["due_date"],
                    opening_balance=row["opening_balance"],
                    principal_due=row["principal_due"],
                    interest_due=row["interest_due"],
                    total_payment=row["total_payment"],
                    closing_balance=row["closing_balance"],
                )
                for row in schedule_rows
            ])

            # Audit: record the disbursement date for the newly-created renewal loan
            try:
                LoanDisbursementAudit.objects.create(
                    loan=new_loan,
                    changed_by=request.user,
                    old_disbursement_date=None,
                    new_disbursement_date=new_loan.disbursement_date,
                    action='renew',
                    reason=reason[:2000],
                )
            except Exception:
                import logging
                logging.exception('Failed to create disbursement audit for new renewed loan %s', getattr(new_loan, 'pk', None))

            LoanRenewal.objects.create(
                original_loan=loan,
                new_loan=new_loan,
                outstanding_amount=outstanding_amount,
                additional_amount=additional_amount,
                total_new_principal=total_new_principal,
                reason=reason,
                approved_by=request.user,
            )

            loan.renewal_count += 1
            loan.status = Loan.Status.COMPLETED
            loan.completion_date = date.today()
            loan.save()

            messages.success(request, f"Loan renewed into new loan {new_loan.loan_number}.")
            # HTMX: return fragment instructing client to redirect/refresh
            if request.headers.get('HX-Request') == 'true' or request.META.get('HTTP_HX_REQUEST') == 'true':
                from django.urls import reverse
                return render(request, 'loans/htmx_success.html', {
                    'message': f'Loan renewed into new loan {new_loan.loan_number}.',
                    'redirect': '"' + reverse('loans:detail', kwargs={'pk': new_loan.pk}) + '"',
                })
            return redirect("loans:detail", pk=new_loan.pk)

        except Exception as e:
            messages.error(request, f"Renewal Error: {e}")

    action_mode = request.GET.get("action", "renew").lower()
    is_reschedule = action_mode == "reschedule"

    frequency_choices = Loan.RepaymentFrequency.choices
    context = {
        "loan": loan,
        "frequency_choices": frequency_choices,
        "default_term": loan.term_months,
        "min_term": loan.product.min_term_months,
        "max_term": loan.product.max_term_months,
        "is_reschedule": is_reschedule,
        "action_title": "Reschedule Loan" if is_reschedule else "Renew Loan",
        "submit_label": "Create Rescheduled Loan" if is_reschedule else "Create Renewal Loan",
        "helper_text": "This creates a new loan using the full outstanding balance as the new principal." if is_reschedule else "This creates a new loan using the outstanding balance as the new principal.",
        "today": date.today(),
    }

    # If requested via HTMX, return only the form fragment suitable for modal
    if request.headers.get('HX-Request') == 'true' or request.META.get('HTTP_HX_REQUEST') == 'true':
        return render(request, 'loans/renew_loan_fragment.html', context)

    return render(request, "loans/renew_loan.html", context)


# ------------------------------------------------------------------ #
# Approve / Reject                                                     #
# ------------------------------------------------------------------ #

@_require_role("MANAGER", "CEO")
@require_POST
def loan_approve(request, pk):
    loan = get_object_or_404(Loan, pk=pk, status=Loan.Status.PENDING)
    user = request.user

    # Limit check: managers can only approve up to UGX 5,000,000
    from django.conf import settings as django_settings
    limit = Decimal(str(getattr(django_settings, "MANAGER_APPROVAL_LIMIT", 5_000_000)))
    if user.is_manager and loan.principal_amount > limit:
        messages.error(request, f"Loans above UGX {limit:,.0f} require CEO approval.")
        return redirect("loans:detail", pk=pk)

    # Default to today; allow CEOs to override via POST disbursement_date field.
    disbursement_date = date.today()
    loan.reviewed_by = user
    loan.approval_date = date.today()

    # If a disbursement_date was provided and user is CEO, validate and apply it
    provided = request.POST.get("disbursement_date", "").strip() if request.POST else ""
    if provided:
        if not user.is_ceo:
            messages.error(request, "Only the CEO may set a custom disbursement date.")
            return redirect("loans:detail", pk=pk)
        try:
            parsed = date.fromisoformat(provided)
        except Exception:
            messages.error(request, "Invalid disbursement date format. Use YYYY-MM-DD.")
            return redirect("loans:detail", pk=pk)
        # CEOs are allowed to back-date disbursement; accept the provided date as-is
        disbursement_date = parsed

    # Capture old disbursement date for auditing
    old_disb_date = loan.disbursement_date
    loan.disbursement_date = disbursement_date

    # Product business rule: some products require at least one guarantor.
    if loan.product.requires_guarantor and not loan.guarantees.filter(is_active=True).exists():
        messages.error(request, "This loan needs at least one active guarantor before this product can be approved.")
        return redirect("loans:detail", pk=pk)

    # Ensure a schedule exists (we can regenerate below when CEO changes disbursement date)
    if not loan.schedule.exists():
        messages.error(request, "Schedule not generated yet. Re-open the loan application to generate a schedule.")
        return redirect("loans:detail", pk=pk)

    # If the disbursement date is different from the schedule's start, regenerate schedule rows so due dates align
    try:
        from .utils import build_loan_schedule_context
        # Build schedule using outstanding principal snapshot (full principal at approval time)
        schedule_rows, totals, _, _, _ = build_loan_schedule_context(
            principal=loan.principal_amount,
            product=loan.product,
            term_months=loan.term_months,
            frequency=loan.repayment_frequency,
            start_date=disbursement_date,
            include_processing_fee=False,
        )

        # Replace existing schedule with new dates/payments
        LoanSchedule.objects.filter(loan=loan).delete()
        LoanSchedule.objects.bulk_create([
            LoanSchedule(
                loan=loan,
                period_number=row["period_number"],
                due_date=row["due_date"],
                opening_balance=row["opening_balance"],
                principal_due=row["principal_due"],
                interest_due=row["interest_due"],
                total_payment=row["total_payment"],
                closing_balance=row["closing_balance"],
            )
            for row in schedule_rows
        ])

        # Update loan totals/dates from regenerated schedule
        loan.first_repayment_date = schedule_rows[0]["due_date"]
        loan.maturity_date = schedule_rows[-1]["due_date"]
        loan.total_repayable = totals.get("total_repayable", loan.total_repayable)
        loan.total_interest = totals.get("total_interest", loan.total_interest)
        loan.outstanding_balance = loan.total_repayable

    except Exception as e:
        # If regeneration fails, fall back to using existing schedule dates
        import logging
        logging.exception("Failed to regenerate schedule on approval for loan %s: %s", loan.pk, e)
        loan.first_repayment_date = loan.schedule.order_by("period_number").first().due_date
        loan.maturity_date = loan.schedule.order_by("-period_number").first().due_date
        loan.outstanding_balance = loan.total_repayable

    # Immediately activate
    loan.status = Loan.Status.ACTIVE
    loan.save()

    # Audit disbursement date change on approval
    try:
        if old_disb_date != loan.disbursement_date:
            LoanDisbursementAudit.objects.create(
                loan=loan,
                changed_by=request.user,
                old_disbursement_date=old_disb_date,
                new_disbursement_date=loan.disbursement_date,
                action='approve',
                reason='Approved and disbursed via approval form',
            )
    except Exception:
        import logging
        logging.exception('Failed to create disbursement audit for loan %s on approval', loan.pk)

    messages.success(request, f"Loan {loan.loan_number} approved and activated.")
    return redirect("loans:detail", pk=pk)


@_require_role("MANAGER", "CEO")
@require_POST
def loan_reject(request, pk):
    loan   = get_object_or_404(Loan, pk=pk, status=Loan.Status.PENDING)
    reason = request.POST.get("rejection_reason", "").strip()
    if not reason:
        messages.error(request, "A rejection reason is required.")
        return redirect("loans:detail", pk=pk)

    loan.status           = Loan.Status.REJECTED
    loan.reviewed_by      = request.user
    loan.rejection_reason = reason
    loan.save()

    messages.success(request, f"Loan {loan.loan_number} rejected.")
    return redirect("loans:detail", pk=pk)


@_require_role("CASHIER", "MANAGER", "CEO")
@require_POST
def loan_draft_delete(request, pk):
    """Permanently delete a DRAFT loan application."""
    loan = get_object_or_404(Loan, pk=pk, status=Loan.Status.DRAFT)
    if not (request.user == loan.applied_by or request.user.is_manager or request.user.is_ceo):
        messages.error(request, "You do not have permission to delete this draft.")
        return redirect("loans:detail", pk=loan.pk)
    ref = loan.loan_number
    loan.delete()
    messages.success(request, f"Draft {ref} deleted.")
    return redirect("loans:list")


@_require_role("CASHIER", "MANAGER", "CEO")
def loan_recall(request, loan_id):
    """Pull a rejected/draft loan back into edit mode."""
    loan = get_object_or_404(Loan, pk=loan_id)
    if not (request.user == loan.applied_by or request.user.is_manager or request.user.is_ceo):
        messages.error(request, "You do not have permission to recall this application.")
        return redirect("loans:detail", pk=loan.pk)
    if loan.status not in (Loan.Status.DRAFT, Loan.Status.REJECTED):
        messages.error(request, "Only draft or rejected applications can be recalled for editing.")
        return redirect("loans:detail", pk=loan.pk)
    loan.status = Loan.Status.DRAFT
    loan.rejection_reason = ""
    loan.save()
    messages.success(request, "Application recalled — you may now edit and resubmit the draft.")
    url = reverse("loans:apply_step2", kwargs={"client_id": loan.client.pk}) + f"?draft_id={loan.pk}"
    return redirect(url)


@login_required
def loan_schedule_print(request, pk):
    """Render a clean, print-ready schedule page (opens in new tab)."""
    loan = get_object_or_404(
        Loan.objects.select_related("client", "product", "applied_by", "reviewed_by"),
        pk=pk,
    )
    schedule = loan.schedule.order_by("period_number")
    return render(request, "loans/schedule_print.html", {
        "loan": loan,
        "schedule": schedule,
    })


@login_required
def loan_schedule_download(request, pk):
    """Download the repayment schedule as a PDF."""
    from django.http import HttpResponse
    from common.pdf_utils import generate_loan_schedule_pdf

    loan = get_object_or_404(Loan, pk=pk)
    pdf_bytes = generate_loan_schedule_pdf(loan)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="Schedule-{loan.loan_number}.pdf"'
    return response


@login_required
def schedule_preview_pdf(request, client_id):
    """
    Render the in-progress (draft/unsaved) loan schedule from step 2 of the
    application wizard as a PDF, using the same product/principal/term/
    frequency parameters as the live HTMX preview. Opened in a new tab so
    the user gets a real, printable PDF instead of `window.print()`-ing
    the whole page.
    """
    from django.http import HttpResponse, HttpResponseBadRequest

    from .utils import generate_schedule_preview_pdf

    client = get_object_or_404(Client, pk=client_id, is_active=True, is_blacklisted=False)

    try:
        product_id  = int(request.GET.get("product", 0))
        principal   = Decimal(str(request.GET.get("principal", "0") or "0"))
        term_months = int(request.GET.get("term_months", 0) or 0)
        frequency   = request.GET.get("frequency", "") or Loan.RepaymentFrequency.MONTHLY

        product = get_object_or_404(LoanProduct, pk=product_id, is_active=True)

        if principal <= 0 or term_months <= 0:
            return HttpResponseBadRequest(
                "Select a product and enter a valid loan amount and term before printing the schedule."
            )

        # Mirror the calculation used to render the on-screen preview in
        # loan_apply_step2 so the PDF always matches what the user sees.
        schedule_rows, totals, fee_amount, _, fee_source = build_loan_schedule_context(
            principal=principal,
            product=product,
            term_months=term_months,
            frequency=frequency,
            start_date=date.today(),
            include_processing_fee=True,
        )

        pdf_bytes = generate_schedule_preview_pdf(
            client=client,
            product=product,
            principal=principal,
            term_months=term_months,
            frequency=frequency,
            schedule_rows=schedule_rows,
            totals=totals,
            processing_fee=fee_amount,
            fee_source=fee_source,
        )
    except (ValueError, TypeError):
        return HttpResponseBadRequest(
            "Enter valid loan details above before printing the schedule."
        )

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="Schedule-Preview-{client.client_number}.pdf"'
    return response


# ------------------------------------------------------------------ #
# HTMX: live schedule preview                                          #
# ------------------------------------------------------------------ #

@login_required
def schedule_preview(request):
    """
    Called via HTMX when the user changes loan parameters.
    Returns only the schedule table partial.
    """
    try:
        product_id  = int(request.GET.get("product", 0))
        principal   = Decimal(str(request.GET.get("principal", "0") or "0"))
        term_months = int(request.GET.get("term_months", 1) or 1)
        frequency   = request.GET.get("frequency", "MONTHLY")

        product = LoanProduct.objects.get(pk=product_id, is_active=True)
        schedule_rows, totals = generate_schedule(
            principal   = principal,
            annual_rate = product.interest_rate_monthly * 12,
            term_months = term_months,
            start_date  = date.today(),
            method      = product.interest_method,
            frequency   = frequency,
        )
        processing_fee = None
        processing_fee_percent = None
        processing_fee_rate_text = None
        fee_source = None

        # Prefer tiered office charge if available
        if product:
            processing_fee = calculate_processing_fee_amount(principal, product=product)
            processing_fee_percent = resolve_processing_fee_rate(product)
            fee_source = "Company settings (range)" if (processing_fee and not processing_fee_percent) else (product.name if processing_fee_percent else "Company settings")
            processing_fee_rate_text = f"{processing_fee_percent}%" if processing_fee_percent else ("Fixed range" if processing_fee else "")

        return render(request, "partials/schedule_table.html", {
            "schedule_rows": schedule_rows,
            "totals":        totals,
            "principal":     principal,
            "processing_fee": processing_fee,
            "processing_fee_percent": processing_fee_percent,
            "processing_fee_rate_text": processing_fee_rate_text,
            "fee_source": fee_source,
        })
    except Exception:
        return render(request, "partials/schedule_table.html", {
            "schedule_rows": [],
            "totals":        {},
            "processing_fee": None,
            "processing_fee_percent": None,
            "fee_source": None,
            "error":         "Enter valid loan details above to preview the schedule.",
        })


# ------------------------------------------------------------------ #
# Extend a schedule entry due date
# ------------------------------------------------------------------ #


@_require_role("MANAGER", "CEO")
@require_POST
def schedule_extend(request, pk):
    """
    POST endpoint to extend a LoanSchedule.due_date with a required reason.
    Expects `new_due_date` (YYYY-MM-DD) and `reason` in POST data.
    """
    try:
        entry = get_object_or_404(LoanSchedule, pk=pk)
        new_due = request.POST.get("new_due_date", "").strip()
        reason = request.POST.get("reason", "").strip()
        if not new_due or not reason:
            messages.error(request, "New due date and reason are required to extend a schedule entry.")
            return redirect("loans:detail", pk=entry.loan.pk)

        # parse date
        try:
            new_date = date.fromisoformat(new_due)
        except Exception:
            messages.error(request, "Invalid date format. Use YYYY-MM-DD.")
            return redirect("loans:detail", pk=entry.loan.pk)

        # record extension
        from .models import LoanScheduleExtension

        extension = LoanScheduleExtension.objects.create(
            schedule_entry = entry,
            old_due_date = entry.due_date,
            new_due_date = new_date,
            reason = reason,
            extended_by = request.user,
        )

        # apply change to schedule entry
        entry.due_date = new_date
        entry.save()

        messages.success(request, f"Schedule entry period {entry.period_number} extended to {new_date}.")
        return redirect("loans:detail", pk=entry.loan.pk)

    except Exception as e:
        messages.error(request, f"Could not extend schedule entry: {e}")
        return redirect("loans:detail", pk=entry.loan.pk)


# ------------------------------------------------------------------ #
# Loan products CRUD (CEO configuration)                             #
# ------------------------------------------------------------------ #


@login_required
def loan_product_list(request):
    """
    List loan products.
    CEO can manage them; other roles typically view active products.
    """
    qs = LoanProduct.objects.all().order_by("name")

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(name__icontains=q)

    status = request.GET.get("status", "")
    if status == "active":
        qs = qs.filter(is_active=True)
    elif status == "inactive":
        qs = qs.filter(is_active=False)

    # Default for non-CEO users: show active only.
    if not request.user.is_ceo and not status:
        qs = qs.filter(is_active=True)

    return render(
        request,
        "loans/product_list.html",
        {
            "products": qs,
            "q": q,
            "status": status,
            "is_ceo": request.user.is_ceo,
        },
    )


@_require_role("CEO")
def loan_product_create(request):
    if request.method == "POST":
        d = request.POST
        try:
            product = LoanProduct(
                name=d["name"].strip(),
                description=d.get("description", "").strip(),
                interest_rate_monthly=Decimal(d["interest_rate_monthly"]),
                interest_method=d["interest_method"],
                default_repayment_frequency=d["default_repayment_frequency"],
                min_amount=Decimal(d["min_amount"]),
                max_amount=Decimal(d["max_amount"]),
                min_term_months=int(d["min_term_months"]),
                max_term_months=int(d["max_term_months"]),
                penalty_rate_monthly=Decimal(d["penalty_rate_monthly"]),
                processing_fee_percent=Decimal(d.get("processing_fee_percent") or "0"),
                requires_guarantor=(d.get("requires_guarantor") == "on"),
                is_active=(d.get("is_active") == "on"),
                created_by=request.user,
            )

            product.full_clean()
            product.save()

            messages.success(request, f"Loan product '{product.name}' created.")
            return redirect("loans:products")
        except Exception as e:
            messages.error(request, f"Could not create product: {e}")

    return render(
        request,
        "loans/product_form.html",
        {
            "title": "Create Loan Product",
            "action": "create",
            "product": None,
            "product_form_defaults": {},
            "interest_method_choices": LoanProduct.InterestMethod.choices,
            "frequency_choices": LoanProduct.RepaymentFrequency.choices,
        },
    )


@_require_role("CEO")
def loan_product_edit(request, pk: int):
    product = get_object_or_404(LoanProduct, pk=pk)

    if request.method == "POST":
        d = request.POST
        try:
            product.name = d["name"].strip()
            product.description = d.get("description", "").strip()
            product.interest_rate_monthly = Decimal(d["interest_rate_monthly"])
            product.interest_method = d["interest_method"]
            product.default_repayment_frequency = d["default_repayment_frequency"]
            product.min_amount = Decimal(d["min_amount"])
            product.max_amount = Decimal(d["max_amount"])
            product.min_term_months = int(d["min_term_months"])
            product.max_term_months = int(d["max_term_months"])
            product.penalty_rate_monthly = Decimal(d["penalty_rate_monthly"])
            product.processing_fee_percent = Decimal(d.get("processing_fee_percent") or "0")
            product.requires_guarantor = (d.get("requires_guarantor") == "on")
            product.is_active = (d.get("is_active") == "on")
            product.full_clean()
            product.save()

            messages.success(request, f"Loan product '{product.name}' updated.")
            return redirect("loans:products")
        except Exception as e:
            messages.error(request, f"Could not update product: {e}")

    return render(
        request,
        "loans/product_form.html",
        {
            "title": f"Edit Loan Product — {product.name}",
            "action": "edit",
            "product": product,
            "product_form_defaults": {
                "name": product.name,
                "description": product.description,
                "interest_rate_monthly": product.interest_rate_monthly,
                "interest_method": product.interest_method,
                "default_repayment_frequency": product.default_repayment_frequency,
                "min_amount": product.min_amount,
                "max_amount": product.max_amount,
                "min_term_months": product.min_term_months,
                "max_term_months": product.max_term_months,
                "penalty_rate_monthly": product.penalty_rate_monthly,
                "processing_fee_percent": product.processing_fee_percent,
                "requires_guarantor": product.requires_guarantor,
                "is_active": product.is_active,
            },
            "interest_method_choices": LoanProduct.InterestMethod.choices,
            "frequency_choices": LoanProduct.RepaymentFrequency.choices,
        },
    )