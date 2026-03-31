"""Shared fixtures for ollim-bot tests."""

import os

os.environ.setdefault("OLLIM_USER_NAME", "TestUser")
os.environ.setdefault("OLLIM_BOT_NAME", "test-bot")

import pytest


@pytest.fixture(autouse=True)
def _reset_bg_tracking():
    """Reset bg fork tracking between tests (production gets per-task ContextVar scope)."""
    import ollim_bot.fork_state as fork_state_mod

    fork_state_mod._bg_tracking.set(None)
    fork_state_mod._main_generation = 0
    fork_state_mod._updates_generation = 0
    fork_state_mod._fork_ctx = None


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    """Redirect all data file paths to a temp directory."""
    import ollim_bot.forks as forks_mod
    import ollim_bot.inquiries as inquiries_mod
    import ollim_bot.ping_budget as ping_budget_mod
    import ollim_bot.runtime_config as runtime_config_mod
    import ollim_bot.scheduling.reminders as reminders_mod
    import ollim_bot.scheduling.routines as routines_mod
    import ollim_bot.sessions as sessions_mod
    import ollim_bot.storage as storage_mod

    monkeypatch.delenv("OLLIM_DATA_DIR", raising=False)
    state_dir = tmp_path / "state"
    monkeypatch.setattr(storage_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(storage_mod, "STATE_DIR", state_dir)
    monkeypatch.setattr(routines_mod, "ROUTINES_DIR", tmp_path / "routines")
    monkeypatch.setattr(reminders_mod, "REMINDERS_DIR", tmp_path / "reminders")
    monkeypatch.setattr(inquiries_mod, "INQUIRIES_FILE", state_dir / "inquiries.json")
    monkeypatch.setattr(ping_budget_mod, "BUDGET_FILE", state_dir / "ping_budget.json")
    monkeypatch.setattr(runtime_config_mod, "CONFIG_FILE", state_dir / "config.json")
    monkeypatch.setattr(sessions_mod, "SESSIONS_FILE", state_dir / "sessions.json")
    monkeypatch.setattr(sessions_mod, "HISTORY_FILE", state_dir / "session_history.jsonl")
    monkeypatch.setattr(sessions_mod, "FORK_MESSAGES_FILE", state_dir / "fork_messages.json")
    monkeypatch.setattr(forks_mod, "_UPDATES_FILE", state_dir / "pending_updates.json")

    import ollim_bot.profile as profile_mod
    import ollim_bot.webhook as webhook_mod

    monkeypatch.setattr(profile_mod, "IDENTITY_FILE", tmp_path / "IDENTITY.md")
    monkeypatch.setattr(profile_mod, "USER_FILE", tmp_path / "USER.md")
    monkeypatch.setattr(webhook_mod, "WEBHOOKS_DIR", tmp_path / "webhooks")
    return tmp_path
