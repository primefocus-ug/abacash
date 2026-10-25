from decimal import Decimal

from django.test import SimpleTestCase

from accounts.templatetags.aba_filters import amount_in_words
from payments.views import _receipt_document_basename


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
