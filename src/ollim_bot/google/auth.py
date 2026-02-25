"""Shared Google OAuth2 credentials for Tasks + Calendar APIs.

Add new scopes to SCOPES when integrating additional Google services.
After adding scopes, delete ~/.ollim-bot/state/token.json to re-consent.
"""

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource
from googleapiclient.discovery import build as _build

from ollim_bot.storage import STATE_DIR

SCOPES = [
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.readonly",
]

CREDENTIALS_FILE = STATE_DIR / "credentials.json"
TOKEN_FILE = STATE_DIR / "token.json"


def get_credentials() -> Credentials:
    """First run opens a browser for consent. Subsequent runs use token.json."""
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json())
        return creds

    assert CREDENTIALS_FILE.exists(), (
        f"Missing {CREDENTIALS_FILE} -- download OAuth client credentials "
        "from Google Cloud Console and save at that path"
    )
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
    creds = flow.run_local_server(port=0, bind_addr="127.0.0.1")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(creds.to_json())
    return creds


def get_service(api: str, version: str) -> Resource:
    """Credentials are obtained (and refreshed) on every call via get_credentials()."""
    return _build(api, version, credentials=get_credentials())
