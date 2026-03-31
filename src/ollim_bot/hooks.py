# ollim-bot
# Copyright (C) 2025-2026 Julius Frost
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""Agent SDK hooks for state-dir write protection, auto-committing, and routine validation."""

import asyncio
import re
from pathlib import Path
from typing import cast

from claude_agent_sdk.types import (
    HookContext,
    HookInput,
    PostToolUseFailureHookInput,
    PostToolUseHookInput,
    PreToolUseHookInput,
    SyncHookJSONOutput,
)

from ollim_bot import storage
from ollim_bot.permissions import mark_errored
from ollim_bot.scheduling.routines import ROUTINES_DIR, Routine
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


async def tool_error_hook(
    input_data: HookInput,
    tool_use_id: str | None,
    context: HookContext,
) -> SyncHookJSONOutput:
    """Mark tool label as errored when a tool returns is_error: True."""
    data = cast(PostToolUseHookInput, input_data)
    if isinstance(data["tool_response"], dict) and data["tool_response"].get("is_error"):
        mark_errored(data["tool_name"], data["tool_input"])
    return {}


async def tool_failure_hook(
    input_data: HookInput,
    tool_use_id: str | None,
    context: HookContext,
) -> SyncHookJSONOutput:
    """Mark tool label as errored on hard execution failure (PostToolUseFailure)."""
    data = cast(PostToolUseFailureHookInput, input_data)
    if not data.get("is_interrupt"):
        mark_errored(data["tool_name"], data["tool_input"])
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


# ---------------------------------------------------------------------------
# Routine validator — PreToolUse hook for routines/*.md
# ---------------------------------------------------------------------------

# Valid frontmatter keys matching Routine dataclass fields (hyphen form)
_ROUTINE_KEYS = {f.name.replace("_", "-") for f in Routine.__dataclass_fields__.values()}

_CRON_RE = re.compile(r"^(\S+\s+){4}\S+$")

# Tools that grant broad access when unscoped
_BROAD_TOOLS_RE = re.compile(r"^(Bash|Write|Edit|MultiEdit)$")
_DELEGATION_TOOLS = {"Task", "Agent"}

_MAX_ROUTINE_LINES = 200


def _parse_routine_frontmatter(content: str) -> tuple[dict | None, str | None]:
    """Parse YAML frontmatter from routine markdown. Returns (fm_dict, error)."""
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, None  # no frontmatter

    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return None, "Unclosed frontmatter — missing closing '---'"

    fm: dict = {}
    for line in lines[1:end_idx]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and fm:
            last_key = list(fm.keys())[-1]
            if isinstance(fm[last_key], list):
                fm[last_key].append(stripped[2:].strip())
            continue
        if ":" not in stripped:
            return None, f"Malformed YAML line: '{stripped}'"
        key, _, value = stripped.partition(":")
        key, value = key.strip(), value.strip()
        if value.startswith("[") and value.endswith("]"):
            fm[key] = [v.strip().strip("\"'") for v in value[1:-1].split(",") if v.strip()]
        elif value.lower() in ("true", "false"):
            fm[key] = value.lower() == "true"
        elif value == "":
            fm[key] = []
        else:
            fm[key] = value.strip("\"'")
    return fm, None


def _get_allowed_tools(fm: dict) -> list[str]:
    tools = fm.get("allowed-tools") or fm.get("allowed_tools") or []
    if isinstance(tools, str):
        tools = [t.strip() for t in tools.split(",")]
    return tools


def validate_routine(content: str) -> tuple[list[str], list[str]]:
    """Validate routine content. Returns (blocks, warnings)."""
    blocks: list[str] = []
    warnings: list[str] = []

    fm, error = _parse_routine_frontmatter(content)
    if fm is None and error is None:
        blocks.append("Missing frontmatter — routine files require YAML between --- markers")
        return blocks, warnings
    if error:
        blocks.append(f"Frontmatter error: {error}")
        return blocks, warnings

    assert fm is not None

    if "id" not in fm:
        blocks.append("Missing 'id' — required for scheduler job registration")
    if "cron" not in fm:
        blocks.append("Missing 'cron' — required for scheduling")
    elif isinstance(fm["cron"], str) and not _CRON_RE.match(fm["cron"].strip()):
        blocks.append(f"Invalid cron: '{fm['cron']}' — need 5 fields (min hour day month dow)")

    if blocks:
        return blocks, warnings

    # --- Warnings ---
    if not fm.get("description"):
        warnings.append("Missing 'description' — degrades schedule display")

    if "background" not in fm:
        warnings.append("Missing 'background' — defaults to false; most routines need background: true")

    tools = _get_allowed_tools(fm)
    for tool in tools:
        base = tool.split("(")[0].strip()
        if _BROAD_TOOLS_RE.match(base) and "(" not in tool:
            warnings.append(f"Unscoped '{base}' in allowed-tools — restrict with path patterns")

    # Delegation + unscoped writes
    tool_bases = {t.split("(")[0].strip() for t in tools}
    has_delegation = bool(tool_bases & _DELEGATION_TOOLS)
    _WRITE_TOOLS = {"Write", "Edit", "MultiEdit"}
    has_unscoped_write = any(t.split("(")[0].strip() in _WRITE_TOOLS and "(" not in t for t in tools)
    if has_delegation and has_unscoped_write:
        warnings.append(
            "Delegation + unscoped Write/Edit — subagent output may be written to shared files "
            "without verification. Scope writes to routine-owned files"
        )

    # Underscore keys
    for key in fm:
        normalized = key.replace("_", "-")
        if "_" in key and normalized in _ROUTINE_KEYS:
            warnings.append(f"'{key}' uses underscores — canonical form is '{normalized}'")

    # Unknown keys
    for key in fm:
        if key.replace("_", "-") not in _ROUTINE_KEYS:
            warnings.append(f"Unknown frontmatter key: '{key}'")

    # Line count
    line_count = content.count("\n") + 1
    if line_count > _MAX_ROUTINE_LINES:
        warnings.append(f"Routine is {line_count} lines (max {_MAX_ROUTINE_LINES}) — consider splitting")

    return blocks, warnings


async def routine_validator(
    input_data: HookInput,
    tool_use_id: str | None,
    context: HookContext,
) -> SyncHookJSONOutput:
    """PreToolUse hook: validate routine files on Write/Edit."""
    data = cast(PreToolUseHookInput, input_data)
    resolved = _resolve_tool_path(data)
    if resolved is None:
        return {}

    routines_resolved = ROUTINES_DIR.resolve()
    if not resolved.is_relative_to(routines_resolved) or resolved.suffix != ".md":
        return {}

    # Simulate the edit to get proposed content
    tool_name = data["tool_name"]
    tool_input = data["tool_input"]
    if tool_name == "Write":
        content = tool_input.get("content", "")
    elif tool_name == "Edit" and resolved.exists():
        original = await asyncio.to_thread(resolved.read_text)
        old = tool_input.get("old_string", "")
        new = tool_input.get("new_string", "")
        if not old or old not in original:
            return {}
        if tool_input.get("replace_all"):
            content = original.replace(old, new)
        else:
            content = original.replace(old, new, 1)
    else:
        return {}

    blocks, warnings = validate_routine(content)

    if blocks:
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "routine-validator: " + " | ".join(blocks),
            }
        }

    if warnings:
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": (f"routine-validator: {len(warnings)} warning(s): " + " | ".join(warnings)),
            }
        }

    return {}
