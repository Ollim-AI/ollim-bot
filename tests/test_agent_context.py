"""Tests for ollim_bot.agent_context — timestamps, durations, thinking config."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

import pytest
from claude_agent_sdk import ResultMessage

from ollim_bot.agent_context import (
    _format_duration,
    format_compact_stats,
    prepend_context,
    relative_time,
    thinking,
    thinking_mode,
    timestamp,
)
from ollim_bot.config import TZ
from ollim_bot.forks import PendingUpdate

TS_RE = r"\[\d{4}-\d{2}-\d{2} \w{3} \d{2}:\d{2} [AP]M PT\]"


# -- _format_duration --


def test_format_duration_zero():
    assert _format_duration(0) == "< 1m"


def test_format_duration_under_minute():
    assert _format_duration(45) == "< 1m"


def test_format_duration_exact_minutes():
    assert _format_duration(300) == "5m"


def test_format_duration_hours_and_minutes():
    assert _format_duration(3720) == "1h 2m"


def test_format_duration_exact_hours():
    assert _format_duration(7200) == "2h"


# -- timestamp --


def test_timestamp_format():
    ts = timestamp()
    assert re.match(TS_RE, ts)


# -- relative_time --


def test_relative_time_just_now():
    now = datetime.now(TZ).isoformat()
    assert relative_time(now) == "just now"


def test_relative_time_minutes_ago():
    five_min_ago = (datetime.now(TZ) - timedelta(minutes=5)).isoformat()
    assert relative_time(five_min_ago) == "5m ago"


def test_relative_time_hours_ago():
    three_hours_ago = (datetime.now(TZ) - timedelta(hours=3)).isoformat()
    assert relative_time(three_hours_ago) == "3h ago"


def test_relative_time_days_ago():
    two_days_ago = (datetime.now(TZ) - timedelta(days=2)).isoformat()
    assert relative_time(two_days_ago) == "2d ago"


# -- thinking_mode --


def test_thinking_mode_enabled():
    assert thinking_mode(True) == "adaptive"


def test_thinking_mode_disabled():
    assert thinking_mode(False) == "off"


# -- thinking --


def test_thinking_off():
    assert thinking("off") == {"type": "disabled"}


def test_thinking_adaptive():
    assert thinking("adaptive") == {"type": "adaptive"}


def test_thinking_budget():
    assert thinking("8000") == {"type": "enabled", "budget_tokens": 8000}


# -- format_compact_stats --


def test_format_compact_stats_none_inputs():
    assert format_compact_stats(None, None) == ""


def test_format_compact_stats_with_result_and_session(monkeypatch):
    start = datetime.now(TZ) - timedelta(hours=1, minutes=2)
    monkeypatch.setattr("ollim_bot.agent_context.session_start_time", lambda: start)

    result = ResultMessage(
        subtype="result",
        duration_ms=0,
        duration_api_ms=0,
        is_error=False,
        num_turns=5,
        session_id="test",
        stop_reason="end_turn",
    )
    stats = format_compact_stats(result, None)
    assert "5 turns" in stats
    assert "1h 2m" in stats


def test_format_compact_stats_with_pre_tokens(monkeypatch):
    monkeypatch.setattr("ollim_bot.agent_context.session_start_time", lambda: None)

    stats = format_compact_stats(None, 50000)
    assert "50k tokens compacted" in stats


# -- prepend_context --


@pytest.mark.asyncio
async def test_prepend_context_no_updates(monkeypatch):
    async def no_updates():
        return []

    monkeypatch.setattr("ollim_bot.forks.pop_pending_updates", no_updates)

    result = await prepend_context("hello")
    assert re.match(rf"{TS_RE} hello", result)


@pytest.mark.asyncio
async def test_prepend_context_with_updates_clear(monkeypatch):
    update = PendingUpdate(ts=datetime.now(TZ).isoformat(), message="bg task done")

    async def pop():
        return [update]

    monkeypatch.setattr("ollim_bot.forks.pop_pending_updates", pop)

    result = await prepend_context("hello", clear=True)
    assert "RECENT BACKGROUND UPDATES (mention key findings" in result
    assert "bg task done" in result
    assert "hello" in result


@pytest.mark.asyncio
async def test_prepend_context_with_updates_no_clear(monkeypatch):
    update = PendingUpdate(ts=datetime.now(TZ).isoformat(), message="bg info")

    monkeypatch.setattr("ollim_bot.forks.peek_pending_updates", lambda: [update])

    result = await prepend_context("hello", clear=False)
    assert "RECENT BACKGROUND UPDATES (read-only" in result
    assert "bg info" in result


@pytest.mark.asyncio
async def test_prepend_context_empty_message(monkeypatch):
    async def no_updates():
        return []

    monkeypatch.setattr("ollim_bot.forks.pop_pending_updates", no_updates)

    result = await prepend_context("")
    assert re.fullmatch(TS_RE, result)
