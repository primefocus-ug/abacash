from io import BytesIO
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import F
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from PIL import Image

from .branch_scope import get_single_active_branch_id, resolve_branch_for_write
from .cash import recent_cash_transactions
from .models import CapitalInjection
from .signals import create_initial_tenant_admin
from .views import (
    _build_dashboard_performance,
    _on_time_schedule_payment_filter,
    _unpaid_overdue_schedule_filter,
    _quick_form_saved,
    _validated_signature_upload,
)
from tenants.provisioning import (
    DEFAULT_EXPENSE_CATEGORIES,
    DEFAULT_PRODUCTS,
    _seed_branch,
    _seed_expense_categories,
    _seed_products,
)


class DefaultBranchSelectionTests(SimpleTestCase):
    @patch("accounts.models.Branch.objects.filter")
    def test_uses_the_only_active_branch_as_default(self, branch_filter):
        branch_filter.return_value.order_by.return_value.values_list.return_value.__getitem__.return_value = [7]

        self.assertEqual(get_single_active_branch_id(), 7)

    @patch("accounts.models.Branch.objects.filter")
    def test_does_not_choose_a_default_when_multiple_active_branches_exist(self, branch_filter):
        branch_filter.return_value.order_by.return_value.values_list.return_value.__getitem__.return_value = [7, 8]

        self.assertIsNone(get_single_active_branch_id())

    @patch("accounts.models.Branch.objects.filter")
    def test_write_resolution_uses_single_active_branch_when_no_choice_was_made(self, branch_filter):
        branch_filter.return_value.order_by.return_value.values_list.return_value.__getitem__.return_value = [7]
        request = SimpleNamespace(
            user=SimpleNamespace(is_superuser=True),
            session={},
        )

        self.assertEqual(resolve_branch_for_write(request, None), 7)


class DashboardPerformanceCalculationTests(SimpleTestCase):
    def test_early_schedule_payment_is_included_in_on_time_payments(self):
        lookup, due_date_expression = _on_time_schedule_payment_filter().children[0]

        self.assertEqual(lookup, "paid_date__lte")
        self.assertEqual(due_date_expression, F("due_date"))

    def test_overdue_balance_includes_prior_due_unpaid_and_partial_installments(self):
        cutoff = date(2026, 10, 25)
        filter_conditions = dict(_unpaid_overdue_schedule_filter(cutoff).children)

        self.assertEqual(filter_conditions["due_date__lt"], cutoff)
        self.assertEqual(
            filter_conditions["status__in"],
            ["PENDING", "PARTIAL", "OVERDUE"],
        )

    @staticmethod
    def _period(**overrides):
        metrics = {
            "loan_charges": Decimal("100"),
            "interest_income": Decimal("100"),
            "disbursements": Decimal("100"),
            "expenses": Decimal("100"),
            "injections": Decimal("100"),
            "overdue_recoveries": Decimal("100"),
            "overdue_balance": Decimal("100"),
            "on_time_rate": 80.0,
            "paid_schedule_count": 10,
        }
        metrics.update(overrides)
        return metrics

    def test_score_uses_directional_comparisons_for_all_requested_metrics(self):
        result = _build_dashboard_performance(
            self._period(
                loan_charges=Decimal("120"),
                interest_income=Decimal("150"),
                disbursements=Decimal("80"),
                expenses=Decimal("80"),
                injections=Decimal("100"),
                overdue_recoveries=Decimal("200"),
                overdue_balance=Decimal("150"),
                on_time_rate=90.0,
            ),
            self._period(),
        )

        self.assertEqual(result["metrics"]["loan_charges"]["change_label"], "+20.0%")
        self.assertEqual(result["metrics"]["expenses"]["direction"], "positive")
        self.assertEqual(result["metrics"]["disbursements"]["direction"], "negative")
        self.assertEqual(result["metrics"]["overdue_recoveries"]["change_label"], "+100.0%")
        self.assertEqual(result["metrics"]["overdue_balance"]["direction"], "negative")
        self.assertEqual(result["metrics"]["on_time_rate"]["change_label"], "+10.0 pp")
        self.assertEqual(result["score"], 64.3)
        self.assertTrue(result["recommendations"])
        self.assertFalse(result["metrics"]["disbursements"]["contributes_to_score"])

    def test_unchanged_empty_periods_have_neutral_score(self):
        empty_period = self._period(**{
            key: Decimal("0") for key in (
                "loan_charges", "interest_income", "disbursements", "expenses",
                "injections", "overdue_recoveries", "overdue_balance",
            )
        })
        empty_period["on_time_rate"] = 0.0
        empty_period["paid_schedule_count"] = 0

        result = _build_dashboard_performance(empty_period, empty_period)

        self.assertEqual(result["score"], 50.0)
        self.assertEqual(
            result["metrics"]["on_time_rate"]["change_label"],
            "No observations",
        )

    def test_new_activity_is_labeled_and_expense_growth_is_unfavorable(self):
        current = self._period(
            loan_charges=Decimal("0"),
            interest_income=Decimal("0"),
            disbursements=Decimal("0"),
            expenses=Decimal("100"),
            injections=Decimal("0"),
            overdue_recoveries=Decimal("0"),
            on_time_rate=0.0,
        )
        previous = self._period(**{
            key: Decimal("0") for key in (
                "loan_charges", "interest_income", "disbursements", "expenses",
                "injections", "overdue_recoveries", "overdue_balance",
            )
        })
        previous["on_time_rate"] = 0.0

        result = _build_dashboard_performance(current, previous)

        self.assertEqual(result["metrics"]["expenses"]["change_label"], "New")
        self.assertEqual(result["metrics"]["expenses"]["direction"], "negative")
        self.assertLess(result["score"], 50.0)

    def test_growth_and_funding_metrics_do_not_raise_the_score(self):
        baseline = self._period()
        current = self._period(
            loan_charges=Decimal("1000"),
            disbursements=Decimal("1000"),
            expenses=Decimal("0"),
            injections=Decimal("1000"),
            overdue_recoveries=Decimal("1000"),
        )

        result = _build_dashboard_performance(current, baseline)

        self.assertEqual(result["score"], 63.5)
        for key in ("loan_charges", "disbursements", "expenses", "injections", "overdue_recoveries"):
            self.assertFalse(result["metrics"][key]["contributes_to_score"])

    def test_new_interest_without_comparison_baseline_is_neutral(self):
        current = self._period(interest_income=Decimal("100"))
        previous = self._period(interest_income=Decimal("0"))

        result = _build_dashboard_performance(current, previous)

        self.assertEqual(result["metrics"]["interest_income"]["change_label"], "New")
        self.assertEqual(result["score"], 63.5)

    def test_unpaid_overdue_balance_increase_reduces_score(self):
        current = self._period(overdue_balance=Decimal("200"))
        previous = self._period(overdue_balance=Decimal("100"))

        result = _build_dashboard_performance(current, previous)

        self.assertEqual(result["score"], 46.0)
        self.assertIn("Unpaid overdue balance moved against the prior period", [
            item["title"] for item in result["recommendations"]
        ])


