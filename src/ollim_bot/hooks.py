"""Agent SDK hooks for auto-committing file changes."""

import asyncio
from pathlib import Path
from typing import cast

from claude_agent_sdk.types import (
    HookContext,
    HookInput,
    PostToolUseHookInput,
    SyncHookJSONOutput,
)

from ollim_bot.storage import DATA_DIR, git_commit


async def auto_commit_hook(
    input_data: HookInput,
    tool_use_id: str | None,
    context: HookContext,
) -> SyncHookJSONOutput:
    """Auto-commit files after Write/Edit tool calls in DATA_DIR."""
    data = cast(PostToolUseHookInput, input_data)
    tool_name = data["tool_name"]
    tool_input = data["tool_input"]

    file_path_str: str = tool_input.get("file_path", "")
    if not file_path_str:
        return {}

    cwd = Path(data["cwd"])
    file_path = Path(file_path_str)
    if not file_path.is_absolute():
        file_path = cwd / file_path

    # Only auto-commit markdown files within DATA_DIR.
    resolved = file_path.resolve()
    if resolved.suffix != ".md" or not resolved.is_relative_to(DATA_DIR.resolve()):
        return {}

    rel = resolved.relative_to(DATA_DIR.resolve())
    message = f"auto: {tool_name.lower()} {rel}"
    await asyncio.to_thread(git_commit, file_path, message)
    return {}
