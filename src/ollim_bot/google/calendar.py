"""CLI handler for `ollim-bot cal` subcommand."""

import argparse
import os
import sys
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ollim_bot.config import _detect_local_tz
from ollim_bot.google.auth import get_service

TZ = ZoneInfo(os.environ.get("OLLIM_TIMEZONE") or _detect_local_tz())


def _get_calendar_service() -> Any:
    return get_service("calendar", "v3")


def run_calendar_command(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="ollim-bot cal")
    sub = parser.add_subparsers(dest="action")

    sub.add_parser("today", help="Show today's events")

    up_p = sub.add_parser("upcoming", help="Show upcoming events")
    up_p.add_argument("--days", type=int, default=7, help="Number of days (default 7)")

    add_p = sub.add_parser("add", help="Create an event")
    add_p.add_argument("summary", help="Event title")
    add_p.add_argument("--start", required=True, help="Start: YYYY-MM-DDTHH:MM")
    add_p.add_argument("--end", required=True, help="End: YYYY-MM-DDTHH:MM")
    add_p.add_argument("--description", help="Event description")

    show_p = sub.add_parser("show", help="Show event details")
    show_p.add_argument("id", help="Event ID")

    del_p = sub.add_parser("delete", help="Delete an event")
    del_p.add_argument("id", help="Event ID")

    upd_p = sub.add_parser("update", help="Update an event")
    upd_p.add_argument("id", help="Event ID")
    upd_p.add_argument("--summary", help="New title")
    upd_p.add_argument("--start", help="New start: YYYY-MM-DDTHH:MM")
    upd_p.add_argument("--end", help="New end: YYYY-MM-DDTHH:MM")
    upd_p.add_argument("--description", help="New description")

    args = parser.parse_args(argv)

    if args.action == "today":
        _handle_events(days=1)
    elif args.action == "upcoming":
        _handle_events(days=args.days)
    elif args.action == "add":
        _handle_add(args)
    elif args.action == "show":
        _handle_show(args.id)
    elif args.action == "delete":
        _handle_delete(args.id)
    elif args.action == "update":
        _handle_update(args)
    else:
        parser.print_help()
        sys.exit(1)


def _handle_events(days: int) -> None:
    now = datetime.now(TZ)
    time_min = now.replace(hour=0, minute=0, second=0, microsecond=0)
    time_max = time_min + timedelta(days=days)

    service = _get_calendar_service()
    events: list[dict] = []
    page_token = None

    while True:
        result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=time_min.isoformat(),
                timeMax=time_max.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                pageToken=page_token,
            )
            .execute()
        )
        events.extend(result.get("items", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            break

    if not events:
        print("no events")
        return

    for e in events:
        print(f"  {e['id']}  {_fmt_event(e)}")


def _fmt_event(event: dict) -> str:
    start = event.get("start", {})
    summary = event.get("summary", "(no title)")

    if "dateTime" in start:
        s = datetime.fromisoformat(start["dateTime"])
        end = event.get("end", {})
        e = datetime.fromisoformat(end["dateTime"]) if "dateTime" in end else s
        return f"{s.strftime('%Y-%m-%d')}  {s.strftime('%H:%M')}-{e.strftime('%H:%M')}  {summary}"

    date = start.get("date", "????-??-??")
    return f"{date}  (all-day)     {summary}"


def _parse_dt(value: str) -> str:
    """Naive datetimes are treated as PT; Google Calendar requires timezone-aware ISO 8601."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.isoformat()


def _handle_show(event_id: str) -> None:
    service = _get_calendar_service()
    e = service.events().get(calendarId="primary", eventId=event_id).execute()

    print(f"title:       {e.get('summary', '(no title)')}")
    print(f"when:        {_fmt_event(e)}")
    if e.get("location"):
        print(f"location:    {e['location']}")
    if e.get("description"):
        print(f"description: {e['description']}")
    if e.get("htmlLink"):
        print(f"link:        {e['htmlLink']}")
    attendees = e.get("attendees", [])
    if attendees:
        names = [a.get("email", "") for a in attendees]
        print(f"attendees:   {', '.join(names)}")
    print(f"status:      {e.get('status', 'unknown')}")
    print(f"id:          {e['id']}")


def _handle_add(args: argparse.Namespace) -> None:
    body: dict = {
        "summary": args.summary,
        "start": {"dateTime": _parse_dt(args.start), "timeZone": str(TZ)},
        "end": {"dateTime": _parse_dt(args.end), "timeZone": str(TZ)},
    }
    if args.description:
        body["description"] = args.description

    service = _get_calendar_service()
    event = service.events().insert(calendarId="primary", body=body).execute()
    print(f"created {event['id']}: {args.summary}")


def delete_event(event_id: str) -> str:
    """Delete a calendar event and return its summary."""
    service = _get_calendar_service()
    event = service.events().get(calendarId="primary", eventId=event_id).execute()
    summary = event.get("summary", event_id)
    service.events().delete(calendarId="primary", eventId=event_id).execute()
    return summary


def _handle_delete(event_id: str) -> None:
    delete_event(event_id)
    print(f"deleted {event_id}")


def _handle_update(args: argparse.Namespace) -> None:
    body: dict = {}
    if args.summary is not None:
        body["summary"] = args.summary
    if args.start is not None:
        body["start"] = {
            "dateTime": _parse_dt(args.start),
            "timeZone": str(TZ),
        }
    if args.end is not None:
        body["end"] = {
            "dateTime": _parse_dt(args.end),
            "timeZone": str(TZ),
        }
    if args.description is not None:
        body["description"] = args.description
    if not body:
        print("error: provide at least one of --summary, --start, --end, --description")
        sys.exit(1)

    service = _get_calendar_service()
    service.events().patch(calendarId="primary", eventId=args.id, body=body).execute()
    print(f"updated {args.id}")
