"""Tests for SDK layout bootstrap in main.py."""

import json

import ollim_bot.main as main_mod


def test_ensure_claude_settings_creates_file_with_auto_memory_disabled(data_dir, monkeypatch):
    monkeypatch.setattr(main_mod, "DATA_DIR", data_dir)

    main_mod._ensure_claude_settings()

    settings = json.loads((data_dir / ".claude" / "settings.json").read_text())
    assert settings["autoMemoryEnabled"] is False


def test_ensure_claude_settings_preserves_existing_value(data_dir, monkeypatch):
    monkeypatch.setattr(main_mod, "DATA_DIR", data_dir)
    settings_path = data_dir / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({"autoMemoryEnabled": True}))

    main_mod._ensure_claude_settings()

    settings = json.loads(settings_path.read_text())
    assert settings["autoMemoryEnabled"] is True


def test_ensure_claude_settings_merges_with_unrelated_keys(data_dir, monkeypatch):
    monkeypatch.setattr(main_mod, "DATA_DIR", data_dir)
    settings_path = data_dir / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({"enabledPlugins": {"foo": True}}))

    main_mod._ensure_claude_settings()

    settings = json.loads(settings_path.read_text())
    assert settings["autoMemoryEnabled"] is False
    assert settings["enabledPlugins"] == {"foo": True}
