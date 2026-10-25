from decimal import Decimal

from django.db.models import Sum

from .branch_scope import scope_to_branch


ZERO = Decimal("0")

# Loans whose principal has actually left the till. Must match the set used by
# reports.views (cash-flow / disbursements) so dashboard and reports agree.
DISBURSED_STATUSES = ["ACTIVE", "COMPLETED", "DEFAULTED", "WRITTEN_OFF", "RESTRUCTURED"]


def cash_movement(*, user=None, branch_id=None, start_date=None, end_date=None, opening_balance=ZERO):
    """Return physical-cash movement and balance for the selected scope."""
    from .models import CapitalInjection, Expense
    from loans.models import Loan
    from payments.models import Payment

    # cash_receipts() excludes internal CREDIT_TRANSFER rows, which move no new cash.
    payments = Payment.objects.cash_receipts().filter(
        status=Payment.Status.ALLOCATED,
        payment_method=Payment.PaymentMethod.CASH,
    )
    disbursements = Loan.objects.filter(
        disbursement_date__isnull=False, status__in=DISBURSED_STATUSES,
    )
    expenses = Expense.objects.filter(
        status=Expense.Status.APPROVED,
        payment_method=Expense.PaymentMethod.CASH,
    )
    injections = CapitalInjection.objects.filter(
        payment_method=CapitalInjection.PaymentMethod.CASH,
    )

    if start_date is not None:
        payments = payments.filter(payment_date__gte=start_date)
        disbursements = disbursements.filter(disbursement_date__gte=start_date)
        expenses = expenses.filter(expense_date__gte=start_date)
        injections = injections.filter(injected_date__gte=start_date)
    if end_date is not None:
        payments = payments.filter(payment_date__lte=end_date)
        disbursements = disbursements.filter(disbursement_date__lte=end_date)
        expenses = expenses.filter(expense_date__lte=end_date)
        injections = injections.filter(injected_date__lte=end_date)

    if branch_id is not None:
        payments = payments.filter(loan__branch_id=branch_id)
        disbursements = disbursements.filter(branch_id=branch_id)
        expenses = expenses.filter(branch_id=branch_id)
        injections = injections.filter(branch_id=branch_id)
    elif user is not None:
        payments = scope_to_branch(payments, user, "loan__branch")
        disbursements = scope_to_branch(disbursements, user)
        expenses = scope_to_branch(expenses, user)
        injections = scope_to_branch(injections, user)

    payment_total = payments.aggregate(total=Sum("amount_received"))["total"] or ZERO
    injection_total = injections.aggregate(total=Sum("amount"))["total"] or ZERO
    disbursement_total = disbursements.aggregate(total=Sum("principal_amount"))["total"] or ZERO
    expense_total = expenses.aggregate(total=Sum("amount"))["total"] or ZERO
    # Processing fees are collected in cash at disbursement (as in the cash-flow report).
    fee_total = sum((l.effective_processing_fee for l in disbursements.select_related("product")), ZERO)
    cash_in = payment_total + injection_total + fee_total
    cash_out = disbursement_total + expense_total

    return {
        "payments": payment_total,
        "injections": injection_total,
        "processing_fees": fee_total,
        "disbursements": disbursement_total,
        "expenses": expense_total,
        "cash_in": cash_in,
        "cash_out": cash_out,
        "cash_at_hand": opening_balance + cash_in - cash_out,
    }


def recent_cash_transactions(
    *, user=None, branch_id=None, limit=6, include_owner_entries=True,
    start_date=None, end_date=None,
):
    """Return the latest physical-cash movements for a dashboard preview.

    include_owner_entries=False drops capital injections and expenses, which
    are owner-level figures that cashiers should not see. Pass False for
    cashier views.
    """
    from .models import CapitalInjection, Expense
    from loans.models import Loan
    from payments.models import Payment

    # Filter first, then slice each queryset to `limit` so the database returns
    # at most `limit` rows per table instead of the full history.
    payments = Payment.objects.cash_receipts().filter(
        status=Payment.Status.ALLOCATED,
        payment_method=Payment.PaymentMethod.CASH,
    ).select_related("client").order_by("-created_at")
    disbursements = Loan.objects.filter(
        disbursement_date__isnull=False, status__in=DISBURSED_STATUSES,
    ).select_related("client", "product").order_by("-created_at")
    expenses = Expense.objects.filter(
        status=Expense.Status.APPROVED,
        payment_method=Expense.PaymentMethod.CASH,
    ).select_related("expense_type", "category").order_by("-created_at")
    injections = CapitalInjection.objects.filter(
        payment_method=CapitalInjection.PaymentMethod.CASH,
    ).order_by("-created_at")

    if start_date is not None:
        payments = payments.filter(payment_date__gte=start_date)
        disbursements = disbursements.filter(disbursement_date__gte=start_date)
        expenses = expenses.filter(expense_date__gte=start_date)
        injections = injections.filter(injected_date__gte=start_date)
    if end_date is not None:
        payments = payments.filter(payment_date__lte=end_date)
        disbursements = disbursements.filter(disbursement_date__lte=end_date)
        expenses = expenses.filter(expense_date__lte=end_date)
        injections = injections.filter(injected_date__lte=end_date)

    if branch_id is not None:
        payments = payments.filter(loan__branch_id=branch_id)
        disbursements = disbursements.filter(branch_id=branch_id)
        expenses = expenses.filter(branch_id=branch_id)
        injections = injections.filter(branch_id=branch_id)
    elif user is not None:
        payments = scope_to_branch(payments, user, "loan__branch")
        disbursements = scope_to_branch(disbursements, user)
        expenses = scope_to_branch(expenses, user)
        injections = scope_to_branch(injections, user)

    payments = list(payments[:limit])
    disbursements = list(disbursements[:limit])
    if include_owner_entries:
        expenses = list(expenses[:limit])
        injections = list(injections[:limit])
    else:
        expenses = []
        injections = []

    transactions = [
        {
            "date": payment.payment_date,
            "timestamp": payment.created_at,
            "type": "Payment",
            "description": f"Repayment from {payment.client.full_name}",
            "amount": payment.amount_received,
            "direction": "in",
        }
        for payment in payments
    ]
    transactions += [
        {
            "date": loan.disbursement_date,
            "timestamp": loan.created_at,
            "type": "Disbursement",
            "description": f"Loan to {loan.client.full_name}",
            "amount": loan.principal_amount,
            "direction": "out",
        }
        for loan in disbursements
    ]
    transactions += [
        {
            "date": loan.disbursement_date,
            "timestamp": loan.created_at,
            "type": "Processing Fee",
            "description": f"Fee from {loan.client.full_name}",
            "amount": loan.effective_processing_fee,
            "direction": "in",
        }
        for loan in disbursements
        if loan.effective_processing_fee
    ]
    transactions += [
        {
            "date": expense.expense_date,
            "timestamp": expense.created_at,
            "type": "Expense",
            "description": expense.expense_type.name if expense.expense_type else (expense.category.name if expense.category else "Expense"),
            "amount": expense.amount,
            "direction": "out",
        }
        for expense in expenses
    ]
    transactions += [
        {
            "date": injection.injected_date,
            "timestamp": injection.created_at,
            "type": "Injection",
            "description": f"From {injection.source}",
            "amount": injection.amount,
            "direction": "in",
        }
        for injection in injections
    ]
    transactions.sort(key=lambda transaction: transaction["timestamp"], reverse=True)
    return transactions[:limit]