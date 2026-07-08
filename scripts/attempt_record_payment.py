import os,sys,traceback
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from decimal import Decimal
from datetime import date
from django.contrib.auth import get_user_model
from loans.models import Loan, LoanSchedule
from payments.models import Payment, Receipt

try:
    loan = Loan.objects.filter(loan_number__icontains='LN-2026-00003').select_related('client').first()
    if not loan:
        loan = Loan.objects.filter(client__last_name__icontains='ONYANGO').select_related('client').first()
    print('Found loan:', loan)
    user = get_user_model().objects.filter(is_staff=True).first()
    print('Using user:', user)
    amount = Decimal('1000')
    pay_date = date.today()

    # Snapshot balance
    balance_before = loan.outstanding_balance

    payment = Payment.objects.create(
        loan=loan,
        client=loan.client,
        recorded_by=user,
        amount_received=amount,
        payment_method='CASH',
        reference_number='SCRIPT_TEST',
        payment_date=pay_date,
        status=Payment.Status.PENDING,
    )
    remaining = amount
    interest_paid = Decimal('0')
    principal_paid = Decimal('0')
    penalty_paid = Decimal('0')

    pending = LoanSchedule.objects.filter(loan=loan, status__in=['PENDING','OVERDUE','PARTIAL']).order_by('period_number')
    print('Pending schedule count:', pending.count())
    for entry in pending:
        if remaining <= 0:
            break
        amount_due = entry.total_payment + entry.penalty_due - entry.amount_paid
        print('Entry', entry.period_number, 'amount_due', amount_due, 'entry.amount_paid', entry.amount_paid)
        if remaining >= amount_due:
            interest_paid += entry.interest_due
            principal_paid += entry.principal_due
            penalty_paid += entry.penalty_due
            remaining -= amount_due
            entry.amount_paid = entry.total_payment + entry.penalty_due
            entry.status = LoanSchedule.Status.PAID
            entry.paid_date = pay_date
        else:
            allocated = remaining
            if remaining >= entry.penalty_due:
                penalty_paid += entry.penalty_due
                remaining -= entry.penalty_due
            else:
                penalty_paid += remaining
                remaining = Decimal('0')
            if remaining >= entry.interest_due:
                interest_paid += entry.interest_due
                remaining -= entry.interest_due
            else:
                interest_paid += remaining
                remaining = Decimal('0')
            principal_paid += remaining
            remaining = Decimal('0')
            entry.amount_paid += allocated
            entry.status = LoanSchedule.Status.PARTIAL
        entry.save()

    overpayment = max(remaining, Decimal('0'))
    payment.principal_paid = principal_paid
    payment.interest_paid = interest_paid
    payment.penalty_paid = penalty_paid
    payment.overpayment = overpayment
    payment.status = Payment.Status.ALLOCATED
    payment.save()

    loan.total_paid += amount - overpayment
    loan.outstanding_balance = max(loan.outstanding_balance - (amount - overpayment), Decimal('0'))
    if loan.outstanding_balance == 0:
        loan.status = Loan.Status.COMPLETED
        loan.completion_date = pay_date
    loan.save()

    receipt = Receipt.objects.create(
        payment=payment,
        balance_before=balance_before,
        balance_after=loan.outstanding_balance,
        amount_received=payment.amount_received,
        principal_paid=payment.principal_paid,
        interest_paid=payment.interest_paid,
        penalty_paid=payment.penalty_paid,
        overpayment=payment.overpayment,
    )
    print('Payment created:', payment.pk)
    print('Receipt created:', receipt.receipt_number)

except Exception as e:
    print('EXCEPTION', type(e), e)
    traceback.print_exc()
    sys.exit(1)
