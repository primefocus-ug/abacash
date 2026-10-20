import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase

from .branch_scope import get_single_active_branch_id, resolve_branch_for_write
from .models import CapitalInjection
from .views import _quick_form_saved


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
