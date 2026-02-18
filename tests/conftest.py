"""Shared fixtures for ollim-bot tests."""

import pytest


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    """Redirect all data file paths to a temp directory."""
    import ollim_bot.inquiries as inquiries_mod
    import ollim_bot.scheduling.reminders as reminders_mod
    import ollim_bot.scheduling.routines as routines_mod
    import ollim_bot.storage as storage_mod

    monkeypatch.setattr(storage_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(routines_mod, "ROUTINES_DIR", tmp_path / "routines")
    monkeypatch.setattr(reminders_mod, "REMINDERS_DIR", tmp_path / "reminders")
    monkeypatch.setattr(inquiries_mod, "INQUIRIES_FILE", tmp_path / "inquiries.json")
    return tmp_path
