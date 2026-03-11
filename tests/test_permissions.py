"""Tests for permissions.py — session-allowed set, resolve, cancel, reset, callback."""

import asyncio

import anyio
import pytest
from claude_agent_sdk.types import (
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)

from ollim_bot.fork_state import BgForkConfig, set_bg_fork_config, set_in_fork
from ollim_bot.permissions import (
    _PendingApproval,
    cancel_pending,
    clear_denied,
    dont_ask,
    handle_tool_permission,
    is_denied,
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
        assert "not available in background forks" in result.message
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
        assert "requires permission" in result.message
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


# --- bg fork dynamic discord gating ---


def test_bg_fork_allows_ping_when_enabled():
    set_in_fork(True)
    set_bg_fork_config(BgForkConfig(allow_ping=True))
    try:
        result = _run(handle_tool_permission("mcp__discord__ping_user", {}, ToolPermissionContext()))

        assert isinstance(result, PermissionResultAllow)
    finally:
        set_in_fork(False)
        set_bg_fork_config(BgForkConfig())


def test_bg_fork_denies_ping_when_disabled():
    set_in_fork(True)
    set_bg_fork_config(BgForkConfig(allow_ping=False))
    try:
        result = _run(handle_tool_permission("mcp__discord__ping_user", {}, ToolPermissionContext()))

        assert isinstance(result, PermissionResultDeny)
        assert "pings disabled" in result.message
    finally:
        set_in_fork(False)
        set_bg_fork_config(BgForkConfig())


def test_bg_fork_allows_report_when_not_blocked():
    set_in_fork(True)
    set_bg_fork_config(BgForkConfig(update_main_session="on_ping"))
    try:
        result = _run(handle_tool_permission("mcp__discord__report_updates", {}, ToolPermissionContext()))

        assert isinstance(result, PermissionResultAllow)
    finally:
        set_in_fork(False)
        set_bg_fork_config(BgForkConfig())


def test_bg_fork_denies_report_when_blocked():
    set_in_fork(True)
    set_bg_fork_config(BgForkConfig(update_main_session="blocked"))
    try:
        result = _run(handle_tool_permission("mcp__discord__report_updates", {}, ToolPermissionContext()))

        assert isinstance(result, PermissionResultDeny)
        assert "reporting blocked" in result.message
    finally:
        set_in_fork(False)
        set_bg_fork_config(BgForkConfig())


# --- clear_denied ---


def test_clear_denied_removes_stale_labels():
    """Denied labels from a previous response don't bleed into the next one."""
    reset()
    set_dont_ask(True)
    try:
        _run(handle_tool_permission("Bash", {"command": "ls"}, ToolPermissionContext()))
        assert is_denied("Bash(ls)") is True

        # Simulate a second denial that isn't consumed by the streamer
        _run(handle_tool_permission("Bash", {"command": "rm -rf /"}, ToolPermissionContext()))
        # clear_denied should wipe it before the next response
        clear_denied()
        assert is_denied("Bash(rm -rf /)") is False
    finally:
        set_dont_ask(True)
        reset()
