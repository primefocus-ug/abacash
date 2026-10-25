from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from unittest.mock import patch

from accounts.models import CompanySettings
from clients.models import Client
from common.pdf_utils import generate_loan_schedule_pdf
from loans import views as loan_views
from loans.models import Loan, LoanProduct
from loans.utils import calculate_processing_fee_amount, resolve_processing_fee_rate


class _RelatedList(list):
    def all(self):
        return self

    def exists(self):
        return bool(self)

    def order_by(self, *fields):
        return self

    def select_related(self, *fields):
        return self


class ProcessingFeeResolutionTests(SimpleTestCase):
    def test_new_company_settings_use_default_range_fees(self):
        settings = CompanySettings()
        self.assertEqual(settings.processing_fee_method, "RANGE")
        self.assertEqual(
            settings.processing_fee_ranges,
            "0-50000:4000\n"
            "100000-200000:8000\n"
            "200001-300001:10000\n"
            "300001-450000:12000\n"
            "450001-600000:15000\n"
            "600001-800000:20000\n"
            "800001-1000000:30000\n"
            "1000001-:40000",
        )

    def test_range_fees_match_configured_inclusive_tiers_and_gaps(self):
        settings = CompanySettings()
        cases = (
            ("50000", "4000"),
            ("50001", "0"),
            ("99999", "0"),
            ("100000", "8000"),
            ("200000", "8000"),
            ("200001", "10000"),
            ("300001", "10000"),
            ("300002", "12000"),
            ("450000", "12000"),
            ("450001", "15000"),
            ("600001", "20000"),
            ("800001", "30000"),
            ("1000000", "30000"),
            ("1000001", "40000"),
        )

        for principal, expected_fee in cases:
            with self.subTest(principal=principal):
                self.assertEqual(
                    calculate_processing_fee_amount(Decimal(principal), company_settings=settings),
                    Decimal(expected_fee),
                )

    def test_uses_product_rate_when_available(self):
        product = SimpleNamespace(processing_fee_percent=Decimal("1.50"))

        self.assertEqual(resolve_processing_fee_rate(product), Decimal("1.50"))

    def test_falls_back_to_company_default_when_product_is_missing(self):
        settings = CompanySettings(
            processing_fee_method="PERCENTAGE",
            default_processing_fee_percent=Decimal("2.25"),
        )

        self.assertEqual(resolve_processing_fee_rate(None, settings), Decimal("2.25"))


class LoanProductCreateDefaultsTests(SimpleTestCase):
    def test_new_product_form_defaults_to_active(self):
        request = RequestFactory().get("/loans/products/new/")
        request.user = SimpleNamespace(role="CEO", is_authenticated=True)

        with patch("loans.views.render") as render:
            loan_views.loan_product_create(request)

        context = render.call_args.args[2]
        self.assertTrue(context["product_form_defaults"]["is_active"])
        self.assertFalse(context["product_form_defaults"]["requires_collateral"])

    def test_htmx_request_renders_product_creation_popover(self):
        request = RequestFactory().get(
            "/loans/products/new/",
            HTTP_HX_REQUEST="true",
        )
        request.user = SimpleNamespace(role="CEO", is_authenticated=True)

        with patch("loans.views.render") as render:
            loan_views.loan_product_create(request)

        self.assertEqual(render.call_args.args[1], "loans/product_form_modal.html")

    def test_htmx_product_create_redirects_to_product_list(self):
        request = RequestFactory().post(
            "/loans/products/new/",
            {
                "name": "Short Term",
                "interest_rate_monthly": "2",
                "interest_method": "FLAT",
                "default_repayment_frequency": "MONTHLY",
                "min_amount": "100000",
                "max_amount": "500000",
                "min_term_months": "1",
                "max_term_months": "6",
                "penalty_rate_monthly": "1",
            },
            HTTP_HX_REQUEST="true",
        )
        request.user = SimpleNamespace(role="CEO", is_authenticated=True)
        product = SimpleNamespace(name="Short Term", full_clean=lambda: None, save=lambda: None)

        with (
            patch("loans.views.LoanProduct", return_value=product),
            patch("loans.views.messages.success"),
        ):
            response = loan_views.loan_product_create(request)

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Redirect"], reverse("loans:products"))


