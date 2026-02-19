"""Tests for config module."""

import importlib

import dotenv
import pytest

import ollim_bot.config as config_mod


def test_missing_user_name_exits(monkeypatch):
    monkeypatch.delenv("OLLIM_USER_NAME", raising=False)
    monkeypatch.setenv("OLLIM_BOT_NAME", "test-bot")
    monkeypatch.setattr(dotenv, "load_dotenv", lambda: None)

    with pytest.raises(SystemExit):
        importlib.reload(config_mod)


def test_missing_bot_name_exits(monkeypatch):
    monkeypatch.setenv("OLLIM_USER_NAME", "TestUser")
    monkeypatch.delenv("OLLIM_BOT_NAME", raising=False)
    monkeypatch.setattr(dotenv, "load_dotenv", lambda: None)

    with pytest.raises(SystemExit):
        importlib.reload(config_mod)


def test_valid_config_loads(monkeypatch):
    monkeypatch.setenv("OLLIM_USER_NAME", "Alice")
    monkeypatch.setenv("OLLIM_BOT_NAME", "my-bot")

    importlib.reload(config_mod)
    assert config_mod.USER_NAME == "Alice"
    assert config_mod.BOT_NAME == "my-bot"
