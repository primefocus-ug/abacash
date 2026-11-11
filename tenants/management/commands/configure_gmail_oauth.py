import os
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.core.exceptions import ValidationError


class Command(BaseCommand):
    help = "Authorize the platform Gmail sender once for automatic email delivery."

    def add_arguments(self, parser):
        parser.add_argument(
            "--client-secrets",
            required=True,
            help="Path to the downloaded Google OAuth Web client JSON file.",
        )
        parser.add_argument(
            "--sender-email",
            required=True,
            help="Gmail address that will send platform emails.",
        )
        parser.add_argument(
            "--port",
            type=int,
            default=8766,
            help="Local OAuth callback port; register its localhost URI in Google Cloud.",
        )
        parser.add_argument(
            "--env-file",
            default=str(settings.BASE_DIR / ".env"),
            help="Environment file to enable Gmail delivery after authorization.",
        )

    def handle(self, *args, **options):
        client_secrets = Path(options["client_secrets"]).expanduser().resolve()
        if not client_secrets.is_file():
            raise CommandError(f"OAuth client JSON file not found: {client_secrets}")

        sender_email = options["sender_email"].strip()
        try:
            validate_email(sender_email)
        except ValidationError as exc:
            raise CommandError("Enter a valid --sender-email address.") from exc

        from google_auth_oauthlib.flow import Flow

        callback_uri = f"http://localhost:{options['port']}/"
        self.stdout.write(
            "Before continuing, register this exact Authorized redirect URI in "
            f"Google Cloud: {callback_uri}"
        )
        self.stdout.write(
            "If the OAuth consent screen is in Testing, add this sender as a test user."
        )

        flow = Flow.from_client_secrets_file(
            str(client_secrets),
            scopes=["https://www.googleapis.com/auth/gmail.send"],
            redirect_uri=callback_uri,
        )
        credentials = flow.run_local_server(
            host="localhost",
            port=options["port"],
            open_browser=True,
            access_type="offline",
            prompt="consent",
        )
        if not credentials.refresh_token:
            raise CommandError(
                "Google did not return a refresh token. Revoke this app's existing "
                "access from the sender account and run the command again."
            )

        token_path = Path(settings.GOOGLE_OAUTH_TOKEN_FILE).expanduser().resolve()
        token_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=token_path.parent,
                prefix=".google-oauth-",
                suffix=".tmp",
                delete=False,
            ) as token_file:
                temporary_path = Path(token_file.name)
                token_file.write(credentials.to_json())
                token_file.write("\n")

            if os.name != "nt":
                temporary_path.chmod(0o600)
            os.replace(temporary_path, token_path)
        except OSError as exc:
            if temporary_path and temporary_path.exists():
                temporary_path.unlink()
            raise CommandError(f"Could not securely save the OAuth token file: {exc}") from exc

        env_path = Path(options["env_file"]).expanduser().resolve()
        self._update_env_file(
            env_path,
            {
                "EMAIL_PROVIDER": "gmail_api",
                "GOOGLE_SENDER_EMAIL": sender_email,
            },
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Gmail authorization saved. Restart Django and the Celery worker "
                "to use Gmail API for email delivery."
            )
        )

    @staticmethod
    def _update_env_file(env_path, updates):
        env_path.parent.mkdir(parents=True, exist_ok=True)
        lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
        output = []
        updated_keys = set()

        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in line:
                key = line.split("=", 1)[0].strip()
                if key in updates:
                    if key not in updated_keys:
                        output.append(f"{key}={updates[key]}")
                        updated_keys.add(key)
                    continue
            output.append(line)

        for key, value in updates.items():
            if key not in updated_keys:
                output.append(f"{key}={value}")

        env_path.write_text("\n".join(output) + "\n", encoding="utf-8")
