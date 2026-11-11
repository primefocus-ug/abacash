import base64
import json
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from django.core.mail import EmailMessage
from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

from .email_backends import GmailApiEmailBackend


class GmailApiEmailBackendTests(SimpleTestCase):
    @override_settings(GOOGLE_SENDER_EMAIL="sender@example.com")
    def test_sends_django_message_through_gmail_api(self):
        service = Mock()
        backend = GmailApiEmailBackend()
        backend._get_service = Mock(return_value=service)
        message = EmailMessage(
            "Activation",
            "Create your password",
            to=["user@example.net"],
        )

        self.assertEqual(backend.send_messages([message]), 1)

        payload = service.users.return_value.messages.return_value.send.call_args.kwargs
        raw_message = payload["body"]["raw"]
        decoded_message = base64.urlsafe_b64decode(
            raw_message + "=" * (-len(raw_message) % 4)
        ).decode()
        self.assertEqual(payload["userId"], "me")
        self.assertIn("From: sender@example.com", decoded_message)
        self.assertIn("To: user@example.net", decoded_message)
        self.assertIn("Subject: Activation", decoded_message)


class ConfigureGmailOAuthCommandTests(SimpleTestCase):
    def test_saves_refresh_token_and_enables_gmail_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client_secrets = root / "client_secret.json"
            token_file = root / "google_oauth_token.json"
            env_file = root / ".env"
            client_secrets.write_text("{}", encoding="utf-8")

            credentials = Mock(
                refresh_token="mock-refresh-token",
                to_json=Mock(return_value=json.dumps({
                    "refresh_token": "mock-refresh-token",
                })),
            )
            flow = Mock()
            flow.run_local_server.return_value = credentials

            with (
                override_settings(GOOGLE_OAUTH_TOKEN_FILE=str(token_file)),
                patch(
                    "google_auth_oauthlib.flow.Flow.from_client_secrets_file",
                    return_value=flow,
                ) as create_flow,
            ):
                call_command(
                    "configure_gmail_oauth",
                    client_secrets=str(client_secrets),
                    sender_email="sender@example.com",
                    env_file=str(env_file),
                    stdout=StringIO(),
                )

            self.assertTrue(token_file.is_file())
            self.assertEqual(
                json.loads(token_file.read_text(encoding="utf-8"))["refresh_token"],
                "mock-refresh-token",
            )
            env_contents = env_file.read_text(encoding="utf-8")
            self.assertIn("EMAIL_PROVIDER=gmail_api", env_contents)
            self.assertIn("GOOGLE_SENDER_EMAIL=sender@example.com", env_contents)
            self.assertEqual(
                create_flow.call_args.kwargs["redirect_uri"],
                "http://localhost:8766/",
            )
