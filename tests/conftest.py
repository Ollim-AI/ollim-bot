"""Shared fixtures for ollim-bot tests."""

import os

os.environ.setdefault("OLLIM_USER_NAME", "TestUser")
os.environ.setdefault("OLLIM_BOT_NAME", "test-bot")

import pytest


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    """Redirect all data file paths to a temp directory."""
    import ollim_bot.forks as forks_mod
    import ollim_bot.inquiries as inquiries_mod
    import ollim_bot.ping_budget as ping_budget_mod
    import ollim_bot.scheduling.reminders as reminders_mod
    import ollim_bot.scheduling.routines as routines_mod
    import ollim_bot.sessions as sessions_mod
    import ollim_bot.storage as storage_mod

    state_dir = tmp_path / "state"
    monkeypatch.setattr(storage_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(storage_mod, "STATE_DIR", state_dir)
    monkeypatch.setattr(routines_mod, "ROUTINES_DIR", tmp_path / "routines")
    monkeypatch.setattr(reminders_mod, "REMINDERS_DIR", tmp_path / "reminders")
    monkeypatch.setattr(inquiries_mod, "INQUIRIES_FILE", state_dir / "inquiries.json")
    monkeypatch.setattr(ping_budget_mod, "BUDGET_FILE", state_dir / "ping_budget.json")
    monkeypatch.setattr(sessions_mod, "SESSIONS_FILE", state_dir / "sessions.json")
    monkeypatch.setattr(sessions_mod, "HISTORY_FILE", state_dir / "session_history.jsonl")
    monkeypatch.setattr(sessions_mod, "FORK_MESSAGES_FILE", state_dir / "fork_messages.json")
    monkeypatch.setattr(forks_mod, "_UPDATES_FILE", state_dir / "pending_updates.json")

    import ollim_bot.webhook as webhook_mod

    monkeypatch.setattr(webhook_mod, "WEBHOOKS_DIR", tmp_path / "webhooks")
    return tmp_path
