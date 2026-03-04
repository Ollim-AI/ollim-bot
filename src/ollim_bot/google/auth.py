"""Shared Google OAuth2 credentials for Tasks + Calendar APIs.

Add new scopes to SCOPES when integrating additional Google services.
After adding scopes, delete ~/.ollim-bot/state/token.json to re-consent.
"""

import asyncio
import concurrent.futures
import sys
import threading
import time
import wsgiref.simple_server
from collections.abc import Callable
from typing import Any

from google.auth.exceptions import RefreshError
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
_REVOKED_MARKER = STATE_DIR / "google_auth_revoked"


class _SilentHandler(wsgiref.simple_server.WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


def get_credentials() -> Credentials:
    """First run opens a browser for consent. Subsequent runs use token.json."""
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as exc:
            if not exc.retryable:  # invalid_grant: token permanently revoked
                TOKEN_FILE.unlink(missing_ok=True)
                _REVOKED_MARKER.touch()
            raise
        TOKEN_FILE.write_text(creds.to_json())
        return creds

    if not CREDENTIALS_FILE.exists():
        print(f"Google credentials not found at {CREDENTIALS_FILE}", file=sys.stderr)
        print("To set up Google integration:", file=sys.stderr)
        print("  1. Go to https://console.cloud.google.com/", file=sys.stderr)
        print("  2. Create OAuth credentials (Desktop application type)", file=sys.stderr)
        print(f"  3. Save the JSON file to {CREDENTIALS_FILE}", file=sys.stderr)
        raise SystemExit(1)
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
    creds = flow.run_local_server(port=0, bind_addr="127.0.0.1")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(creds.to_json())
    return creds


def get_service(api: str, version: str) -> Resource:
    """Credentials are obtained (and refreshed) on every call via get_credentials()."""
    return _build(api, version, credentials=get_credentials())


def is_google_connected() -> bool:
    """True if a Google token exists that doesn't require a new consent flow.

    Does not attempt a network refresh — a stale token that can refresh still
    returns True; actual refresh happens lazily via get_credentials().
    """
    if not TOKEN_FILE.exists():
        return False
    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    return bool(creds.valid or (creds.expired and creds.refresh_token))


def check_and_clear_revoked() -> bool:
    """Return True and delete the marker if a token revocation was detected.

    Written by get_credentials() on non-retryable RefreshError (invalid_grant).
    Consumed by the scheduler to trigger a user-facing ping.
    """
    if not _REVOKED_MARKER.exists():
        return False
    _REVOKED_MARKER.unlink(missing_ok=True)
    return True


async def start_google_auth_flow() -> tuple[str, Callable[[str], None], asyncio.Future[None]]:
    """Start the Google OAuth flow without blocking the event loop.

    Returns (auth_url, complete_from_paste, future).
    - auth_url: Google OAuth URL to show the user.
    - complete_from_paste: call with the query string parsed from a pasted
      redirect URL to complete auth from a different device.
    - future: resolves to None on success, raises TimeoutError (5 min) or
      another exception on failure. Caller is responsible for awaiting it.
    """
    loop = asyncio.get_running_loop()
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)

    _done = threading.Event()
    _lock = threading.Lock()
    captured: dict[str, str | None] = {"query": None}

    def _complete(query_string: str) -> None:
        """First-write-wins: whichever path arrives first (browser or paste) wins."""
        with _lock:
            if captured["query"] is None:
                captured["query"] = query_string
                _done.set()

    def _app(environ: dict[str, Any], start_response: Any) -> list[bytes]:
        _complete(environ.get("QUERY_STRING", ""))
        start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
        return [b"<html><body><p>Auth complete. You may close this window.</p></body></html>"]

    server = wsgiref.simple_server.make_server("127.0.0.1", 0, _app, handler_class=_SilentHandler)
    server.timeout = 1  # short poll so _serve() responds quickly to complete_from_paste

    flow.redirect_uri = f"http://127.0.0.1:{server.server_port}"
    auth_url, _ = flow.authorization_url(access_type="offline")

    def complete_from_paste(query_string: str) -> None:
        _complete(query_string)

    def _serve() -> None:
        deadline = time.monotonic() + 300
        try:
            while not _done.is_set() and time.monotonic() < deadline:
                server.handle_request()
            if captured["query"] is None:
                raise TimeoutError("google auth timed out")
            if "error=" in captured["query"]:
                raise ValueError(f"google auth error: {captured['query']}")
            # oauthlib requires https in authorization_response
            base = f"https://127.0.0.1:{server.server_port}"
            flow.fetch_token(authorization_response=f"{base}?{captured['query']}")
            TOKEN_FILE.write_text(flow.credentials.to_json())
        finally:
            server.server_close()

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    cf_future = executor.submit(_serve)
    executor.shutdown(wait=False)  # release pool resources; thread runs to completion
    return auth_url, complete_from_paste, asyncio.wrap_future(cf_future, loop=loop)