class LoanProductEditPopoverTests(SimpleTestCase):
    def setUp(self):
        self.product = SimpleNamespace(
            pk=1,
            name="Short Term",
            description="",
            interest_rate_monthly=Decimal("2"),
            interest_method="FLAT",
            default_repayment_frequency="MONTHLY",
            min_amount=Decimal("100000"),
            max_amount=Decimal("500000"),
            min_term_months=1,
            max_term_months=6,
            penalty_rate_monthly=Decimal("1"),
            processing_fee_percent=Decimal("0"),
            requires_guarantor=False,
            requires_collateral=False,
            is_active=True,
            full_clean=lambda: None,
            save=lambda: None,
        )

    def test_htmx_get_renders_product_edit_popover(self):
        request = RequestFactory().get(
            "/loans/products/1/edit/",
            HTTP_HX_REQUEST="true",
        )
        request.user = SimpleNamespace(role="CEO", is_authenticated=True)

        with (
            patch("loans.views.get_object_or_404", return_value=self.product),
            patch("loans.views.render") as render,
        ):
            loan_views.loan_product_edit(request, pk=1)

        self.assertEqual(render.call_args.args[1], "loans/product_form_modal.html")
        self.assertEqual(render.call_args.args[2]["action"], "edit")
        self.assertEqual(render.call_args.args[2]["product_form_defaults"]["name"], "Short Term")

    def test_htmx_edit_saves_and_redirects_to_product_list(self):
        request = RequestFactory().post(
            "/loans/products/1/edit/",
            {
                "name": "Updated Term",
                "interest_rate_monthly": "2",
                "interest_method": "FLAT",
                "default_repayment_frequency": "MONTHLY",
                "min_amount": "100000",
                "max_amount": "500000",
                "min_term_months": "1",
                "max_term_months": "6",
                "penalty_rate_monthly": "1",
            },
            HTTP_HX_REQUEST="true",
        )
        request.user = SimpleNamespace(role="CEO", is_authenticated=True)

        with (
            patch("loans.views.get_object_or_404", return_value=self.product),
            patch("loans.views.messages.success"),
        ):
            response = loan_views.loan_product_edit(request, pk=1)

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Redirect"], reverse("loans:products"))
        self.assertEqual(self.product.name, "Updated Term")

    def test_invalid_htmx_edit_renders_errors_inside_the_popover(self):
        request = RequestFactory().post(
            "/loans/products/1/edit/",
            {
                "name": "Updated Term",
                "interest_rate_monthly": "2",
                "interest_method": "FLAT",
                "default_repayment_frequency": "MONTHLY",
                "min_amount": "100000",
                "max_amount": "500000",
                "min_term_months": "1",
                "max_term_months": "6",
                "penalty_rate_monthly": "1",
            },
            HTTP_HX_REQUEST="true",
        )
        request.user = SimpleNamespace(role="CEO", is_authenticated=True)

        with (
            patch("loans.views.get_object_or_404", return_value=self.product),
            patch.object(self.product, "full_clean", side_effect=ValueError("Invalid product terms.")),
            patch.object(self.product, "save") as save,
            patch("loans.views.render") as render,
        ):
            loan_views.loan_product_edit(request, pk=1)

        self.assertEqual(render.call_args.args[1], "loans/product_form_modal.html")
        self.assertIn("Invalid product terms.", render.call_args.args[2]["form_error"])
        save.assert_not_called()


class LoanProductRangeValidationTests(SimpleTestCase):
    def test_rejects_maximum_amount_below_minimum(self):
        product = LoanProduct(min_amount=Decimal("100000"), max_amount=Decimal("1"))

        with self.assertRaises(ValidationError) as error:
            product.clean()

        self.assertIn("max_amount", error.exception.message_dict)

    def test_rejects_maximum_term_below_minimum(self):
        product = LoanProduct(min_term_months=6, max_term_months=1)

        with self.assertRaises(ValidationError) as error:
            product.clean()

        self.assertIn("max_term_months", error.exception.message_dict)


