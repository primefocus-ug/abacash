from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import CapitalInjection


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
