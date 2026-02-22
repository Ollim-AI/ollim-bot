"""Shared fixtures for ollim-bot tests."""

import os

os.environ.setdefault("OLLIM_USER_NAME", "TestUser")
os.environ.setdefault("OLLIM_BOT_NAME", "test-bot")

import pytest


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    """Redirect all data file paths to a temp directory."""
    import ollim_bot.inquiries as inquiries_mod
    import ollim_bot.ping_budget as ping_budget_mod
    import ollim_bot.scheduling.reminders as reminders_mod
    import ollim_bot.scheduling.routines as routines_mod
    import ollim_bot.sessions as sessions_mod
    import ollim_bot.storage as storage_mod

    monkeypatch.setattr(storage_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(routines_mod, "ROUTINES_DIR", tmp_path / "routines")
    monkeypatch.setattr(reminders_mod, "REMINDERS_DIR", tmp_path / "reminders")
    monkeypatch.setattr(inquiries_mod, "INQUIRIES_FILE", tmp_path / "inquiries.json")
    monkeypatch.setattr(ping_budget_mod, "BUDGET_FILE", tmp_path / "ping_budget.json")
    monkeypatch.setattr(sessions_mod, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(
        sessions_mod, "HISTORY_FILE", tmp_path / "session_history.jsonl"
    )
    monkeypatch.setattr(
        sessions_mod, "FORK_MESSAGES_FILE", tmp_path / "fork_messages.json"
    )
    return tmp_path
