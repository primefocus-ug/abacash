from decimal import Decimal

from django.test import SimpleTestCase

from accounts.templatetags.aba_filters import amount_in_words


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
