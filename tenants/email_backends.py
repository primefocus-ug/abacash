import base64
import logging
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)


class GmailApiEmailBackend(BaseEmailBackend):
    """Send Django email messages through one platform Gmail account."""

    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        self._service = None

    def _get_service(self):
        if self._service is not None:
            return self._service

        token_path = Path(settings.GOOGLE_OAUTH_TOKEN_FILE)
        if not token_path.is_file():
            raise ImproperlyConfigured(
                "Gmail OAuth token file is missing. Run "
                "`python manage.py configure_gmail_oauth` first."
            )

        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        credentials = Credentials.from_authorized_user_file(
            str(token_path),
            scopes=["https://www.googleapis.com/auth/gmail.send"],
        )
        if not credentials.valid:
            if not credentials.expired or not credentials.refresh_token:
                raise ImproperlyConfigured(
                    "Gmail OAuth credentials are invalid or cannot be refreshed. "
                    "Run `python manage.py configure_gmail_oauth` again."
                )
            credentials.refresh(Request())

        self._service = build(
            "gmail",
            "v1",
            credentials=credentials,
            cache_discovery=False,
        )
        return self._service

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        sender = getattr(settings, "GOOGLE_SENDER_EMAIL", "").strip()
        if not sender:
            raise ImproperlyConfigured(
                "GOOGLE_SENDER_EMAIL must be set to the Gmail account authorized "
                "by the OAuth setup command."
            )

        sent_count = 0
        for email_message in email_messages:
            try:
                email_message.from_email = sender
                raw_message = base64.urlsafe_b64encode(
                    email_message.message().as_bytes()
                ).decode("ascii")
                self._get_service().users().messages().send(
                    userId="me",
                    body={"raw": raw_message},
                ).execute()
                sent_count += 1
            except Exception:
                logger.exception("Gmail API failed to deliver an email message.")
                if not self.fail_silently:
                    raise

        return sent_count

    def close(self):
        self._service = None