class UserSignatureUploadTests(SimpleTestCase):
    def test_accepts_a_valid_png_signature(self):
        image_buffer = BytesIO()
        Image.new("RGB", (1, 1), color="black").save(image_buffer, format="PNG")
        upload = SimpleUploadedFile(
            "signature.png",
            image_buffer.getvalue(),
            content_type="image/png",
        )

        self.assertEqual(_validated_signature_upload(upload).name, "signature.png")

    def test_rejects_signature_larger_than_two_megabytes(self):
        upload = SimpleUploadedFile(
            "signature.png",
            b"x" * (2 * 1024 * 1024 + 1),
            content_type="image/png",
        )

        with self.assertRaisesMessage(ValueError, "2 MB or smaller"):
            _validated_signature_upload(upload)

    def test_rejects_non_image_signature_content(self):
        upload = SimpleUploadedFile(
            "signature.png",
            b"not an image",
            content_type="image/png",
        )

        with self.assertRaises(ValidationError):
            _validated_signature_upload(upload)


class QuickFormResponseTests(SimpleTestCase):
    def test_standard_post_keeps_the_existing_redirect_flow(self):
        request = RequestFactory().post("/accounts/admin-panel/branches/new/")

        self.assertIsNone(_quick_form_saved(request))

    def test_htmx_post_returns_a_success_event_without_a_page_response(self):
        request = RequestFactory().post(
            "/accounts/admin-panel/branches/new/",
            HTTP_HX_REQUEST="true",
        )

        response = _quick_form_saved(request)

        self.assertEqual(response.status_code, 204)
        events = json.loads(response["HX-Trigger"])
        self.assertIn("quickFormSaved", events)
        self.assertIn("quickFormNotice", events)


