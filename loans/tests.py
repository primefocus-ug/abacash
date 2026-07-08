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
