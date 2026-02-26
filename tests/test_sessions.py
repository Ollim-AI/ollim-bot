"""Tests for sessions.py — session persistence and history logging."""

import json

import pytest

import ollim_bot.sessions as sessions_mod
from ollim_bot.sessions import (
    SessionEvent,
    delete_session_id,
    flush_message_collector,
    log_session_event,
    lookup_fork_session,
    save_session_id,
    set_swap_in_progress,
    start_message_collector,
    track_message,
)


@pytest.fixture()
def history(tmp_path, monkeypatch):
    path = tmp_path / "session_history.jsonl"
    monkeypatch.setattr(sessions_mod, "HISTORY_FILE", path)
    return path


def test_session_event_is_frozen():
    event = SessionEvent(session_id="abc", event="created", timestamp="2026-01-01T00:00:00")

    try:
        event.session_id = "xyz"  # type: ignore[invalid-assignment]
        raise AssertionError("Should have raised FrozenInstanceError")
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


# --- save_session_id auto-detection ---


@pytest.fixture()
def sessions(tmp_path, monkeypatch, history):
    """Redirect both SESSIONS_FILE and HISTORY_FILE to tmp_path."""
    path = tmp_path / "sessions.json"
    monkeypatch.setattr(sessions_mod, "SESSIONS_FILE", path)
    return path


def test_save_session_id_logs_created_on_first_save(sessions, history):
    save_session_id("first-session")

    lines = history.read_text().strip().splitlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["event"] == "created"
    assert data["session_id"] == "first-session"
    assert data["parent_session_id"] is None


def test_save_session_id_no_event_on_same_id(sessions, history):
    sessions.write_text("same-id")

    save_session_id("same-id")

    assert not history.exists()


def test_save_session_id_logs_compacted_on_id_change(sessions, history):
    sessions.write_text("old-id")

    save_session_id("new-id")

    lines = history.read_text().strip().splitlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["event"] == "compacted"
    assert data["session_id"] == "new-id"
    assert data["parent_session_id"] == "old-id"


def test_save_session_id_skips_log_during_swap(sessions, history):
    sessions.write_text("old-id")

    set_swap_in_progress(True)
    try:
        save_session_id("new-id")
    finally:
        set_swap_in_progress(False)

    assert not history.exists()


def test_delete_then_save_logs_created(sessions, history):
    sessions.write_text("old-id")
    delete_session_id()

    save_session_id("brand-new")

    lines = history.read_text().strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["event"] == "created"


# --- fork message tracking ---


@pytest.fixture()
def fork_messages(tmp_path, monkeypatch):
    path = tmp_path / "fork_messages.json"
    monkeypatch.setattr(sessions_mod, "FORK_MESSAGES_FILE", path)
    return path


def test_track_message_noop_without_collector(fork_messages):
    track_message(111)

    assert not fork_messages.exists()


def test_collector_roundtrip(fork_messages):
    start_message_collector()
    track_message(100)
    track_message(200)
    flush_message_collector("fork-abc", "parent-xyz")

    assert lookup_fork_session(100) == "fork-abc"
    assert lookup_fork_session(200) == "fork-abc"


def test_lookup_unknown_returns_none(fork_messages):
    assert lookup_fork_session(999) is None


def test_flush_clears_collector(fork_messages):
    start_message_collector()
    track_message(100)
    flush_message_collector("fork-abc", "parent-xyz")

    start_message_collector()
    flush_message_collector("fork-def", "parent-xyz")

    assert lookup_fork_session(100) == "fork-abc"


def test_expired_records_pruned(fork_messages):
    import time

    old_ts = time.time() - (8 * 24 * 3600)
    fork_messages.write_text(
        json.dumps(
            [
                {
                    "message_id": 100,
                    "fork_session_id": "old-fork",
                    "parent_session_id": "old-parent",
                    "ts": old_ts,
                }
            ]
        )
    )

    assert lookup_fork_session(100) is None
