"""
payments/views.py
=================
Payment recording and receipt generation for ABA Uganda.
"""

from decimal import Decimal
from datetime import date
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from loans.models import Loan, LoanSchedule
from accounts.models import AuditLog
from accounts.audit import log_action
from common.pdf_utils import render_pdf_response
from clients.models import CreditTransaction
from .models import Payment, Receipt

logger = logging.getLogger("payments")


@login_required
def payment_list(request):
    # Handle modal form POST submitted from the list page
    if request.method == "POST" and request.POST.get("_from_list"):
        return record_payment(request)

    qs = Payment.objects.select_related("loan__client", "recorded_by").order_by("-payment_date")
    if request.user.is_cashier:
        qs = qs.filter(recorded_by=request.user)

    search = request.GET.get("q", "").strip()
    if search:
        qs = qs.filter(loan__loan_number__icontains=search) | \
             qs.filter(loan__client__last_name__icontains=search)

    active_loans = Loan.objects.filter(status="ACTIVE").select_related("client").order_by("client__last_name")
    return render(request, "payments/payment_list.html", {
        "payments": qs[:100],
        "search": search,
        "active_loans": active_loans,
        "today": date.today(),
    })


@login_required
def record_payment(request, loan_pk=None):
    """Record a repayment from a client."""
    loan = None
    if loan_pk:
        loan = get_object_or_404(Loan, pk=loan_pk, status=Loan.Status.ACTIVE)

    active_loans = Loan.objects.filter(status="ACTIVE").select_related("client").order_by("client__last_name")
    selected_loan = None

    if request.method == "POST":
        try:
            loan_id     = request.POST.get("loan_id") or loan_pk

            # Validate loan selection
            if not loan_id:
                raise ValueError("Please select a loan.")

            selected_loan = get_object_or_404(Loan, pk=loan_id, status=Loan.Status.ACTIVE)

            amount_str  = request.POST.get("amount", "0").strip()
            method      = request.POST.get("payment_method", "CASH")
            reference   = request.POST.get("reference_number", "")
            pay_date_str= request.POST.get("payment_date", str(date.today()))

            # Validate and convert amount
            if not amount_str:
                raise ValueError("Payment amount is required.")

            try:
                amount = Decimal(amount_str)
            except Exception:
                raise ValueError(f"Invalid amount format: '{amount_str}'. Please enter a valid number.")

            if amount < 0:
                raise ValueError("Payment amount cannot be negative.")

            if amount == 0:
                raise ValueError("Payment amount must be greater than zero.")

            try:
                pay_date = date.fromisoformat(pay_date_str)
            except Exception:
                raise ValueError(f"Invalid date format: '{pay_date_str}'.")

            selected_loan = get_object_or_404(Loan, pk=loan_id, status=Loan.Status.ACTIVE)

            # Snapshot balance before payment
            balance_before = selected_loan.outstanding_balance

            # prepare transfer variables
            transfer_payment = None
            transfer_receipt = None

            with transaction.atomic():
                client = selected_loan.client

                # Optional: transfer existing client credit to another loan before applying it to this payment
                transfer_target_id = request.POST.get('transfer_target_loan')
                transfer_amount_str = request.POST.get('transfer_amount', '').strip()
                transfer_payment = None
                transfer_receipt = None
                if transfer_target_id:
                    try:
                        target_loan = get_object_or_404(Loan, pk=transfer_target_id, status=Loan.Status.ACTIVE, client=client)
                        credit_available = client.credit_balance
                        if transfer_amount_str:
                            transfer_amount = Decimal(transfer_amount_str)
                        else:
                            transfer_amount = credit_available
                        transfer_amount = max(Decimal('0'), min(transfer_amount, credit_available))
                        if transfer_amount > 0:
                            # Allocate the transferred credit to the target loan's pending schedule entries
                            remaining_transfer = transfer_amount
                            t_interest_paid = Decimal('0')
                            t_principal_paid = Decimal('0')
                            t_penalty_paid = Decimal('0')

                            target_pending = LoanSchedule.objects.filter(
                                loan=target_loan,
                                status__in=["PENDING", "OVERDUE", "PARTIAL"],
                            ).order_by('period_number')

                            for t_entry in target_pending:
                                if remaining_transfer <= 0:
                                    break
                                t_amount_due = t_entry.total_payment + t_entry.penalty_due - t_entry.amount_paid
                                if remaining_transfer >= t_amount_due:
                                    t_interest_paid += t_entry.interest_due
                                    t_principal_paid += t_entry.principal_due
                                    t_penalty_paid += t_entry.penalty_due
                                    remaining_transfer -= t_amount_due
                                    t_entry.amount_paid = t_entry.total_payment + t_entry.penalty_due
                                    t_entry.status = LoanSchedule.Status.PAID
                                    t_entry.paid_date = pay_date
                                else:
                                    allocated = remaining_transfer
                                    if remaining_transfer >= t_entry.penalty_due:
                                        t_penalty_paid += t_entry.penalty_due
                                        remaining_transfer -= t_entry.penalty_due
                                    else:
                                        t_penalty_paid += remaining_transfer
                                        remaining_transfer = Decimal('0')
                                    if remaining_transfer >= t_entry.interest_due:
                                        t_interest_paid += t_entry.interest_due
                                        remaining_transfer -= t_entry.interest_due
                                    else:
                                        t_interest_paid += remaining_transfer
                                        remaining_transfer = Decimal('0')
                                    t_principal_paid += remaining_transfer
                                    remaining_transfer = Decimal('0')
                                    t_entry.amount_paid += allocated
                                    t_entry.status = LoanSchedule.Status.PARTIAL
                                t_entry.save()

                            applied = transfer_amount - remaining_transfer
                            # Update target loan totals
                            target_balance_before = target_loan.outstanding_balance
                            target_loan.total_paid += applied
                            target_loan.outstanding_balance = max(target_loan.outstanding_balance - applied, Decimal('0'))
                            if target_loan.outstanding_balance == 0:
                                target_loan.status = Loan.Status.COMPLETED
                                target_loan.completion_date = pay_date
                            target_loan.save()

                            if applied > 0:
                                try:
                                    # create transfer payment & receipt for audit
                                    transfer_payment = Payment.objects.create(
                                        loan=target_loan,
                                        client=client,
                                        recorded_by=request.user,
                                        amount_received=applied,
                                        principal_paid=t_principal_paid,
                                        interest_paid=t_interest_paid,
                                        penalty_paid=t_penalty_paid,
                                        overpayment=Decimal('0'),
                                        payment_method=Payment.PaymentMethod.OTHER,
                                        reference_number=f"CREDIT_TRANSFER:{request.user.pk}",
                                        payment_date=pay_date,
                                        status=Payment.Status.ALLOCATED,
                                    )

                                    transfer_receipt = Receipt.objects.create(
                                        payment=transfer_payment,
                                        balance_before=target_balance_before,
                                        balance_after=target_loan.outstanding_balance,
                                        amount_received=transfer_payment.amount_received,
                                        principal_paid=transfer_payment.principal_paid,
                                        interest_paid=transfer_payment.interest_paid,
                                        penalty_paid=transfer_payment.penalty_paid,
                                        overpayment=transfer_payment.overpayment,
                                    )

                                    # adjust client credit balance and ledger
                                    client.credit_balance = credit_available - applied
                                    client.save(update_fields=['credit_balance'])

                                    CreditTransaction.objects.create(
                                        client=client,
                                        tx_type=CreditTransaction.TxType.APPLIED,
                                        amount=-applied,
                                        balance_after=client.credit_balance,
                                        loan=target_loan,
                                        payment=transfer_payment,
                                        created_by=request.user,
                                        notes=f"Transferred to loan {target_loan.loan_number} by {request.user.get_full_name()}",
                                    )
                                except Exception:
                                    # If anything in recording transfer records fails, log but continue the main flow
                                    logger.exception("Failed to record transfer payment/receipt for client=%s target=%s", client, target_loan.pk)
                    except Exception:
                        # Fail softly: do not block the main payment flow for transfer errors
                        logger.exception("Credit transfer failed for client=%s target=%s", client, transfer_target_id)

                # After optional transfer, auto-apply remaining client credit to this payment
                credit_before = client.credit_balance
                credit_to_use = min(credit_before, amount)
                if credit_to_use > 0:
                    client.credit_balance = max(Decimal("0"), credit_before - credit_to_use)
                    client.save(update_fields=["credit_balance"])
                    CreditTransaction.objects.create(
                        client=client,
                        tx_type=CreditTransaction.TxType.APPLIED,
                        amount=-credit_to_use,
                        balance_after=client.credit_balance,
                        loan=selected_loan,
                        created_by=request.user,
                        notes=f"Applied to payment on {pay_date}",
                    )

                amount_to_apply = amount - credit_to_use

                # Create the payment record
                payment = Payment.objects.create(
                    loan             = selected_loan,
                    client           = selected_loan.client,
                    recorded_by      = request.user,
                    amount_received  = amount,
                    payment_method   = method,
                    reference_number = reference,
                    payment_date     = pay_date,
                    status           = Payment.Status.PENDING,
                )

                # Allocate payment to schedule entries
                remaining = amount_to_apply
                interest_paid   = Decimal("0")
                principal_paid  = Decimal("0")
                penalty_paid    = Decimal("0")

                pending_entries = LoanSchedule.objects.filter(
                    loan=selected_loan,
                    status__in=["PENDING", "OVERDUE", "PARTIAL"],
                ).order_by("period_number")

                for entry in pending_entries:
                    if remaining <= 0:
                        break

                    amount_due = entry.total_payment + entry.penalty_due - entry.amount_paid

                    if remaining >= amount_due:
                        # Full payment of this entry
                        interest_paid  += entry.interest_due
                        principal_paid += entry.principal_due
                        penalty_paid   += entry.penalty_due
                        remaining      -= amount_due
                        entry.amount_paid = entry.total_payment + entry.penalty_due
                        entry.status   = LoanSchedule.Status.PAID
                        entry.paid_date = pay_date
                    else:
                        # Partial payment — allocate: penalty first, then interest, then principal
                        allocated = remaining
                        if remaining >= entry.penalty_due:
                            penalty_paid += entry.penalty_due
                            remaining    -= entry.penalty_due
                        else:
                            penalty_paid += remaining
                            remaining     = Decimal("0")
                        if remaining >= entry.interest_due:
                            interest_paid += entry.interest_due
                            remaining     -= entry.interest_due
                        else:
                            interest_paid += remaining
                            remaining      = Decimal("0")
                        principal_paid += remaining
                        remaining       = Decimal("0")
                        entry.amount_paid += allocated
                        entry.status = LoanSchedule.Status.PARTIAL

                    entry.save()

                # Handle overpayment
                overpayment = max(remaining, Decimal("0"))

                # Update payment allocation breakdown
                payment.principal_paid  = principal_paid
                payment.interest_paid   = interest_paid
                payment.penalty_paid    = penalty_paid
                payment.overpayment     = overpayment
                payment.status          = Payment.Status.ALLOCATED
                payment.save()

                net_applied = amount_to_apply - overpayment

                if overpayment > 0:
                    client.credit_balance += overpayment
                    client.save(update_fields=["credit_balance"])
                    CreditTransaction.objects.create(
                        client=client,
                        tx_type=CreditTransaction.TxType.OVERPAYMENT,
                        amount=overpayment,
                        balance_after=client.credit_balance,
                        loan=selected_loan,
                        payment=payment,
                        created_by=request.user,
                        notes=f"Overpayment on {pay_date}",
                    )

                # Update loan totals
                selected_loan.total_paid        += net_applied
                selected_loan.outstanding_balance = max(
                    selected_loan.outstanding_balance - net_applied, Decimal("0")
                )
                if selected_loan.outstanding_balance == 0:
                    selected_loan.status          = Loan.Status.COMPLETED
                    selected_loan.completion_date = pay_date
                selected_loan.save()

                    # Create receipt (snapshot allocation values so receipt remains accurate)
                receipt = Receipt.objects.create(
                    payment        = payment,
                    balance_before = balance_before,
                    balance_after  = selected_loan.outstanding_balance,
                    amount_received = payment.amount_received,
                    principal_paid  = payment.principal_paid,
                    interest_paid   = payment.interest_paid,
                    penalty_paid    = payment.penalty_paid,
                    overpayment     = payment.overpayment,
                )

            credit_note = f" and UGX {overpayment:,.0f} stored as client credit" if overpayment > 0 else ""
            messages.success(request, f"Payment of UGX {amount:,.0f} recorded{credit_note}. Receipt: {receipt.receipt_number}")

            log_action(request.user, AuditLog.Action.PAYMENT, payment, request=request,
                       changes={"amount": str(amount), "loan": selected_loan.loan_number,
                                "principal": str(principal_paid), "interest": str(interest_paid),
                                "penalty": str(penalty_paid), "receipt": receipt.receipt_number},
                       remarks=f"Payment recorded by {request.user.full_name}")

            # If a transfer occurred and produced a transfer_receipt, render a combined receipt view
            try:
                if transfer_receipt is not None:
                    # Render combined receipts for printing/viewing
                    return render(request, "payments/combined_receipt.html", {
                        "receipts": [transfer_receipt, receipt],
                        "auto_print": True,
                    })
            except Exception:
                # If something goes wrong rendering combined receipts, fall back to single receipt redirect
                logger.exception("Failed to render combined receipt for payment=%s", payment.pk)

            return redirect("payments:receipt", pk=receipt.pk)

        except ValueError as e:
            messages.error(request, f"Payment Error: {str(e)}")
        except TypeError as e:
            messages.error(request, f"Invalid input: {str(e)}")
        except Exception as e:
            logger.exception(
                "Payment recording failed for loan=%s user=%s amount=%s",
                loan_id,
                request.user,
                request.POST.get("amount", ""),
            )
            messages.error(request, "Unexpected server error while recording payment. The issue has been logged.")

        # If submitted from the list-page modal, re-render the list with the modal open
        if request.POST.get("_from_list"):
            qs = Payment.objects.select_related("loan__client", "recorded_by").order_by("-payment_date")
            if request.user.is_cashier:
                qs = qs.filter(recorded_by=request.user)
            active_loans = Loan.objects.filter(status="ACTIVE").select_related("client").order_by("client__last_name")
            return render(request, "payments/payment_list.html", {
                "payments": qs[:100],
                "search": "",
                "active_loans": active_loans,
                "today": date.today(),
                "selected_loan_id": request.POST.get("loan_id", ""),
                "posted_amount": request.POST.get("amount", ""),
            })

    # Prepare client other loans list for the transfer UI (only when a loan is selected)
    client_other_loans = []
    if selected_loan or loan:
        l = selected_loan or loan
        try:
            client_other_loans = l.client.loans.filter(status=Loan.Status.ACTIVE).exclude(pk=l.pk).select_related('product').order_by('created_at')
        except Exception:
            client_other_loans = []

    return render(request, "payments/record_payment.html", {
        "loan":         selected_loan or loan,
        "active_loans": active_loans,
        "today":        date.today(),
        "client_other_loans": client_other_loans,
    })


