"""Shared fixtures for ollim-bot tests."""

import pytest


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    """Redirect all data file paths to a temp directory."""
    import ollim_bot.inquiries as inquiries_mod
    import ollim_bot.reminders as reminders_mod
    import ollim_bot.routines as routines_mod
    import ollim_bot.storage as storage_mod

    monkeypatch.setattr(storage_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(routines_mod, "ROUTINES_FILE", tmp_path / "routines.jsonl")
    monkeypatch.setattr(reminders_mod, "REMINDERS_FILE", tmp_path / "reminders.jsonl")
    monkeypatch.setattr(inquiries_mod, "INQUIRIES_FILE", tmp_path / "inquiries.json")
    return tmp_path
