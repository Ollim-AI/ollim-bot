"""Tests for sessions.py — session persistence and history logging."""

import json

import pytest

import ollim_bot.sessions as sessions_mod
from ollim_bot.sessions import (
    SessionEvent,
    log_session_event,
)


@pytest.fixture()
def history(tmp_path, monkeypatch):
    path = tmp_path / "session_history.jsonl"
    monkeypatch.setattr(sessions_mod, "HISTORY_FILE", path)
    return path


def test_session_event_is_frozen():
    event = SessionEvent(
        session_id="abc", event="created", timestamp="2026-01-01T00:00:00"
    )

    try:
        event.session_id = "xyz"
        assert False, "Should have raised FrozenInstanceError"
    except AttributeError:
        pass


def test_log_session_event_creates_file(history):
    log_session_event("abc123", "created")

    lines = history.read_text().strip().splitlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["session_id"] == "abc123"
    assert data["event"] == "created"
    assert data["parent_session_id"] is None
    assert "timestamp" in data


def test_log_session_event_with_parent(history):
    log_session_event("new-id", "compacted", parent_session_id="old-id")

    data = json.loads(history.read_text().strip())
    assert data["session_id"] == "new-id"
    assert data["event"] == "compacted"
    assert data["parent_session_id"] == "old-id"


def test_log_session_event_appends(history):
    log_session_event("a", "created")
    log_session_event("b", "compacted", parent_session_id="a")

    lines = history.read_text().strip().splitlines()
    assert len(lines) == 2
