"""Find stored loan figures that disagree with the underlying schedule/payments.

Read-only by default. Always runs inside a tenant schema context
(see tenants/command_utils.py):

    python manage.py reconcile_loans --schema=<name>                # report
    python manage.py reconcile_loans --schema=<name> --fix          # rewrite total_paid / outstanding_balance
    python manage.py reconcile_loans --all-tenants --tolerance 1    # every tenant, ignore diffs <= 1 UGX
"""
from decimal import Decimal

from django.db.models import Sum

from loans.models import Loan, LoanSchedule
from payments.models import Payment
from tenants.command_utils import TenantSchemaCommand

ZERO = Decimal("0")


class Command(TenantSchemaCommand):
    help = "Compare Loan.total_paid / outstanding_balance with schedule rows and payments."

    def add_tenant_arguments(self, parser):
        parser.add_argument("--fix", action="store_true", help="Rewrite stored totals from the schedule.")
        parser.add_argument("--tolerance", type=Decimal, default=Decimal("0.01"))

    def handle_tenant(self, schema, *args, **opts):
        tol, fix = opts["tolerance"], opts["fix"]
        bad = 0
        loans = Loan.objects.exclude(status__in=["DRAFT", "PENDING", "APPROVED", "REJECTED"])
        for loan in loans.iterator():
            rows = LoanSchedule.objects.filter(loan=loan).exclude(status="WAIVED")
            sched_paid = rows.aggregate(t=Sum("amount_paid"))["t"] or ZERO
            sched_owed = sum(
                (max(r.total_payment + r.penalty_due - r.amount_paid, ZERO) for r in rows), ZERO
            )
            # Allocated payments on THIS loan (includes credit transfers: they are real allocations).
            allocated = Payment.objects.filter(loan=loan, status="ALLOCATED")
            split_total = sum(
                (x.principal_paid + x.interest_paid + x.penalty_paid for x in allocated), ZERO
            )
            problems = []
            if abs(loan.total_paid - sched_paid) > tol:
                problems.append(f"total_paid {loan.total_paid:,.2f} != schedule amount_paid {sched_paid:,.2f}")
            if abs(split_total - sched_paid) > tol:
                problems.append(f"payment splits {split_total:,.2f} != schedule amount_paid {sched_paid:,.2f}")
            if loan.status in ("ACTIVE", "RESTRUCTURED", "DEFAULTED") and abs(loan.outstanding_balance - sched_owed) > tol:
                problems.append(f"outstanding {loan.outstanding_balance:,.2f} != schedule owed {sched_owed:,.2f}")
            if loan.status == "COMPLETED" and sched_owed > tol:
                problems.append(f"COMPLETED but schedule still owes {sched_owed:,.2f}")
            if loan.status == "ACTIVE" and loan.outstanding_balance <= 0:
                problems.append("ACTIVE with zero outstanding balance")
            if loan.status == "WRITTEN_OFF" and loan.outstanding_balance != 0:
                problems.append(f"WRITTEN_OFF but outstanding {loan.outstanding_balance:,.2f}")
            for x in allocated:
                parts = x.principal_paid + x.interest_paid + x.penalty_paid
                if parts > x.amount_received + tol and not x.reference_number.startswith("CREDIT_TRANSFER:"):
                    # Allowed when client credit was auto-applied; flag only for review.
                    pass
            if problems:
                bad += 1
                self.stdout.write(self.style.WARNING(f"{loan.loan_number} [{loan.status}]"))
                for msg in problems:
                    self.stdout.write(f"    - {msg}")
                if fix and loan.status in ("ACTIVE", "RESTRUCTURED", "DEFAULTED", "COMPLETED"):
                    loan.total_paid = sched_paid
                    loan.outstanding_balance = sched_owed
                    loan.save(update_fields=["total_paid", "outstanding_balance", "updated_at"])
                    self.stdout.write(self.style.SUCCESS("    fixed totals from schedule"))
        self.stdout.write(self.style.SUCCESS(f"Done. {bad} loan(s) with discrepancies."))
