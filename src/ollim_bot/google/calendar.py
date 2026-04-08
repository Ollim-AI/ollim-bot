# ollim-bot
# Copyright (C) 2025-2026 Julius Frost
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""CLI handler for `ollim-bot cal` subcommand."""

import argparse
import sys
from datetime import datetime, timedelta
from typing import Any

from googleapiclient.errors import HttpError

from ollim_bot import runtime_config
from ollim_bot.config import TZ
from ollim_bot.google.auth import get_service


def _get_calendar_service() -> Any:
    return get_service("calendar", "v3")


def _default_calendar_ids() -> list[str]:
    raw = runtime_config.load().google_calendars
    return [c.strip() for c in raw.split(",") if c.strip()]


def _default_calendar_id() -> str:
    """First configured calendar — used as default for write operations."""
    return _default_calendar_ids()[0]


def run_calendar_command(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="ollim-bot cal")
    sub = parser.add_subparsers(dest="action")

    today_p = sub.add_parser("today", help="Show today's events")
    today_p.add_argument("--calendar", help="Calendar ID (default: all configured)")

    up_p = sub.add_parser("upcoming", help="Show upcoming events")
    up_p.add_argument("--days", type=int, default=7, help="Number of days (default 7)")
    up_p.add_argument("--calendar", help="Calendar ID (default: all configured)")

    add_p = sub.add_parser("add", help="Create an event")
    add_p.add_argument("summary", help="Event title")
    add_p.add_argument("--start", required=True, help="Start: YYYY-MM-DDTHH:MM")
    add_p.add_argument("--end", required=True, help="End: YYYY-MM-DDTHH:MM")
    add_p.add_argument("--description", help="Event description")
    add_p.add_argument("--calendar", help="Calendar ID (default: first configured)")

    show_p = sub.add_parser("show", help="Show event details")
    show_p.add_argument("id", help="Event ID")
    show_p.add_argument("--calendar", help="Calendar ID (default: first configured)")

    del_p = sub.add_parser("delete", help="Delete an event")
    del_p.add_argument("id", help="Event ID")
    del_p.add_argument("--calendar", help="Calendar ID (default: first configured)")

    upd_p = sub.add_parser("update", help="Update an event")
    upd_p.add_argument("id", help="Event ID")
    upd_p.add_argument("--summary", help="New title")
    upd_p.add_argument("--start", help="New start: YYYY-MM-DDTHH:MM")
    upd_p.add_argument("--end", help="New end: YYYY-MM-DDTHH:MM")
    upd_p.add_argument("--description", help="New description")
    upd_p.add_argument("--calendar", help="Calendar ID (default: first configured)")

    sub.add_parser("calendars", help="List available calendars")

    args = parser.parse_args(argv)

    cal_flag = getattr(args, "calendar", None)
    cal_ids = [cal_flag] if cal_flag else None
    cal_id = cal_flag or _default_calendar_id()

    if args.action == "today":
        _handle_events(days=1, calendar_ids=cal_ids)
    elif args.action == "upcoming":
        _handle_events(days=args.days, calendar_ids=cal_ids)
    elif args.action == "add":
        _handle_add(args, calendar_id=cal_id)
    elif args.action == "show":
        _handle_show(args.id, calendar_id=cal_id)
    elif args.action == "delete":
        _handle_delete(args.id, calendar_id=cal_id)
    elif args.action == "update":
        _handle_update(args, calendar_id=cal_id)
    elif args.action == "calendars":
        _handle_calendars()
    else:
        parser.print_help()
        sys.exit(1)


def _event_sort_key(event: dict) -> datetime:
    """Normalize start time for sorting — handles both timed and all-day events."""
    start = event.get("start", {})
    if "dateTime" in start:
        return datetime.fromisoformat(start["dateTime"])
    date_str = start.get("date", "1970-01-01")
    return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=TZ)


def _handle_events(days: int, calendar_ids: list[str] | None = None) -> None:
    if calendar_ids is None:
        calendar_ids = _default_calendar_ids()

    multi = len(calendar_ids) > 1
    now = datetime.now(TZ)
    time_min = now.replace(hour=0, minute=0, second=0, microsecond=0)
    time_max = time_min + timedelta(days=days)

    service = _get_calendar_service()
    all_events: list[dict] = []

    for cal_id in calendar_ids:
        try:
            page_token = None
            while True:
                result = (
                    service.events()
                    .list(
                        calendarId=cal_id,
                        timeMin=time_min.isoformat(),
                        timeMax=time_max.isoformat(),
                        singleEvents=True,
                        orderBy="startTime",
                        pageToken=page_token,
                    )
                    .execute()
                )
                for item in result.get("items", []):
                    item["_calendar_id"] = cal_id
                all_events.extend(result.get("items", []))
                page_token = result.get("nextPageToken")
                if not page_token:
                    break
        except HttpError as e:
            if e.resp.status == 404:
                print(f"  (calendar '{cal_id}' not found — skipped)")
            else:
                raise

    if not all_events:
        print("no events")
        return

    if multi:
        all_events.sort(key=_event_sort_key)

    for e in all_events:
        label = f"  [{e['_calendar_id']}]" if multi else ""
        print(f"  {e['id']}  {_fmt_event(e)}{label}")


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


def _handle_show(event_id: str, calendar_id: str = "primary") -> None:
    service = _get_calendar_service()
    e = service.events().get(calendarId=calendar_id, eventId=event_id).execute()

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


def _handle_add(args: argparse.Namespace, calendar_id: str = "primary") -> None:
    body: dict = {
        "summary": args.summary,
        "start": {"dateTime": _parse_dt(args.start), "timeZone": str(TZ)},
        "end": {"dateTime": _parse_dt(args.end), "timeZone": str(TZ)},
    }
    if args.description:
        body["description"] = args.description

    service = _get_calendar_service()
    event = service.events().insert(calendarId=calendar_id, body=body).execute()
    print(f"created {event['id']}: {args.summary}")


def delete_event(event_id: str, calendar_id: str = "primary") -> str:
    """Delete a calendar event and return its summary."""
    service = _get_calendar_service()
    event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
    summary = event.get("summary", event_id)
    service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
    return summary


def _handle_delete(event_id: str, calendar_id: str = "primary") -> None:
    delete_event(event_id, calendar_id=calendar_id)
    print(f"deleted {event_id}")


def _handle_update(args: argparse.Namespace, calendar_id: str = "primary") -> None:
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
    service.events().patch(calendarId=calendar_id, eventId=args.id, body=body).execute()
    print(f"updated {args.id}")


def _handle_calendars() -> None:
    service = _get_calendar_service()
    result = service.calendarList().list().execute()
    calendars = result.get("items", [])
    if not calendars:
        print("no calendars found")
        return
    for cal in calendars:
        cal_id = cal.get("id", "")
        summary = cal.get("summaryOverride") or cal.get("summary", "")
        print(f"  {cal_id:<40s}{summary}")
