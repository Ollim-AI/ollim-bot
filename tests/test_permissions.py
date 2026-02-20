"""Tests for permissions.py — session-allowed set, resolve, cancel, reset, callback."""

import asyncio

from claude_agent_sdk.types import (
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)

from ollim_bot.forks import set_in_fork
from ollim_bot.permissions import (
    cancel_pending,
    handle_tool_permission,
    is_session_allowed,
    reset,
    resolve_approval,
    session_allow,
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


def test_resolve_approval_sets_future():
    loop = asyncio.new_event_loop()
    future: asyncio.Future[str] = loop.create_future()
    reset()

    from ollim_bot.permissions import _pending

    _pending[12345] = future
    resolve_approval(12345, "\N{WHITE HEAVY CHECK MARK}")

    assert future.done()
    assert loop.run_until_complete(future) == "\N{WHITE HEAVY CHECK MARK}"
    loop.close()


def test_resolve_approval_ignores_unknown_message():
    reset()
    resolve_approval(99999, "\N{WHITE HEAVY CHECK MARK}")


def test_resolve_approval_ignores_already_done():
    loop = asyncio.new_event_loop()
    future: asyncio.Future[str] = loop.create_future()
    future.set_result("\N{WHITE HEAVY CHECK MARK}")
    reset()

    from ollim_bot.permissions import _pending

    _pending[12345] = future

    resolve_approval(12345, "\N{CROSS MARK}")

    assert loop.run_until_complete(future) == "\N{WHITE HEAVY CHECK MARK}"
    loop.close()


def test_cancel_pending_cancels_all():
    loop = asyncio.new_event_loop()
    f1: asyncio.Future[str] = loop.create_future()
    f2: asyncio.Future[str] = loop.create_future()
    reset()

    from ollim_bot.permissions import _pending

    _pending[1] = f1
    _pending[2] = f2

    cancel_pending()

    assert f1.cancelled()
    assert f2.cancelled()

    from ollim_bot.permissions import _pending as after

    assert len(after) == 0
    loop.close()


def test_reset_cancels_pending_and_clears_allowed():
    loop = asyncio.new_event_loop()
    future: asyncio.Future[str] = loop.create_future()
    reset()

    from ollim_bot.permissions import _pending

    _pending[1] = future
    session_allow("Bash")

    reset()

    assert future.cancelled()
    assert is_session_allowed("Bash") is False
    loop.close()


# --- canUseTool callback ---


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_handle_tool_permission_denies_bg_fork():
    set_in_fork(True)
    try:
        result = _run(
            handle_tool_permission(
                "Bash", {"command": "rm -rf /"}, ToolPermissionContext()
            )
        )

        assert isinstance(result, PermissionResultDeny)
        assert "not allowed" in result.message
    finally:
        set_in_fork(False)


def test_handle_tool_permission_allows_session_allowed():
    reset()
    session_allow("WebFetch")
    try:
        result = _run(
            handle_tool_permission(
                "WebFetch", {"url": "https://example.com"}, ToolPermissionContext()
            )
        )

        assert isinstance(result, PermissionResultAllow)
    finally:
        reset()
