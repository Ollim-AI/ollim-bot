"""Tests for runtime_config.py — persistent runtime configuration."""

import json

import pytest

import ollim_bot.runtime_config as runtime_config_mod
from ollim_bot.runtime_config import (
    VALID_KEYS,
    RuntimeConfig,
    format_all,
    format_one,
    load,
    save,
    set_value,
)

# --- load / save round-trip ---


def test_load_returns_defaults_when_no_file(data_dir):
    assert load() == RuntimeConfig()


def test_save_and_load_round_trip(data_dir):
    cfg = RuntimeConfig(model_main="opus", thinking_fork=False)
    save(cfg)

    loaded = load()
    assert loaded.model_main == "opus"
    assert loaded.thinking_fork is False


def test_load_ignores_unknown_keys(data_dir):
    cfg_file = runtime_config_mod.CONFIG_FILE
    cfg_file.parent.mkdir(parents=True, exist_ok=True)
    cfg_file.write_text(json.dumps({"model_main": "haiku", "unknown_key": 42}))

    cfg = load()
    assert cfg.model_main == "haiku"
    assert not hasattr(cfg, "unknown_key")


# --- set_value parsing ---


@pytest.mark.parametrize(
    "key, raw, expected",
    [
        ("model_main", "opus", "opus"),
        ("model_main", "SONNET", "sonnet"),
        ("model_main", "default", None),
        ("model_main", "none", None),
        ("model_main", "", None),
        ("model_fork", "haiku", "haiku"),
        ("model_fork", "null", None),
        ("thinking_main", "on", True),
        ("thinking_main", "off", False),
        ("thinking_main", "true", True),
        ("thinking_main", "false", False),
        ("thinking_fork", "off", False),
        ("max_thinking_tokens", "20000", 20000),
        ("bg_fork_timeout", "3600", 3600),
        ("fork_idle_timeout", "5", 5),
        ("permission_mode", "default", "default"),
        ("permission_mode", "bypassPermissions", "bypassPermissions"),
    ],
)
def test_set_value_valid(data_dir, key, raw, expected):
    cfg = set_value(key, raw)
    assert getattr(cfg, key) == expected

    reloaded = load()
    assert getattr(reloaded, key) == expected


@pytest.mark.parametrize(
    "key, raw",
    [
        ("model_main", "gpt4"),
        ("thinking_main", "maybe"),
        ("max_thinking_tokens", "-1"),
        ("max_thinking_tokens", "abc"),
        ("max_thinking_tokens", "0"),
        ("max_thinking_tokens", "00"),
        ("bg_fork_timeout", "0"),
        ("fork_idle_timeout", "0"),
        ("permission_mode", "admin"),
    ],
)
def test_set_value_invalid(data_dir, key, raw):
    with pytest.raises(ValueError):
        set_value(key, raw)


def test_set_value_unknown_key(data_dir):
    with pytest.raises(ValueError, match="unknown key"):
        set_value("nonexistent", "value")


# --- format_all / format_one ---


def test_format_all_shows_defaults(data_dir):
    text = format_all()
    assert "model.main" in text
    assert "thinking.fork" in text
    assert "(default)" in text


def test_format_one_shows_value(data_dir):
    set_value("model_main", "opus")

    text = format_one("model_main")
    assert "opus" in text
    assert "(default)" not in text


def test_format_one_model_fork_inherit(data_dir):
    text = format_one("model_fork")
    assert "(inherit main)" in text


def test_format_one_timeout_units(data_dir):
    text = format_one("bg_fork_timeout")
    assert "1800s" in text

    text = format_one("fork_idle_timeout")
    assert "10m" in text


# --- valid keys ---


def test_valid_keys_matches_dataclass():
    from dataclasses import fields

    field_names = {f.name for f in fields(RuntimeConfig)}
    assert field_names == VALID_KEYS
