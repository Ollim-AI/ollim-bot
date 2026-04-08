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
"""Tests for google/calendar.py — multi-calendar, --calendar flag, calendars subcommand."""

import io
import sys
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from ollim_bot.google import calendar as cal_mod


@pytest.fixture()
def mock_service(monkeypatch):
    svc = MagicMock()
    monkeypatch.setattr(cal_mod, "_get_calendar_service", lambda: svc)
    return svc


@pytest.fixture()
def single_calendar(monkeypatch):
    """Configure a single calendar (default)."""
    monkeypatch.setattr(cal_mod, "_default_calendar_ids", lambda: ["primary"])


@pytest.fixture()
def multi_calendar(monkeypatch):
    """Configure two calendars."""
    monkeypatch.setattr(cal_mod, "_default_calendar_ids", lambda: ["primary", "work@group.calendar.google.com"])


def _capture(fn, *args, **kwargs):
    old = sys.stdout
    sys.stdout = buf = io.StringIO()
    fn(*args, **kwargs)
    sys.stdout = old
    return buf.getvalue()


def _make_event(event_id, summary, start_dt, end_dt=None, all_day=False):
    if all_day:
        return {
            "id": event_id,
            "summary": summary,
            "start": {"date": start_dt},
            "end": {"date": end_dt or start_dt},
        }
    return {
        "id": event_id,
        "summary": summary,
        "start": {"dateTime": start_dt},
        "end": {"dateTime": end_dt or start_dt},
    }


def _setup_events(mock_service, events):
    """Set up mock to return events for a single calendar query."""
    mock_service.events().list().execute.return_value = {
        "items": events,
        "nextPageToken": None,
    }


# --- multi-calendar merge + sort ---


class TestMultiCalendarEvents:
    def test_single_calendar_no_label(self, mock_service, single_calendar):
        events = [_make_event("e1", "Lunch", "2026-04-06T12:00:00-07:00", "2026-04-06T13:00:00-07:00")]
        _setup_events(mock_service, events)
        output = _capture(cal_mod._handle_events, 1, calendar_ids=["primary"])
        assert "Lunch" in output
        assert "[primary]" not in output

    def test_multi_calendar_adds_labels(self, mock_service, multi_calendar):
        events_primary = [_make_event("e1", "Lunch", "2026-04-06T12:00:00-07:00")]
        events_work = [_make_event("e2", "Standup", "2026-04-06T09:00:00-07:00")]

        mock_service.events().list().execute.side_effect = [
            {"items": events_primary, "nextPageToken": None},
            {"items": events_work, "nextPageToken": None},
        ]

        output = _capture(cal_mod._handle_events, 1, calendar_ids=["primary", "work@group.calendar.google.com"])
        assert "[primary]" in output
        assert "[work@group.calendar.google.com]" in output

    def test_multi_calendar_sorts_by_start_time(self, mock_service):
        events_primary = [_make_event("e1", "Lunch", "2026-04-06T12:00:00-07:00")]
        events_work = [_make_event("e2", "Standup", "2026-04-06T09:00:00-07:00")]

        mock_service.events().list().execute.side_effect = [
            {"items": events_primary, "nextPageToken": None},
            {"items": events_work, "nextPageToken": None},
        ]

        output = _capture(cal_mod._handle_events, 1, calendar_ids=["primary", "work"])
        lines = [line for line in output.strip().split("\n") if line.strip()]
        assert "Standup" in lines[0]
        assert "Lunch" in lines[1]

    def test_mixed_allday_and_timed_events_sort(self, mock_service):
        mock_service.events().list().execute.side_effect = [
            {
                "items": [_make_event("e1", "Meeting", "2026-04-06T14:00:00-07:00", "2026-04-06T15:00:00-07:00")],
                "nextPageToken": None,
            },
            {"items": [_make_event("e2", "Holiday", "2026-04-06", all_day=True)], "nextPageToken": None},
        ]

        output = _capture(cal_mod._handle_events, 1, calendar_ids=["primary", "work"])
        lines = [line for line in output.strip().split("\n") if line.strip()]
        assert "Holiday" in lines[0]
        assert "Meeting" in lines[1]


# --- bad calendar ID ---


class TestBadCalendarId:
    def test_skips_bad_calendar_with_warning(self, mock_service):
        resp = MagicMock()
        resp.status = 404
        mock_service.events().list().execute.side_effect = HttpError(resp, b"not found")

        output = _capture(cal_mod._handle_events, 1, calendar_ids=["badid"])
        assert "not found" in output
        assert "skipped" in output


# --- calendars subcommand ---


class TestCalendarsSubcommand:
    def test_lists_calendars(self, mock_service):
        mock_service.calendarList().list().execute.return_value = {
            "items": [
                {"id": "primary", "summary": "My Calendar"},
                {"id": "work@group.calendar.google.com", "summary": "Work"},
            ]
        }
        output = _capture(cal_mod._handle_calendars)
        assert "primary" in output
        assert "My Calendar" in output
        assert "work@group.calendar.google.com" in output
        assert "Work" in output


# --- delete_event with calendar_id ---


class TestDeleteEvent:
    def test_uses_provided_calendar_id(self, mock_service):
        mock_service.events().get().execute.return_value = {"summary": "Test"}
        cal_mod.delete_event("eid", calendar_id="work")
        mock_service.events().get.assert_called_with(calendarId="work", eventId="eid")
        mock_service.events().delete.assert_called_with(calendarId="work", eventId="eid")

    def test_defaults_to_primary(self, mock_service):
        mock_service.events().get().execute.return_value = {"summary": "Test"}
        cal_mod.delete_event("eid")
        mock_service.events().get.assert_called_with(calendarId="primary", eventId="eid")


# --- no events ---


class TestNoEvents:
    def test_no_events_message(self, mock_service):
        _setup_events(mock_service, [])
        output = _capture(cal_mod._handle_events, 1, calendar_ids=["primary"])
        assert "no events" in output