@login_required
def receipt_view(request, pk):
    receipt = get_object_or_404(
        Receipt.objects.select_related(
            "payment__loan__client",
            "payment__loan__product",
            "payment__recorded_by",
        ),
        pk=pk,
    )
    loan = receipt.payment.loan
    guarantees = loan.guarantees.select_related('guarantor').all()
    collateral_items = loan.collateral_items.all()
    context = {
        "receipt": receipt,
        "guarantees": guarantees,
        "collateral_items": collateral_items,
    }
    if request.GET.get("format") == "pdf":
        filename = f"Receipt-{receipt.receipt_number}.pdf"
        return render_pdf_response(request, "payments/receipt.html", context, filename=filename)
    return render(request, "payments/receipt.html", context)


@login_required
def payment_history(request, loan_pk):
    loan     = get_object_or_404(Loan, pk=loan_pk)
    payments = Payment.objects.filter(loan=loan).select_related("recorded_by").order_by("-payment_date")
    return render(request, "payments/payment_history.html", {"loan": loan, "payments": payments})

@login_required
def credit_refund(request, client_pk):
    """Manager/CEO refund a client's credit balance (cash payout of stored credit)."""
    from clients.models import Client

    if request.user.is_cashier:
        messages.error(request, "Only Managers and CEO can process refunds.")
        return redirect("clients:detail", pk=client_pk)

    client = get_object_or_404(Client, pk=client_pk)

    if request.method == "POST":
        try:
            amount = Decimal(request.POST.get("amount", "0").strip())
            if amount <= 0:
                raise ValueError("Refund amount must be greater than zero.")
            if amount > client.credit_balance:
                raise ValueError(
                    f"Refund amount UGX {amount:,.0f} exceeds credit balance UGX {client.credit_balance:,.0f}."
                )
            notes = request.POST.get("notes", "").strip()
            with transaction.atomic():
                client.credit_balance -= amount
                client.save(update_fields=["credit_balance"])
                CreditTransaction.objects.create(
                    client=client,
                    tx_type=CreditTransaction.TxType.REFUNDED,
                    amount=-amount,
                    balance_after=client.credit_balance,
                    created_by=request.user,
                    notes=notes or f"Cash refund authorised by {request.user.full_name}",
                )
            messages.success(
                request,
                f"UGX {amount:,.0f} refunded to {client.full_name}. Remaining credit: UGX {client.credit_balance:,.0f}.",
            )
        except ValueError as e:
            messages.error(request, str(e))
        return redirect("clients:detail", pk=client_pk)

    return render(request, "payments/credit_refund.html", {"client": client})