class SchedulePdfGenerationTests(SimpleTestCase):
    def test_generates_pdf_with_payment_reconciliation_fields(self):
        payment = SimpleNamespace(reference_number="MOMO-12345")
        schedule_row = SimpleNamespace(
            due_date=date(2026, 11, 1),
            paid_date=date(2026, 11, 1),
            paid_by_payment=payment,
            opening_balance=Decimal("110000"),
            principal_due=Decimal("100000"),
            interest_due=Decimal("10000"),
            penalty_due=Decimal("0"),
            total_payment=Decimal("110000"),
            amount_paid=Decimal("110000"),
            closing_balance=Decimal("0"),
            get_status_display=lambda: "Paid",
        )
        collateral = SimpleNamespace(
            description="Motorcycle",
            estimated_value=Decimal("5000000"),
            document_number="LOG-123",
            storage_location="Kampala branch",
            notes="",
            release_date=None,
            released_to="",
        )
        loan = SimpleNamespace(
            loan_number="LN-00001",
            client=SimpleNamespace(full_name="Test Client"),
            principal_amount=Decimal("100000"),
            product=SimpleNamespace(name="Salary Loan"),
            get_status_display=lambda: "Active",
            disbursement_date=date(2026, 10, 1),
            maturity_date=date(2026, 11, 1),
            get_interest_method_display=lambda: "Flat Rate",
            interest_rate_monthly=Decimal("5.00"),
            total_interest=Decimal("10000"),
            processing_fee=Decimal("4000"),
            total_repayable=Decimal("110000"),
            total_paid=Decimal("110000"),
            collateral_items=_RelatedList([collateral]),
            schedule=_RelatedList([schedule_row]),
        )
        signature_buffer = BytesIO()
        Image.new("RGB", (1, 1), color="black").save(signature_buffer, format="PNG")
        signatory = SimpleNamespace(
            full_name="Test Signatory",
            signature=ContentFile(signature_buffer.getvalue(), name="signature.png"),
        )

        with patch("accounts.models.BankAccount.objects.filter", return_value=_RelatedList()):
            pdf = generate_loan_schedule_pdf(loan, signatory=signatory)

        self.assertTrue(pdf.startswith(b"%PDF"))


class OptionalGuarantorAmountTests(SimpleTestCase):
    def test_blank_guaranteed_amount_is_allowed(self):
        self.assertEqual(loan_views._parse_optional_guarantor_amount(""), Decimal("0"))

    def test_supplied_guaranteed_amount_must_be_positive(self):
        self.assertEqual(
            loan_views._parse_optional_guarantor_amount("25000"),
            Decimal("25000"),
        )
        with self.assertRaisesMessage(ValueError, "positive number"):
            loan_views._parse_optional_guarantor_amount("0")
        with self.assertRaisesMessage(ValueError, "positive number"):
            loan_views._parse_optional_guarantor_amount("not-a-number")