class RecentCashRangeTests(SimpleTestCase):
    def test_cash_preview_filters_each_source_to_the_selected_dates(self):
        start_date = date(2026, 1, 1)
        end_date = date(2026, 3, 31)
        querysets = []
        for _ in range(4):
            queryset = MagicMock()
            queryset.filter.return_value = queryset
            queryset.select_related.return_value = queryset
            queryset.order_by.return_value = queryset
            queryset.__getitem__.return_value = []
            querysets.append(queryset)

        with (
            patch("payments.models.Payment.objects.cash_receipts", return_value=querysets[0]),
            patch("loans.models.Loan.objects.filter", return_value=querysets[1]),
            patch("accounts.models.Expense.objects.filter", return_value=querysets[2]),
            patch("accounts.models.CapitalInjection.objects.filter", return_value=querysets[3]),
        ):
            transactions = recent_cash_transactions(start_date=start_date, end_date=end_date)

        self.assertEqual(transactions, [])
        expected_date_filters = (
            ("payment_date__gte", "payment_date__lte"),
            ("disbursement_date__gte", "disbursement_date__lte"),
            ("expense_date__gte", "expense_date__lte"),
            ("injected_date__gte", "injected_date__lte"),
        )
        for queryset, (start_lookup, end_lookup) in zip(querysets, expected_date_filters):
            queryset.filter.assert_any_call(**{start_lookup: start_date})
            queryset.filter.assert_any_call(**{end_lookup: end_date})


class InitialTenantAdminSignalTests(SimpleTestCase):
    def test_seeds_the_configured_superuser_in_a_new_tenant(self):
        user_manager = Mock()
        user_manager.exists.return_value = False
        user_model = SimpleNamespace(objects=user_manager)
        tenant_connection = SimpleNamespace(schema_name="tenant_alpha", settings_dict={})

        with (
            override_settings(
                TENANT_INITIAL_ADMIN_USERNAME="admin",
                TENANT_INITIAL_ADMIN_EMAIL="primefocusug@gmail.com",
                TENANT_INITIAL_ADMIN_PASSWORD="@Developer25",
            ),
            patch("accounts.signals.connection", tenant_connection),
            patch("accounts.signals.get_user_model", return_value=user_model),
        ):
            create_initial_tenant_admin(None, SimpleNamespace(name="accounts"))

        user_manager.create_superuser.assert_called_once_with(
            username="admin",
            email="primefocusug@gmail.com",
            password="@Developer25",
        )


class CapitalInjectionCreateViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="ceo",
            email="ceo@example.com",
            password="secret123",
            first_name="CEO",
            last_name="User",
            role="CEO",
        )
        self.user.role = "CEO"
        self.user.save(update_fields=["role"])

    def test_create_redirects_and_saves_when_amount_is_submitted_as_string(self):
        response = self.client.post(
            "/accounts/admin-panel/capital-injections/create/",
            {
                "source": "Investor",
                "amount": "1000",
                "injected_date": "2026-06-28",
                "investor": "Jane",
                "notes": "Seed funding",
            },
            follow=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, "/accounts/admin-panel/capital-injections/")
        self.assertTrue(CapitalInjection.objects.filter(source="Investor").exists())
        injection = CapitalInjection.objects.get(source="Investor")
        self.assertEqual(injection.amount, Decimal("1000"))


class SuperuserPermissionTests(SimpleTestCase):
    def test_superuser_has_all_permissions(self):
        user = get_user_model()(
            email="admin@example.com",
            is_active=True,
            is_superuser=True,
        )

        self.assertTrue(user.has_perm("accounts.can_manage_branches"))


class TenantBootstrapDefaultsTests(SimpleTestCase):
    def test_seeds_configured_head_office_branch(self):
        branch = object()
        with patch("accounts.models.Branch.objects.get_or_create", return_value=(branch, True)) as seed:
            result = _seed_branch("Focus Finance", "+256700000000", "Kampala", "office@example.com")

        self.assertIs(result, branch)
        self.assertEqual(seed.call_args.kwargs["code"], "HQ")
        self.assertEqual(seed.call_args.kwargs["defaults"]["name"], "Focus Finance — Head Office")
        self.assertEqual(seed.call_args.kwargs["defaults"]["phone"], "+256700000000")

    def test_seeds_expense_categories_and_types_idempotently(self):
        with (
            patch(
                "accounts.models.TransactionCategory.objects.get_or_create",
                side_effect=lambda name, defaults: (SimpleNamespace(name=name), False),
            ) as seed_category,
            patch("accounts.models.ExpenseType.objects.get_or_create") as seed_type,
        ):
            _seed_expense_categories()

        expected_type_count = sum(len(category["types"]) for category in DEFAULT_EXPENSE_CATEGORIES)
        self.assertEqual(seed_category.call_count, len(DEFAULT_EXPENSE_CATEGORIES))
        self.assertEqual(seed_type.call_count, expected_type_count)

    def test_seeds_editable_loan_product_defaults_including_logbook(self):
        with patch(
            "loans.models.LoanProduct.objects.get_or_create",
            side_effect=lambda name, defaults: (SimpleNamespace(name=name), True),
        ) as seed_product:
            _seed_products()

        seeded_names = {call.kwargs["name"] for call in seed_product.call_args_list}
        expected_names = {product["name"] for product in DEFAULT_PRODUCTS}
        self.assertSetEqual(seeded_names, expected_names)
        self.assertIn("Logbook Loan", seeded_names)
