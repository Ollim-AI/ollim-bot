"""Tests for reminders.py — Reminder dataclass with chain fields."""

from datetime import datetime

import pytest

from ollim_bot.scheduling.reminders import (
    Reminder,
    append_reminder,
    list_reminders,
    remove_reminder,
)


def test_reminder_new_computes_run_at():
    reminder = Reminder.new(message="test", delay_minutes=30)

    assert len(reminder.id) == 8
    assert reminder.message == "test"
    run_at = datetime.fromisoformat(reminder.run_at)
    assert run_at.tzinfo is not None
    assert reminder.chain_depth == 0
    assert reminder.max_chain == 0
    assert reminder.chain_parent is None


def test_reminder_new_with_chain():
    reminder = Reminder.new(message="check task", delay_minutes=60, max_chain=3)

    assert reminder.max_chain == 3
    assert reminder.chain_depth == 0
    assert reminder.chain_parent == reminder.id  # auto-set to self


def test_reminder_new_chain_with_explicit_parent():
    reminder = Reminder.new(
        message="follow-up",
        delay_minutes=30,
        max_chain=3,
        chain_depth=1,
        chain_parent="original",
    )

    assert reminder.chain_depth == 1
    assert reminder.chain_parent == "original"


def test_reminder_new_chain_depth_exceeds_max():
    with pytest.raises(AssertionError, match="chain_depth.*>.*max_chain"):
        Reminder.new(message="bad", delay_minutes=10, max_chain=2, chain_depth=3)


def test_reminder_new_background():
    reminder = Reminder.new(message="silent", delay_minutes=15, background=True)

    assert reminder.background is True


def test_append_and_list_reminders(data_dir):
    r1 = Reminder.new(message="first", delay_minutes=10)
    r2 = Reminder.new(message="second", delay_minutes=20)

    append_reminder(r1)
    append_reminder(r2)
    result = list_reminders()

    assert len(result) == 2
    assert result[0].message == "first"
    assert result[1].message == "second"


def test_list_reminders_empty(data_dir):
    assert list_reminders() == []


def test_remove_reminder(data_dir):
    r = Reminder.new(message="test", delay_minutes=5)
    append_reminder(r)

    removed = remove_reminder(r.id)

    assert removed is True
    assert list_reminders() == []


def test_remove_reminder_not_found(data_dir):
    assert remove_reminder("nonexistent") is False


def test_chain_roundtrip_preserves_fields(data_dir):
    original = Reminder.new(
        message="chain test",
        delay_minutes=60,
        background=True,
        max_chain=2,
        chain_depth=1,
        chain_parent="parent_id",
    )
    append_reminder(original)

    loaded = list_reminders()[0]

    assert loaded.chain_depth == 1
    assert loaded.max_chain == 2
    assert loaded.chain_parent == "parent_id"
    assert loaded.background is True


def test_reminder_new_defaults_model_isolated():
    reminder = Reminder.new(message="test", delay_minutes=30)

    assert reminder.model is None
    assert reminder.isolated is False


def test_reminder_new_with_model_isolated():
    reminder = Reminder.new(
        message="check", delay_minutes=30, model="haiku", isolated=True
    )

    assert reminder.model == "haiku"
    assert reminder.isolated is True


def test_reminder_model_isolated_roundtrip(data_dir):
    reminder = Reminder.new(
        message="check",
        delay_minutes=30,
        model="sonnet",
        isolated=True,
        background=True,
    )
    append_reminder(reminder)

    loaded = list_reminders()[0]

    assert loaded.model == "sonnet"
    assert loaded.isolated is True


def test_chain_roundtrip_preserves_model_isolated(data_dir):
    original = Reminder.new(
        message="chain test",
        delay_minutes=60,
        background=True,
        max_chain=2,
        chain_depth=1,
        chain_parent="parent_id",
        model="haiku",
        isolated=True,
    )
    append_reminder(original)

    loaded = list_reminders()[0]

    assert loaded.model == "haiku"
    assert loaded.isolated is True
    assert loaded.chain_depth == 1
    assert loaded.max_chain == 2


def test_reminder_new_defaults_update_main_session_allow_ping():
    reminder = Reminder.new(message="test", delay_minutes=30)

    assert reminder.update_main_session == "on_ping"
    assert reminder.allow_ping is True


def test_reminder_new_custom_bg_config():
    reminder = Reminder.new(
        message="silent",
        delay_minutes=30,
        background=True,
        update_main_session="freely",
        allow_ping=False,
    )

    assert reminder.update_main_session == "freely"
    assert reminder.allow_ping is False


def test_reminder_bg_config_roundtrip(data_dir):
    reminder = Reminder.new(
        message="check",
        delay_minutes=30,
        background=True,
        update_main_session="blocked",
        allow_ping=False,
    )
    append_reminder(reminder)

    loaded = list_reminders()[0]

    assert loaded.update_main_session == "blocked"
    assert loaded.allow_ping is False


# --- Tool restrictions ---


def test_reminder_new_defaults_tool_restrictions():
    reminder = Reminder.new(message="test", delay_minutes=30)

    assert reminder.allowed_tools is None
    assert reminder.blocked_tools is None


def test_reminder_new_with_allowed_tools():
    reminder = Reminder.new(
        message="email only",
        delay_minutes=30,
        allowed_tools=["Bash(ollim-bot gmail *)"],
    )

    assert reminder.allowed_tools == ["Bash(ollim-bot gmail *)"]


def test_reminder_new_both_tools_raises():
    with pytest.raises(ValueError, match="Cannot specify both"):
        Reminder.new(
            message="bad",
            delay_minutes=10,
            allowed_tools=["Read(**.md)"],
            blocked_tools=["WebFetch"],
        )


def test_reminder_allowed_tools_roundtrip(data_dir):
    tools = ["Bash(ollim-bot gmail *)", "mcp__discord__report_updates"]
    reminder = Reminder.new(
        message="restricted",
        delay_minutes=30,
        background=True,
        allowed_tools=tools,
    )
    append_reminder(reminder)

    loaded = list_reminders()[0]

    assert loaded.allowed_tools == tools
    assert loaded.blocked_tools is None


def test_reminder_blocked_tools_roundtrip(data_dir):
    tools = ["WebFetch", "WebSearch"]
    reminder = Reminder.new(
        message="no web",
        delay_minutes=30,
        background=True,
        blocked_tools=tools,
    )
    append_reminder(reminder)

    loaded = list_reminders()[0]

    assert loaded.blocked_tools == tools
    assert loaded.allowed_tools is None
