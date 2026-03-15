"""Tests for reminder_tools.py — add, list, cancel MCP tool handlers."""

import asyncio
from datetime import datetime, timedelta

from ollim_bot.config import TZ
from ollim_bot.reminder_tools import add_reminder, cancel_reminder, list_reminders_tool
from ollim_bot.scheduling.reminders import Reminder

_add = add_reminder.handler
_list = list_reminders_tool.handler
_cancel = cancel_reminder.handler


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _text(result: dict) -> str:
    return result["content"][0]["text"]


# --- add_reminder validation ---


def test_add_both_delay_and_run_at():
    result = _run(_add({"prompt": "x", "delay_minutes": 30, "run_at": "2099-01-01T00:00"}))

    assert "Error" in _text(result)
    assert "delay_minutes OR run_at, not both" in _text(result)


def test_add_neither_delay_nor_run_at():
    result = _run(_add({"prompt": "x"}))

    assert "Error" in _text(result)
    assert "provide either delay_minutes or run_at" in _text(result)


def test_add_invalid_iso_datetime():
    result = _run(_add({"prompt": "x", "run_at": "not-a-date"}))

    assert "Error" in _text(result)
    assert "invalid ISO datetime" in _text(result)


def test_add_run_at_in_the_past():
    past = (datetime.now(TZ) - timedelta(hours=1)).isoformat()

    result = _run(_add({"prompt": "x", "run_at": past}))

    assert "Error" in _text(result)
    assert "run_at is in the past" in _text(result)


# --- add_reminder success paths ---


def test_add_with_delay_minutes(monkeypatch):
    captured = []
    monkeypatch.setattr("ollim_bot.reminder_tools.append_reminder", captured.append)

    result = _run(_add({"prompt": "check email", "delay_minutes": 30}))

    assert len(captured) == 1
    r = captured[0]
    assert r.message == "check email"
    assert r.background is True
    assert "set for" in _text(result)
    assert r.id in _text(result)


def test_add_with_run_at_future(monkeypatch):
    captured = []
    monkeypatch.setattr("ollim_bot.reminder_tools.append_reminder", captured.append)
    future = (datetime.now(TZ) + timedelta(hours=2)).isoformat()

    result = _run(_add({"prompt": "meeting", "run_at": future}))

    assert len(captured) == 1
    assert "set for" in _text(result)


def test_add_run_at_without_timezone_uses_bot_tz(monkeypatch):
    captured = []
    monkeypatch.setattr("ollim_bot.reminder_tools.append_reminder", captured.append)
    naive = (datetime.now(TZ) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")

    result = _run(_add({"prompt": "test tz", "run_at": naive}))

    assert len(captured) == 1
    assert "set for" in _text(result)
    # The reminder's run_at should have timezone info (inherited from TZ)
    run_at_dt = datetime.fromisoformat(captured[0].run_at)
    assert run_at_dt.tzinfo is not None


def test_add_foreground_true(monkeypatch):
    captured = []
    monkeypatch.setattr("ollim_bot.reminder_tools.append_reminder", captured.append)

    _run(_add({"prompt": "watch me work", "delay_minutes": 5, "foreground": True}))

    assert captured[0].background is False


def test_add_max_chain_and_description(monkeypatch):
    captured = []
    monkeypatch.setattr("ollim_bot.reminder_tools.append_reminder", captured.append)

    _run(
        _add(
            {
                "prompt": "follow up",
                "delay_minutes": 10,
                "max_chain": 3,
                "description": "daily check",
            }
        )
    )

    r = captured[0]
    assert r.max_chain == 3
    assert r.description == "daily check"


# --- list_reminders_tool ---


def test_list_empty(monkeypatch):
    monkeypatch.setattr("ollim_bot.reminder_tools._list_reminders", lambda: [])

    result = _run(_list({}))

    assert _text(result) == "No pending reminders."


def test_list_multiple_sorted(monkeypatch):
    r1 = Reminder.new(message="first", delay_minutes=60, background=True, description="alpha")
    r2 = Reminder.new(message="second", delay_minutes=10, background=False, description="beta")
    monkeypatch.setattr("ollim_bot.reminder_tools._list_reminders", lambda: [r1, r2])

    result = _run(_list({}))
    text = _text(result)
    lines = text.strip().split("\n")

    assert len(lines) == 2
    # r2 fires sooner, should be first
    assert r2.id in lines[0]
    assert "[fg]" in lines[0]
    assert "beta" in lines[0]
    assert r1.id in lines[1]
    assert "[bg]" in lines[1]
    assert "alpha" in lines[1]


def test_list_no_description(monkeypatch):
    r = Reminder.new(message="bare", delay_minutes=5, description="")
    monkeypatch.setattr("ollim_bot.reminder_tools._list_reminders", lambda: [r])

    result = _run(_list({}))

    assert "(no description)" in _text(result)


# --- cancel_reminder ---


def test_cancel_existing(monkeypatch):
    monkeypatch.setattr("ollim_bot.reminder_tools.remove_reminder", lambda rid: True)

    result = _run(_cancel({"reminder_id": "abc123"}))

    assert "abc123 cancelled" in _text(result)


def test_cancel_unknown(monkeypatch):
    monkeypatch.setattr("ollim_bot.reminder_tools.remove_reminder", lambda rid: False)

    result = _run(_cancel({"reminder_id": "nope"}))

    assert "Error" in _text(result)
    assert "no reminder found" in _text(result)
