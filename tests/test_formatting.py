"""Tests for formatting.py — tool label formatting."""

from ollim_bot.formatting import format_tool_label


def test_simple_tool():
    assert (
        format_tool_label("Read", '{"file_path": "/home/user/notes.md"}')
        == "Read(user/notes.md)"
    )


def test_mcp_tool_strips_prefix():
    assert format_tool_label("mcp__discord__ping_user", "") == "ping_user"


def test_bash_truncates_command():
    long_cmd = "a" * 100
    label = format_tool_label("Bash", f'{{"command": "{long_cmd}"}}')
    # Bash truncates to 50 chars
    assert len(label) < 60


def test_unknown_tool_returns_name():
    assert format_tool_label("UnknownTool", '{"foo": "bar"}') == "UnknownTool"


def test_bad_json_returns_name():
    assert format_tool_label("Read", "not json") == "Read"


def test_path_shortening():
    label = format_tool_label(
        "Write", '{"file_path": "/home/user/.ollim-bot/reminders/foo.md"}'
    )
    assert label == "Write(reminders/foo.md)"


def test_grep_multiple_keys():
    label = format_tool_label("Grep", '{"pattern": "TODO", "path": "/home/user/src"}')
    assert "TODO" in label
    assert "src" in label
