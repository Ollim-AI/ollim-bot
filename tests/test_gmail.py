"""Tests for google/gmail.py CLI handler."""

import base64
import io
import sys
from unittest.mock import MagicMock

import pytest

from ollim_bot.google import gmail


@pytest.fixture()
def mock_service(monkeypatch):
    """Patch _get_gmail_service and return the mock service."""
    svc = MagicMock()
    monkeypatch.setattr(gmail, "_get_gmail_service", lambda: svc)
    return svc


def _capture(fn, *args):
    old = sys.stdout
    sys.stdout = buf = io.StringIO()
    fn(*args)
    sys.stdout = old
    return buf.getvalue()


# --- query construction (category:primary filtering) ---


def _setup_empty_list(mock_service):
    mock_service.users().messages().list().execute.return_value = {"messages": []}


def _last_list_query(mock_service) -> str:
    """Extract the `q=` kwarg from the most recent messages().list() call."""
    return mock_service.users().messages().list.call_args.kwargs["q"]


class TestUnreadQuery:
    def test_default_filters_primary(self, mock_service):
        _setup_empty_list(mock_service)
        _capture(gmail.run_gmail_command, ["unread"])
        assert _last_list_query(mock_service) == "is:unread category:primary"

    def test_all_flag_removes_filter(self, mock_service):
        _setup_empty_list(mock_service)
        _capture(gmail.run_gmail_command, ["unread", "--all"])
        assert _last_list_query(mock_service) == "is:unread"


class TestSearchQuery:
    def test_default_appends_primary(self, mock_service):
        _setup_empty_list(mock_service)
        _capture(gmail.run_gmail_command, ["search", "from:alice"])
        assert _last_list_query(mock_service) == "from:alice category:primary"

    def test_all_flag_passes_raw_query(self, mock_service):
        _setup_empty_list(mock_service)
        _capture(gmail.run_gmail_command, ["search", "from:alice", "--all"])
        assert _last_list_query(mock_service) == "from:alice"


# --- pure helpers ---


class TestShortSender:
    def test_name_and_email(self):
        assert gmail._short_sender("Alice Smith <alice@example.com>") == "Alice Smith"

    def test_quoted_name(self):
        assert gmail._short_sender('"Bob Jones" <bob@example.com>') == "Bob Jones"

    def test_plain_email(self):
        assert gmail._short_sender("alice@example.com") == "alice@example.com"


class TestFmtDate:
    def test_empty(self):
        assert "(no date)" in gmail._fmt_date("")

    def test_epoch_ms(self):
        result = gmail._fmt_date("1700000000000")
        assert "2023-11-14" in result


class TestDecodeBody:
    def test_plain_text(self):
        encoded = base64.urlsafe_b64encode(b"hello world").decode()
        payload = {"mimeType": "text/plain", "body": {"data": encoded}}
        assert gmail._decode_body(payload, "text/plain") == "hello world"

    def test_nested_parts(self):
        encoded = base64.urlsafe_b64encode(b"nested").decode()
        payload = {
            "mimeType": "multipart/alternative",
            "parts": [{"mimeType": "text/plain", "body": {"data": encoded}}],
        }
        assert gmail._decode_body(payload, "text/plain") == "nested"

    def test_no_match(self):
        payload = {"mimeType": "text/html", "body": {"data": ""}}
        assert gmail._decode_body(payload, "text/plain") == ""


class TestExtractTextBody:
    def test_prefers_plain(self):
        plain = base64.urlsafe_b64encode(b"plain text").decode()
        html = base64.urlsafe_b64encode(b"<p>html</p>").decode()
        payload = {
            "mimeType": "multipart/alternative",
            "parts": [
                {"mimeType": "text/plain", "body": {"data": plain}},
                {"mimeType": "text/html", "body": {"data": html}},
            ],
        }
        assert gmail._extract_text_body(payload) == "plain text"

    def test_falls_back_to_html(self):
        html = base64.urlsafe_b64encode(b"<p>hello</p>").decode()
        payload = {
            "mimeType": "multipart/alternative",
            "parts": [
                {"mimeType": "text/html", "body": {"data": html}},
            ],
        }
        assert "hello" in gmail._extract_text_body(payload)

    def test_strips_style_tags(self):
        html = base64.urlsafe_b64encode(b"<style>.x{color:red}</style><p>content</p>").decode()
        payload = {"mimeType": "text/html", "body": {"data": html}}
        result = gmail._extract_text_body(payload)
        assert "color" not in result
        assert "content" in result
