"""Tests for permissions.py — session-allowed set, resolve, cancel, reset, callback."""

import asyncio

import anyio
import pytest
from claude_agent_sdk.types import (
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)

from ollim_bot.forks import set_in_fork
from ollim_bot.permissions import (
    _is_protected_path,
    _PendingApproval,
    cancel_pending,
    dont_ask,
    handle_tool_permission,
    is_session_allowed,
    reset,
    resolve_approval,
    session_allow,
    set_dont_ask,
)


def test_session_allowed_default_empty():
    reset()
    assert is_session_allowed("Bash") is False


def test_session_allow_and_check():
    reset()
    session_allow("Bash(rm *)")

    assert is_session_allowed("Bash(rm *)") is True
    assert is_session_allowed("Bash(ls)") is False


def test_reset_clears_session_allowed():
    reset()
    session_allow("WebFetch")

    reset()

    assert is_session_allowed("WebFetch") is False


def test_resolve_approval_sets_result():
    reset()

    from ollim_bot.permissions import _pending

    entry = _PendingApproval(event=anyio.Event(), result=[])
    _pending[12345] = entry
    resolve_approval(12345, "\N{WHITE HEAVY CHECK MARK}")

    assert entry.event.is_set()
    assert entry.result == ["\N{WHITE HEAVY CHECK MARK}"]


def test_resolve_approval_ignores_unknown_message():
    reset()
    resolve_approval(99999, "\N{WHITE HEAVY CHECK MARK}")


def test_resolve_approval_ignores_already_set():
    reset()

    from ollim_bot.permissions import _pending

    entry = _PendingApproval(event=anyio.Event(), result=["\N{WHITE HEAVY CHECK MARK}"])
    entry.event.set()
    _pending[12345] = entry

    resolve_approval(12345, "\N{CROSS MARK}")

    assert entry.result == ["\N{WHITE HEAVY CHECK MARK}"]


def test_cancel_pending_sets_events():
    reset()

    from ollim_bot.permissions import _pending

    e1 = _PendingApproval(event=anyio.Event(), result=[])
    e2 = _PendingApproval(event=anyio.Event(), result=[])
    _pending[1] = e1
    _pending[2] = e2

    cancel_pending()

    assert e1.event.is_set()
    assert e2.event.is_set()
    assert e1.result == []  # no emoji — caller treats as cancel
    assert e2.result == []

    from ollim_bot.permissions import _pending as after

    assert len(after) == 0


def test_reset_cancels_pending_and_clears_allowed():
    reset()

    from ollim_bot.permissions import _pending

    entry = _PendingApproval(event=anyio.Event(), result=[])
    _pending[1] = entry
    session_allow("Bash")

    reset()

    assert entry.event.is_set()
    assert is_session_allowed("Bash") is False


# --- canUseTool callback ---


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_handle_tool_permission_denies_bg_fork():
    set_in_fork(True)
    try:
        result = _run(handle_tool_permission("Bash", {"command": "rm -rf /"}, ToolPermissionContext()))

        assert isinstance(result, PermissionResultDeny)
        assert "not allowed" in result.message
    finally:
        set_in_fork(False)


def test_handle_tool_permission_allows_session_allowed():
    reset()
    set_dont_ask(False)
    session_allow("WebFetch")
    try:
        result = _run(handle_tool_permission("WebFetch", {"url": "https://example.com"}, ToolPermissionContext()))

        assert isinstance(result, PermissionResultAllow)
    finally:
        set_dont_ask(True)
        reset()


# --- dontAsk mode ---


def test_dont_ask_default_true():
    assert dont_ask() is True


def test_dont_ask_denies_non_whitelisted():
    set_dont_ask(True)
    try:
        result = _run(handle_tool_permission("Bash", {"command": "ls"}, ToolPermissionContext()))

        assert isinstance(result, PermissionResultDeny)
        assert "not allowed" in result.message
    finally:
        set_dont_ask(True)


def test_dont_ask_allows_session_allowed():
    reset()
    set_dont_ask(True)
    session_allow("WebFetch")
    try:
        result = _run(handle_tool_permission("WebFetch", {"url": "https://example.com"}, ToolPermissionContext()))

        assert isinstance(result, PermissionResultAllow)
    finally:
        set_dont_ask(True)
        reset()


def test_dont_ask_off_reaches_approval_flow():
    """When dontAsk is off and no channel set, hits the assertion (approval flow entered)."""
    reset()
    set_dont_ask(False)
    from ollim_bot.channel import init_channel

    init_channel(None)
    try:
        with pytest.raises(AssertionError, match="init_channel"):
            _run(handle_tool_permission("Bash", {"command": "ls"}, ToolPermissionContext()))
    finally:
        set_dont_ask(True)


# --- state-dir write protection ---


def test_is_protected_path_state_file(data_dir):
    from ollim_bot.storage import STATE_DIR

    STATE_DIR.mkdir(parents=True, exist_ok=True)

    assert _is_protected_path(str(STATE_DIR / "config.json")) is True
    assert _is_protected_path(str(STATE_DIR / "sessions.json")) is True
    assert _is_protected_path(str(STATE_DIR / "sub" / "nested.json")) is True


def test_is_protected_path_non_state(data_dir):
    assert _is_protected_path(str(data_dir / "routines" / "foo.md")) is False
    assert _is_protected_path(str(data_dir / "reminders" / "bar.md")) is False


def test_is_protected_path_state_dir_itself(data_dir):
    from ollim_bot.storage import STATE_DIR

    assert _is_protected_path(str(STATE_DIR)) is True


def test_handle_tool_permission_blocks_write_to_state(data_dir):
    from ollim_bot.storage import STATE_DIR

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_path = str(STATE_DIR / "config.json")

    result = _run(handle_tool_permission("Write", {"file_path": state_path}, ToolPermissionContext()))

    assert isinstance(result, PermissionResultDeny)
    assert "write-protected" in result.message


def test_handle_tool_permission_blocks_edit_to_state(data_dir):
    from ollim_bot.storage import STATE_DIR

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_path = str(STATE_DIR / "sessions.json")

    result = _run(handle_tool_permission("Edit", {"file_path": state_path}, ToolPermissionContext()))

    assert isinstance(result, PermissionResultDeny)
    assert "write-protected" in result.message


def test_handle_tool_permission_allows_write_outside_state(data_dir):
    """Write to non-state path should not be blocked by state protection (may be blocked by dontAsk)."""
    set_dont_ask(True)
    non_state_path = str(data_dir / "routines" / "foo.md")

    result = _run(handle_tool_permission("Write", {"file_path": non_state_path}, ToolPermissionContext()))

    # dontAsk denies it, but the message should NOT mention write-protected
    assert isinstance(result, PermissionResultDeny)
    assert "write-protected" not in result.message


def test_handle_tool_permission_state_guard_overrides_session_allowed(data_dir):
    """State-dir guard takes priority even if the tool is session-allowed."""
    from ollim_bot.storage import STATE_DIR

    reset()
    set_dont_ask(False)
    session_allow("Write")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_path = str(STATE_DIR / "config.json")

    try:
        result = _run(handle_tool_permission("Write", {"file_path": state_path}, ToolPermissionContext()))

        assert isinstance(result, PermissionResultDeny)
        assert "write-protected" in result.message
    finally:
        set_dont_ask(True)
        reset()
