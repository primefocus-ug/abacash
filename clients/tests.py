from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from common.phone_numbers import normalize_phone_number
from .models import ClientDocument
from .views import _save_client_documents


class PhoneNumberNormalizationTests(SimpleTestCase):
    def test_adds_uganda_country_code_to_local_number(self):
        self.assertEqual(normalize_phone_number("0770 123 456"), "+256770123456")

    def test_normalizes_country_code_without_plus(self):
        self.assertEqual(normalize_phone_number("256 770 123456"), "+256770123456")

    def test_preserves_explicit_country_code_and_removes_trunk_zero(self):
        self.assertEqual(normalize_phone_number("+256 (0) 770-123456"), "+256770123456")

    def test_converts_international_access_prefix(self):
        self.assertEqual(normalize_phone_number("00 256 0770 123456"), "+256770123456")

    def test_preserves_explicit_foreign_country_code(self):
        self.assertEqual(normalize_phone_number("+44 20 1234 5678"), "+442012345678")

    def test_blank_or_non_numeric_input_is_empty(self):
        self.assertEqual(normalize_phone_number(""), "")
        self.assertEqual(normalize_phone_number(" (—) "), "")


class ClientDocumentUploadTests(SimpleTestCase):
    def test_saves_multiple_optional_attachments_with_valid_type(self):
        client = object()
        uploaded_by = object()
        files = [SimpleNamespace(name="id-front.jpg"), SimpleNamespace(name="payslip.pdf")]

        with patch("clients.views.ClientDocument.objects.create") as create_document:
            _save_client_documents(client, files, ClientDocument.DocumentType.NATIONAL_ID, uploaded_by)

        self.assertEqual(create_document.call_count, 2)
        self.assertEqual(create_document.call_args_list[0].kwargs["file"], files[0])
        self.assertEqual(create_document.call_args_list[0].kwargs["document_type"], "NIN")
        self.assertEqual(create_document.call_args_list[1].kwargs["file"], files[1])
        self.assertEqual(create_document.call_args_list[1].kwargs["uploaded_by"], uploaded_by)

    def test_unknown_document_type_falls_back_to_other(self):
        uploaded_file = SimpleNamespace(name="supporting-file.bin")

        with patch("clients.views.ClientDocument.objects.create") as create_document:
            _save_client_documents(object(), [uploaded_file], "UNKNOWN", None)

        self.assertEqual(
            create_document.call_args.kwargs["document_type"],
            ClientDocument.DocumentType.OTHER,
        )