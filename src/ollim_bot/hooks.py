"""Agent SDK hooks for state-dir write protection and auto-committing file changes."""

import asyncio
from pathlib import Path
from typing import cast

from claude_agent_sdk.types import (
    HookContext,
    HookInput,
    PostToolUseHookInput,
    PreToolUseHookInput,
    SyncHookJSONOutput,
)

from ollim_bot import storage
from ollim_bot.storage import git_commit


def _resolve_tool_path(data: PreToolUseHookInput | PostToolUseHookInput) -> Path | None:
    file_path_str: str = data["tool_input"].get("file_path", "")
    if not file_path_str:
        return None
    cwd = Path(data["cwd"])
    file_path = Path(file_path_str)
    if not file_path.is_absolute():
        file_path = cwd / file_path
    return file_path.resolve()


async def state_dir_guard(
    input_data: HookInput,
    tool_use_id: str | None,
    context: HookContext,
) -> SyncHookJSONOutput:
    data = cast(PreToolUseHookInput, input_data)
    resolved = _resolve_tool_path(data)
    if resolved is not None and resolved.is_relative_to(storage.STATE_DIR.resolve()):
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "state/ is write-protected",
            }
        }
    return {}


async def auto_commit_hook(
    input_data: HookInput,
    tool_use_id: str | None,
    context: HookContext,
) -> SyncHookJSONOutput:
    data = cast(PostToolUseHookInput, input_data)
    resolved = _resolve_tool_path(data)
    if resolved is None:
        return {}

    # Only auto-commit markdown files within DATA_DIR.
    data_dir_resolved = storage.DATA_DIR.resolve()
    if resolved.suffix != ".md" or not resolved.is_relative_to(data_dir_resolved):
        return {}

    tool_name = data["tool_name"]
    rel = resolved.relative_to(data_dir_resolved)
    message = f"auto: {tool_name.lower()} {rel}"
    await asyncio.to_thread(git_commit, resolved, message)
    return {}