class LoanBranchResolutionTests(SimpleTestCase):
    @patch("loans.views.resolve_branch_for_write", return_value=None)
    @patch("loans.views.Branch.objects.filter")
    def test_privileged_user_defaults_to_clients_active_branch(self, branch_filter, _resolver):
        client_branch = SimpleNamespace(pk=12)
        branch_filter.return_value.first.return_value = client_branch
        client = SimpleNamespace(branch_id=12)
        request = SimpleNamespace(
            user=SimpleNamespace(is_superuser=True),
            session={},
        )

        self.assertEqual(loan_views._resolve_loan_branch(request, client, ""), 12)
        branch_filter.assert_called_once_with(pk=12, is_active=True)

    @patch("loans.views.Branch.objects.filter")
    def test_privileged_user_can_select_an_active_branch(self, branch_filter):
        branch_filter.return_value.first.return_value = SimpleNamespace(pk=15)
        request = SimpleNamespace(
            user=SimpleNamespace(
                is_superuser=False,
                can=lambda permission: permission == "can_view_all_branches",
            ),
            session={},
        )

        self.assertEqual(loan_views._resolve_loan_branch(request, SimpleNamespace(branch_id=12), "15"), 15)
        branch_filter.assert_called_once_with(pk="15", is_active=True)

    def test_staff_remain_restricted_to_their_assigned_branch(self):
        request = SimpleNamespace(
            user=SimpleNamespace(is_superuser=False, can=lambda _permission: False, branch_id=21),
            session={},
        )
        with (
            patch("loans.views.resolve_branch_for_write", return_value=21) as resolver,
            patch("loans.views.Branch.objects.filter") as branch_filter,
        ):
            branch_filter.return_value.first.return_value = SimpleNamespace(pk=21)
            self.assertEqual(loan_views._resolve_loan_branch(request, SimpleNamespace(branch_id=12), ""), 21)
        resolver.assert_called_once_with(request, "")


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


class LoanApplicationClientSearchTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="loan_search_cashier",
            email="loan-search@example.com",
            password="test-password",
            role=User.Role.CASHIER,
        )
        self.client.force_login(self.user)

    def create_client(self, first_name, last_name, **overrides):
        details = {
            "first_name": first_name,
            "last_name": last_name,
            "gender": Client.Gender.FEMALE,
            "date_of_birth": "1990-01-01",
            "marital_status": Client.MaritalStatus.SINGLE,
            "nin": overrides.pop("nin", f"NIN-{first_name}-{last_name}"),
            "phone_primary": "+256700000001",
            "physical_address": "Kampala",
            "district": "Kampala",
            "employment_status": Client.EmploymentStatus.EMPLOYED,
            **overrides,
        }
        return Client.objects.create(**details)

    def test_apply_page_shows_the_three_most_recent_clients_immediately(self):
        created_clients = [
            self.create_client(f"Recent{index}", "Client", nin=f"NIN-RECENT-{index}")
            for index in range(4)
        ]
        created_at = timezone.now()
        for index, client in enumerate(created_clients):
            Client.objects.filter(pk=client.pk).update(
                created_at=created_at + timedelta(seconds=index),
            )

        with patch("loans.views.scope_to_branch", side_effect=lambda queryset, _user: queryset):
            response = self.client.get(reverse("loans:apply"))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        visible_numbers = [
            content.index(client.client_number)
            for client in created_clients[1:]
        ]
        self.assertEqual(visible_numbers, sorted(visible_numbers, reverse=True))
        self.assertNotContains(response, created_clients[0].client_number)

    def test_search_matches_a_full_client_name(self):
        client = self.create_client("Jane", "Doe", other_names="Ann", nin="NIN-JANE-DOE")

        with patch("loans.views.scope_to_branch", side_effect=lambda queryset, _user: queryset):
            response = self.client.get(
                reverse("loans:client_search"),
                {"q": "Jane Ann Doe"},
                HTTP_HX_REQUEST="true",
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, client.client_number)
        self.assertContains(response, "Jane Ann Doe")


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


