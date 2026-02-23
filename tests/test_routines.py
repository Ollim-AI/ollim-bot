"""Tests for routines.py — Routine dataclass and CRUD."""

from ollim_bot.scheduling.routines import (
    Routine,
    append_routine,
    list_routines,
    remove_routine,
)


def test_routine_new_generates_id():
    routine = Routine.new(message="test", cron="0 9 * * *")

    assert len(routine.id) == 8
    assert routine.message == "test"
    assert routine.cron == "0 9 * * *"
    assert routine.background is False


def test_routine_new_with_background():
    routine = Routine.new(message="bg task", cron="*/5 * * * *", background=True)

    assert routine.background is True


def test_append_and_list_routines(data_dir):
    r1 = Routine.new(message="morning", cron="0 8 * * *")
    r2 = Routine.new(message="evening", cron="0 18 * * *")

    append_routine(r1)
    append_routine(r2)
    result = list_routines()

    assert len(result) == 2
    messages = {r.message for r in result}
    assert messages == {"morning", "evening"}


def test_list_routines_empty(data_dir):
    assert list_routines() == []


def test_remove_routine(data_dir):
    r = Routine.new(message="test", cron="0 9 * * *")
    append_routine(r)

    removed = remove_routine(r.id)

    assert removed is True
    assert list_routines() == []


def test_remove_routine_not_found(data_dir):
    assert remove_routine("nonexistent") is False


def test_routine_new_defaults_model_isolated():
    routine = Routine.new(message="test", cron="0 9 * * *")

    assert routine.model is None
    assert routine.isolated is False


def test_routine_new_with_model_isolated():
    routine = Routine.new(
        message="check", cron="0 9 * * *", model="haiku", isolated=True
    )

    assert routine.model == "haiku"
    assert routine.isolated is True


def test_routine_model_isolated_roundtrip(data_dir):
    routine = Routine.new(
        message="check",
        cron="0 9 * * *",
        model="sonnet",
        isolated=True,
        background=True,
    )
    append_routine(routine)

    loaded = list_routines()[0]

    assert loaded.model == "sonnet"
    assert loaded.isolated is True


def test_routine_new_defaults_update_main_session_allow_ping():
    routine = Routine.new(message="test", cron="0 9 * * *")

    assert routine.update_main_session == "on_ping"
    assert routine.allow_ping is True


def test_routine_new_custom_bg_config():
    routine = Routine.new(
        message="silent",
        cron="0 9 * * *",
        background=True,
        update_main_session="blocked",
        allow_ping=False,
    )

    assert routine.update_main_session == "blocked"
    assert routine.allow_ping is False


def test_routine_bg_config_roundtrip(data_dir):
    routine = Routine.new(
        message="check",
        cron="0 9 * * *",
        background=True,
        update_main_session="always",
        allow_ping=False,
    )
    append_routine(routine)

    loaded = list_routines()[0]

    assert loaded.update_main_session == "always"
    assert loaded.allow_ping is False


def test_routine_default_bg_config_omitted_from_frontmatter(data_dir):
    """Default values should not appear in serialized YAML."""
    routine = Routine.new(message="defaults", cron="0 9 * * *")
    append_routine(routine)

    loaded = list_routines()[0]

    assert loaded.update_main_session == "on_ping"
    assert loaded.allow_ping is True


# --- Tool restrictions ---


def test_routine_new_defaults_tool_restrictions():
    routine = Routine.new(message="test", cron="0 9 * * *")

    assert routine.allowed_tools is None
    assert routine.blocked_tools is None


def test_routine_new_with_allowed_tools():
    routine = Routine.new(
        message="email only",
        cron="0 9 * * *",
        allowed_tools=["Bash(ollim-bot gmail *)", "Bash(ollim-bot tasks *)"],
    )

    assert routine.allowed_tools == [
        "Bash(ollim-bot gmail *)",
        "Bash(ollim-bot tasks *)",
    ]
    assert routine.blocked_tools is None


def test_routine_new_with_blocked_tools():
    routine = Routine.new(
        message="no web",
        cron="0 9 * * *",
        blocked_tools=["WebFetch", "WebSearch"],
    )

    assert routine.blocked_tools == ["WebFetch", "WebSearch"]
    assert routine.allowed_tools is None


def test_routine_new_both_tools_raises():
    import pytest

    with pytest.raises(ValueError, match="Cannot specify both"):
        Routine.new(
            message="bad",
            cron="0 9 * * *",
            allowed_tools=["Read(**.md)"],
            blocked_tools=["WebFetch"],
        )


def test_routine_allowed_tools_roundtrip(data_dir):
    tools = ["Bash(ollim-bot gmail *)", "mcp__discord__report_updates"]
    routine = Routine.new(
        message="restricted",
        cron="0 9 * * *",
        background=True,
        allowed_tools=tools,
    )
    append_routine(routine)

    loaded = list_routines()[0]

    assert loaded.allowed_tools == tools
    assert loaded.blocked_tools is None


def test_routine_blocked_tools_roundtrip(data_dir):
    tools = ["WebFetch", "WebSearch"]
    routine = Routine.new(
        message="no web",
        cron="0 9 * * *",
        background=True,
        blocked_tools=tools,
    )
    append_routine(routine)

    loaded = list_routines()[0]

    assert loaded.blocked_tools == tools
    assert loaded.allowed_tools is None


def test_routine_no_tools_omitted_from_frontmatter(data_dir):
    """Default None tool restrictions should not appear in serialized YAML."""
    routine = Routine.new(message="defaults", cron="0 9 * * *")
    append_routine(routine)

    loaded = list_routines()[0]

    assert loaded.allowed_tools is None
    assert loaded.blocked_tools is None
