from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.models import CompanySettings
from clients.models import Client
from loans.models import Loan, LoanProduct
from loans.utils import resolve_processing_fee_rate


class ProcessingFeeResolutionTests(SimpleTestCase):
    def test_uses_product_rate_when_available(self):
        product = SimpleNamespace(processing_fee_percent=Decimal("1.50"))

        self.assertEqual(resolve_processing_fee_rate(product), Decimal("1.50"))

    def test_falls_back_to_company_default_when_product_is_missing(self):
        settings = CompanySettings(default_processing_fee_percent=Decimal("2.25"))

        self.assertEqual(resolve_processing_fee_rate(None, settings), Decimal("2.25"))


class LoanListStaffFilterTests(TestCase):
    def test_list_filters_loans_by_applied_staff(self):
        User = get_user_model()
        staff_a = User.objects.create_user(username="staff_a", email="staffa@example.com", password="secret123", role=User.Role.CASHIER)
        staff_b = User.objects.create_user(username="staff_b", email="staffb@example.com", password="secret123", role=User.Role.CASHIER)

        product = LoanProduct.objects.create(
            name="Test Product",
            interest_rate_monthly=Decimal("2.00"),
            processing_fee_percent=Decimal("1.00"),
        )

        client = Client.objects.create(
            first_name="Jane",
            last_name="Doe",
            gender=Client.Gender.FEMALE,
            date_of_birth="1990-01-01",
            marital_status=Client.MaritalStatus.SINGLE,
            nin="NIN1234567890",
            phone_primary="+256700000001",
            physical_address="Kampala",
            district="Kampala",
            employment_status=Client.EmploymentStatus.EMPLOYED,
        )

        Loan.objects.create(
            client=client,
            product=product,
            applied_by=staff_a,
            principal_amount=Decimal("1000000"),
            interest_rate_monthly=Decimal("2.00"),
            interest_method=LoanProduct.InterestMethod.FLAT_RATE,
            penalty_rate_monthly=Decimal("2.00"),
            term_months=3,
            repayment_frequency=Loan.RepaymentFrequency.MONTHLY,
            total_repayable=Decimal("1000000"),
            outstanding_balance=Decimal("1000000"),
            status=Loan.Status.PENDING,
            loan_number="LN-2024-00001",
            core_id="LN00000001",
        )

        Loan.objects.create(
            client=client,
            product=product,
            applied_by=staff_b,
            principal_amount=Decimal("2000000"),
            interest_rate_monthly=Decimal("2.00"),
            interest_method=LoanProduct.InterestMethod.FLAT_RATE,
            penalty_rate_monthly=Decimal("2.00"),
            term_months=6,
            repayment_frequency=Loan.RepaymentFrequency.MONTHLY,
            total_repayable=Decimal("2000000"),
            outstanding_balance=Decimal("2000000"),
            status=Loan.Status.PENDING,
            loan_number="LN-2024-00002",
            core_id="LN00000002",
        )

        self.client.force_login(staff_a)
        response = self.client.get(reverse("loans:list"), {"staff": str(staff_b.pk)})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "LN-2024-00002")
        self.assertNotContains(response, "LN-2024-00001")


class LoanScheduleCalculationTests(SimpleTestCase):
    def test_reducing_balance_total_repayable_matches_schedule_sum(self):
        from datetime import date
        from loans.utils import generate_schedule
        from decimal import Decimal

        principal = Decimal("1000000")
        schedule, totals = generate_schedule(
            principal=principal,
            annual_rate=Decimal("60"),
            term_months=12,
            start_date=date.today(),
            method="REDUCING",
            frequency="MONTHLY",
        )

        total_payment_sum = sum(row["total_payment"] for row in schedule)
        total_interest_sum = sum(row["interest_due"] for row in schedule)

        self.assertEqual(totals["total_repayable"], total_payment_sum)
        self.assertEqual(totals["total_interest"], total_interest_sum)


class LoanOutstandingBalanceTests(TestCase):
    def test_loan_review_submission_stores_principal_plus_interest_only(self):
        User = get_user_model()
        cashier = User.objects.create_user(
            username="cashier",
            email="cashier@example.com",
            password="pass",
            role=User.Role.CASHIER,
        )

        product = LoanProduct.objects.create(
            name="Test Product",
            interest_rate_monthly=Decimal("2.00"),
            processing_fee_percent=Decimal("1.00"),
            requires_guarantor=False,
        )

        client = Client.objects.create(
            first_name="Jane",
            last_name="Doe",
            gender=Client.Gender.FEMALE,
            date_of_birth="1990-01-01",
            marital_status=Client.MaritalStatus.SINGLE,
            nin="NIN1234567890",
            phone_primary="+256700000001",
            physical_address="Kampala",
            district="Kampala",
            employment_status=Client.EmploymentStatus.EMPLOYED,
        )

        loan = Loan.objects.create(
            client=client,
            product=product,
            applied_by=cashier,
            principal_amount=Decimal("1000000"),
            interest_rate_monthly=Decimal("2.00"),
            interest_method=LoanProduct.InterestMethod.FLAT_RATE,
            penalty_rate_monthly=Decimal("2.00"),
            term_months=6,
            repayment_frequency=Loan.RepaymentFrequency.MONTHLY,
            total_repayable=Decimal("0"),
            outstanding_balance=Decimal("0"),
            status=Loan.Status.DRAFT,
            loan_number="LN-2024-00001",
            core_id="LN00000001",
        )

        self.client.force_login(cashier)
        response = self.client.post(
            reverse("loans:apply_review", kwargs={"client_id": client.pk}),
            {"draft_id": str(loan.pk), "action": "submit"},
        )

        loan.refresh_from_db()
        expected_total_interest = Decimal("1000000") * Decimal("0.02") * Decimal("6")
        expected_total_repayable = Decimal("1000000") + expected_total_interest

        self.assertEqual(response.status_code, 302)
        self.assertEqual(loan.total_repayable, expected_total_repayable)
        self.assertEqual(loan.outstanding_balance, expected_total_repayable)


class LoanScheduleContextTests(SimpleTestCase):
    def test_schedule_context_total_repayable_inclusive_excludes_processing_fee(self):
        from datetime import date
        from loans.utils import build_loan_schedule_context

        product = SimpleNamespace(
            interest_rate_monthly=Decimal("2.00"),
            interest_method="FLAT",
            processing_fee_percent=Decimal("1.00"),
        )

        principal = Decimal("1000000")
        schedule_rows, totals, processing_fee, fee_percent, fee_source = build_loan_schedule_context(
            principal=principal,
            product=product,
            term_months=6,
            frequency="MONTHLY",
            start_date=date.today(),
            include_processing_fee=True,
        )

        expected_total_interest = principal * Decimal("0.02") * Decimal("6")
        expected_total_repayable = principal + expected_total_interest

        self.assertEqual(totals["total_repayable_exclusive"], expected_total_repayable)
        self.assertEqual(totals["total_repayable_inclusive"], expected_total_repayable)
        self.assertEqual(totals["grand_total"], expected_total_repayable)
        self.assertEqual(totals["total_repayable"], expected_total_repayable)
        self.assertEqual(processing_fee, principal * Decimal("0.01"))