class LoanRescheduleTests(SimpleTestCase):
    def test_reschedule_sets_outstanding_balance_from_first_schedule_row(self):
        class DummyUser:
            role = "MANAGER"
            is_authenticated = True
            username = "manager"
            first_name = "Manager"
            last_name = "Test"

            @property
            def is_ceo(self):
                return False

        class DummyLoan:
            pk = "12345678-1234-1234-1234-123456789abc"
            loan_number = "LN-001"
            term_months = 6
            repayment_frequency = Loan.RepaymentFrequency.MONTHLY
            outstanding_balance = Decimal("1000000")
            disbursement_date = date(2024, 1, 1)
            product = SimpleNamespace(min_term_months=1, max_term_months=12)
            status = Loan.Status.ACTIVE

            def __init__(self):
                self.saved = False
                self.schedule_rows = []

            def save(self):
                self.saved = True

        class DummyScheduleManager:
            def __init__(self):
                self.deleted = False
                self.created_rows = []

            def filter(self, **kwargs):
                return self

            def delete(self):
                self.deleted = True

            def bulk_create(self, rows):
                self.created_rows = rows

        loan = DummyLoan()
        request = RequestFactory().post(
            reverse("loans:reschedule", kwargs={"pk": loan.pk}),
            {
                "term_months": "4",
                "frequency": Loan.RepaymentFrequency.MONTHLY,
                "reason": "Need a shorter schedule",
            },
        )
        request.user = DummyUser()
        schedule_manager = DummyScheduleManager()
        schedule_rows = [
            {"period_number": 1, "due_date": date(2024, 2, 1), "opening_balance": Decimal("500000"), "principal_due": Decimal("400000"), "interest_due": Decimal("100000"), "total_payment": Decimal("500000"), "closing_balance": Decimal("0")},
        ]
        totals = {"total_repayable_exclusive": Decimal("500000"), "total_interest": Decimal("100000")}

        with patch("loans.views.get_object_or_404", return_value=loan), \
             patch("loans.views.build_loan_schedule_context", return_value=(schedule_rows, totals, None, None, None)), \
             patch("loans.views.messages.success"), \
             patch("loans.views.messages.error"), \
             patch("loans.views.LoanSchedule.objects", new=schedule_manager), \
             patch("loans.views.LoanDisbursementAudit.objects.create", return_value=None):
            response = loan_views.loan_reschedule(request, "loan-1")

        self.assertIn(response.status_code, (200, 302))
        self.assertTrue(loan.saved)
        self.assertEqual(loan.outstanding_balance, Decimal("1000000"))

    def test_reschedule_keeps_existing_schedule_when_no_settings_change(self):
        class DummyUser:
            role = "MANAGER"
            is_authenticated = True
            username = "manager"
            first_name = "Manager"
            last_name = "Test"

            @property
            def is_ceo(self):
                return False

        class DummyLoan:
            pk = "12345678-1234-1234-1234-123456789abc"
            loan_number = "LN-001"
            term_months = 6
            repayment_frequency = Loan.RepaymentFrequency.MONTHLY
            outstanding_balance = Decimal("1000000")
            disbursement_date = date(2024, 1, 1)
            product = SimpleNamespace(min_term_months=1, max_term_months=12)
            status = Loan.Status.ACTIVE
            total_repayable = Decimal("1200000")
            total_interest = Decimal("200000")
            maturity_date = date(2024, 7, 1)

            def __init__(self):
                self.saved = False

            def save(self):
                self.saved = True

        class DummyScheduleManager:
            def __init__(self):
                self.deleted = False
                self.created_rows = []

            def filter(self, **kwargs):
                return self

            def delete(self):
                self.deleted = True

            def bulk_create(self, rows):
                self.created_rows = rows

        loan = DummyLoan()
        request = RequestFactory().post(
            reverse("loans:reschedule", kwargs={"pk": loan.pk}),
            {
                "term_months": "6",
                "frequency": Loan.RepaymentFrequency.MONTHLY,
                "reason": "No change needed",
                "disbursement_date": "2024-01-01",
            },
        )
        request.user = DummyUser()
        schedule_manager = DummyScheduleManager()

        with patch("loans.views.get_object_or_404", return_value=loan), \
             patch("loans.views.build_loan_schedule_context", side_effect=AssertionError("build_loan_schedule_context should not run when settings are unchanged")), \
             patch("loans.views.messages.success"), \
             patch("loans.views.messages.error"), \
             patch("loans.views.LoanSchedule.objects", new=schedule_manager), \
             patch("loans.views.LoanDisbursementAudit.objects.create", return_value=None):
            response = loan_views.loan_reschedule(request, "loan-1")

        self.assertIn(response.status_code, (200, 302))
        self.assertFalse(loan.saved)
        self.assertFalse(schedule_manager.deleted)
        self.assertEqual(schedule_manager.created_rows, [])


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
