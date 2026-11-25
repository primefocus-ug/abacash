from types import SimpleNamespace
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse

from accounts.templatetags.aba_filters import amount_in_words
from payments import views as payment_views
from payments.admin import PaymentAdmin
from payments.models import Payment
from payments.views import _assess_schedule_penalty, _receipt_document_basename


class AmountInWordsTests(SimpleTestCase):
    def test_formats_amount_in_words(self):
        self.assertEqual(
            amount_in_words(Decimal("1234567")),
            "one million two hundred thirty-four thousand five hundred sixty-seven Uganda shillings only",
        )

    def test_matches_receipt_display_for_fractional_amounts(self):
        self.assertEqual(
            amount_in_words(Decimal("100.99")),
            "one hundred Uganda shillings only",
        )

    def test_formats_zero_and_negative_amounts(self):
        self.assertEqual(amount_in_words(Decimal("0")), "zero Uganda shillings only")
        self.assertEqual(
            amount_in_words(Decimal("-5")),
            "minus five Uganda shillings only",
        )


class ReceiptDocumentNameTests(SimpleTestCase):
    def test_filename_includes_company_client_and_tenant_slug(self):
        self.assertEqual(
            _receipt_document_basename(
                "Acme Finance Ltd",
                "Amina N. Kato",
                "acme_finance",
            ),
            "acme-finance-ltd-amina-n-kato-acme-finance",
        )

    def test_filename_removes_path_characters(self):
        self.assertEqual(
            _receipt_document_basename("Acme/Finance", "Amina Kato", "acme"),
            "acme-finance-amina-kato-acme",
        )


class SchedulePenaltyAssessmentTests(SimpleTestCase):
    def setUp(self):
        self.loan = SimpleNamespace(
            penalty_enabled=True,
            penalty_rate_monthly=Decimal("2"),
            penalty_frequency="DAILY",
        )
        self.entry = SimpleNamespace(
            loan=self.loan,
            due_date=date(2026, 1, 1),
            total_payment=Decimal("1000"),
            amount_paid=Decimal("0"),
            penalty_due=Decimal("0"),
            penalty_paid=Decimal("0"),
            penalty_periods_processed=0,
        )
        self.company_settings = SimpleNamespace(
            penalties_enabled=True,
            grace_period_days=0,
        )

    def test_daily_penalty_is_assessed_once_per_overdue_day(self):
        first_assessment = _assess_schedule_penalty(
            self.entry,
            self.loan,
            date(2026, 1, 4),
            self.company_settings,
        )
        repeat_assessment = _assess_schedule_penalty(
            self.entry,
            self.loan,
            date(2026, 1, 4),
            self.company_settings,
        )

        self.assertEqual(first_assessment, Decimal("60.00"))
        self.assertEqual(repeat_assessment, Decimal("0"))
        self.assertEqual(self.entry.penalty_due, Decimal("60.00"))

    def test_new_daily_penalty_uses_remaining_unpaid_installment(self):
        _assess_schedule_penalty(
            self.entry,
            self.loan,
            date(2026, 1, 2),
            self.company_settings,
        )
        self.entry.amount_paid = Decimal("520")
        self.entry.penalty_paid = Decimal("20")

        newly_accrued = _assess_schedule_penalty(
            self.entry,
            self.loan,
            date(2026, 1, 3),
            self.company_settings,
        )

        self.assertEqual(newly_accrued, Decimal("10.00"))
        self.assertEqual(self.entry.penalty_due, Decimal("30.00"))

    def test_master_setting_off_skips_periods_without_accruing_them_later(self):
        self.company_settings.penalties_enabled = False
        skipped = _assess_schedule_penalty(
            self.entry,
            self.loan,
            date(2026, 1, 4),
            self.company_settings,
        )
        self.company_settings.penalties_enabled = True
        next_period = _assess_schedule_penalty(
            self.entry,
            self.loan,
            date(2026, 1, 5),
            self.company_settings,
        )

        self.assertEqual(skipped, Decimal("0"))
        self.assertEqual(next_period, Decimal("20.00"))
        self.assertEqual(self.entry.penalty_due, Decimal("20.00"))

    def test_monthly_penalty_uses_started_thirty_day_periods(self):
        self.loan.penalty_frequency = "MONTHLY"
        self.assertEqual(
            _assess_schedule_penalty(
                self.entry,
                self.loan,
                date(2026, 2, 1),
                self.company_settings,
            ),
            Decimal("40.00"),
        )

    def test_grace_period_is_excluded_from_penalty_days(self):
        self.company_settings.grace_period_days = 3
        self.assertEqual(
            _assess_schedule_penalty(
                self.entry,
                self.loan,
                date(2026, 1, 4),
                self.company_settings,
            ),
            Decimal("0"),
        )
        self.assertEqual(
            _assess_schedule_penalty(
                self.entry,
                self.loan,
                date(2026, 1, 5),
                self.company_settings,
            ),
            Decimal("20.00"),
        )


class CreditRefundRoleTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.client_pk = "12345678-1234-5678-1234-567812345678"

    @patch("payments.views.messages.error")
    def test_non_ceo_cannot_open_refund_form(self, show_error):
        request = self.factory.get("/")
        request.user = SimpleNamespace(role="MANAGER", is_authenticated=True)

        response = payment_views.credit_refund(request, client_pk=self.client_pk)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            reverse("clients:detail", kwargs={"pk": self.client_pk}),
        )
        show_error.assert_called_once()

    @patch("payments.views.render", return_value=HttpResponse())
    @patch("payments.views.can_access_branch_object", return_value=True)
    @patch("payments.views.get_object_or_404")
    def test_ceo_can_open_refund_form(self, get_object, _branch_access, render):
        request = self.factory.get("/")
        request.user = SimpleNamespace(role="CEO", is_authenticated=True)
        client = SimpleNamespace()
        get_object.return_value = client

        response = payment_views.credit_refund(request, client_pk=self.client_pk)

        self.assertEqual(response.status_code, 200)
        render.assert_called_once_with(
            request,
            "payments/credit_refund.html",
            {"client": client},
        )


class PaymentAdminRoleTests(SimpleTestCase):
    def setUp(self):
        self.payment_admin = PaymentAdmin(Payment, AdminSite())

    def test_non_ceo_cannot_delete_or_reverse_payment_in_admin(self):
        request = SimpleNamespace(
            user=SimpleNamespace(
                role="MANAGER",
                has_perm=lambda _permission: True,
            )
        )

        self.assertFalse(self.payment_admin.has_delete_permission(request))
        readonly_fields = self.payment_admin.get_readonly_fields(request)
        self.assertTrue(
            {"status", "reversal_reason", "reversal_date", "reversed_by"}.issubset(
                readonly_fields
            )
        )

    def test_ceo_can_delete_payment_when_django_permission_is_granted(self):
        request = SimpleNamespace(
            user=SimpleNamespace(
                role="CEO",
                has_perm=lambda _permission: True,
            )
        )

        self.assertTrue(self.payment_admin.has_delete_permission(request))
