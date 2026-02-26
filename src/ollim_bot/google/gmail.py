"""CLI handler for `ollim-bot gmail` subcommand."""

import argparse
import base64
import os
import re
import sys
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ollim_bot.config import _detect_local_tz
from ollim_bot.google.auth import get_service

TZ = ZoneInfo(os.environ.get("OLLIM_TIMEZONE") or _detect_local_tz())


def _get_gmail_service() -> Any:
    return get_service("gmail", "v1")


def run_gmail_command(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="ollim-bot gmail")
    sub = parser.add_subparsers(dest="action")

    unread_p = sub.add_parser("unread", help="List unread emails")
    unread_p.add_argument("--max", type=int, default=20, help="Max results (default 20)")

    read_p = sub.add_parser("read", help="Read an email by ID")
    read_p.add_argument("id", help="Message ID")

    search_p = sub.add_parser("search", help="Search emails")
    search_p.add_argument("query", help="Gmail search query")
    search_p.add_argument("--max", type=int, default=20, help="Max results (default 20)")

    sub.add_parser("labels", help="List labels")

    args = parser.parse_args(argv)

    if args.action == "unread":
        _handle_list(query="is:unread", max_results=args.max)
    elif args.action == "read":
        _handle_read(args.id)
    elif args.action == "search":
        _handle_list(query=args.query, max_results=args.max)
    elif args.action == "labels":
        _handle_labels()
    else:
        parser.print_help()
        sys.exit(1)


def _handle_list(query: str, max_results: int) -> None:
    service = _get_gmail_service()
    result = (
        service.users()
        .messages()
        .list(
            userId="me",
            q=query,
            maxResults=max_results,
        )
        .execute()
    )

    messages = result.get("messages", [])
    if not messages:
        print("no messages")
        return

    for msg_stub in messages:
        msg = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=msg_stub["id"],
                format="metadata",
                metadataHeaders=["From", "Subject"],
            )
            .execute()
        )
        headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
        sender = _short_sender(headers.get("From", "(unknown)"))
        subject = headers.get("Subject", "(no subject)")
        date = _fmt_date(msg.get("internalDate", ""))
        print(f"  {msg['id']}  {date}  {sender}  {subject}")


def _fmt_date(internal_date: str) -> str:
    """Convert Gmail internalDate (epoch ms) to readable PT string."""
    if not internal_date:
        return "(no date)    "
    dt = datetime.fromtimestamp(int(internal_date) / 1000, tz=TZ)
    return dt.strftime("%Y-%m-%d %H:%M")


def _short_sender(from_header: str) -> str:
    """Extract display name from 'Name <email>' format."""
    if "<" in from_header:
        return from_header.split("<")[0].strip().strip('"')
    return from_header


def _decode_body(payload: dict, mime_type: str) -> str:
    mime = payload.get("mimeType", "")

    if mime == mime_type and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        text = _decode_body(part, mime_type)
        if text:
            return text

    return ""


def _extract_text_body(payload: dict) -> str:
    """Prefers text/plain; falls back to text/html with inline styles and tags stripped."""
    text = _decode_body(payload, "text/plain")
    if text:
        return text

    html = _decode_body(payload, "text/html")
    if html:
        clean = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
        clean = re.sub(r"<[^>]+>", " ", clean)
        clean = re.sub(r" +", " ", clean)
        return clean.strip()

    return ""


def _handle_read(msg_id: str) -> None:
    service = _get_gmail_service()
    msg = (
        service.users()
        .messages()
        .get(
            userId="me",
            id=msg_id,
            format="full",
        )
        .execute()
    )

    headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
    print(f"from:    {headers.get('From', '(unknown)')}")
    print(f"to:      {headers.get('To', '(unknown)')}")
    print(f"date:    {_fmt_date(msg.get('internalDate', ''))}")
    print(f"subject: {headers.get('Subject', '(no subject)')}")
    print()

    body = _extract_text_body(msg["payload"])
    if body:
        if len(body) > 3000:
            body = body[:3000] + "\n... (truncated)"
        print(body)
    else:
        print("(no text body)")


def _handle_labels() -> None:
    service = _get_gmail_service()
    result = service.users().labels().list(userId="me").execute()
    for label in result.get("labels", []):
        print(f"  {label['id']}  {label['name']}")
