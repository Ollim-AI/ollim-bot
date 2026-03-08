"""Tests for hooks.py — state_dir_guard and auto_commit_hook."""

import asyncio

from claude_agent_sdk.types import HookContext, PreToolUseHookInput

from ollim_bot.hooks import _resolve_tool_path, state_dir_guard


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_pre_tool_input(file_path: str, cwd: str) -> PreToolUseHookInput:
    return PreToolUseHookInput(
        session_id="test",
        transcript_path="",
        cwd=cwd,
        agent_id="test",
        agent_type="main",
        hook_event_name="PreToolUse",
        tool_name="Write",
        tool_input={"file_path": file_path},
        tool_use_id="test",
    )


_HOOK_CTX = HookContext(signal=None)


def test_resolve_tool_path_absolute(tmp_path):
    target = tmp_path / "file.md"
    data = _make_pre_tool_input(str(target), str(tmp_path))

    result = _resolve_tool_path(data)

    assert result == target.resolve()


def test_resolve_tool_path_relative(tmp_path):
    data = _make_pre_tool_input("sub/file.md", str(tmp_path))

    result = _resolve_tool_path(data)

    assert result == (tmp_path / "sub" / "file.md").resolve()


def test_resolve_tool_path_missing():
    data = _make_pre_tool_input("", "/tmp")

    assert _resolve_tool_path(data) is None


def test_state_dir_guard_blocks_write_to_state(data_dir):
    from ollim_bot.storage import STATE_DIR

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    data = _make_pre_tool_input(str(STATE_DIR / "config.json"), str(data_dir))

    result = _run(state_dir_guard(data, None, _HOOK_CTX))

    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "write-protected" in result["hookSpecificOutput"]["permissionDecisionReason"]


def test_state_dir_guard_allows_non_state(data_dir):
    data = _make_pre_tool_input(str(data_dir / "routines" / "foo.md"), str(data_dir))

    result = _run(state_dir_guard(data, None, _HOOK_CTX))

    assert result == {}


def test_state_dir_guard_allows_empty_path(data_dir):
    data = _make_pre_tool_input("", str(data_dir))

    result = _run(state_dir_guard(data, None, _HOOK_CTX))

    assert result == {}


def test_state_dir_guard_blocks_state_dir_itself(data_dir):
    from ollim_bot.storage import STATE_DIR

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    data = _make_pre_tool_input(str(STATE_DIR), str(data_dir))

    result = _run(state_dir_guard(data, None, _HOOK_CTX))

    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
