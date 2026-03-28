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
"""Tool pattern validation, scanning, and per-job tool restrictions.

Validates tool patterns declared across routines, reminders, webhooks,
subagents, and skills. Blocks dangerous patterns (Bash(*), bash chaining),
warns on overly broad wildcards, and enforces write-protection on state/.
"""

from __future__ import annotations

import functools
import logging
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from claude_agent_sdk import ClaudeAgentOptions

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Validation types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolPatternError:
    pattern: str
    source: str  # e.g. "routine:heartbeat", "subagent:ollim-bot-guide", "main"
    message: str
    severity: Literal["error", "warning"]


# ---------------------------------------------------------------------------
# Pattern rules
# ---------------------------------------------------------------------------

# Bash chaining operators — these allow arbitrary command injection
_BASH_CHAIN_RE = re.compile(r"[;&|]")

# Matches tool patterns with arguments: ToolName(args)
_TOOL_WITH_ARGS_RE = re.compile(r"^(\w+)\((.+)\)$")

# Tools that modify files on disk
FILE_WRITE_TOOLS = frozenset(("Write", "Edit"))

# Discord MCP tool classification — used for dynamic bg fork gating
PING_TOOLS = frozenset(("mcp__discord__ping_user", "mcp__discord__discord_embed"))
REPORTING_TOOLS = frozenset(("mcp__discord__report_updates", "mcp__discord__follow_up_chain"))
REMINDER_TOOLS = frozenset(
    (
        "mcp__discord__add_reminder",
        "mcp__discord__list_reminders",
        "mcp__discord__cancel_reminder",
    )
)
DISCORD_TOOLS = PING_TOOLS | REPORTING_TOOLS | REMINDER_TOOLS
# Tools gated by canUseTool (ping budget, allow_ping, update_main_session) —
# stripped from bg fork allowed_tools so the SDK doesn't auto-approve them.
GATED_TOOLS = PING_TOOLS | REPORTING_TOOLS


# ---------------------------------------------------------------------------
# State directory write-protection
# ---------------------------------------------------------------------------

# Probe paths covering different patterns state files could take.
# Not tied to specific filenames — just representative structures.
# Limitation: extension-specific patterns (e.g. state/*.txt) slip through
# if no probe matches. Acceptable because state/ only uses .json/.jsonl.
_STATE_PROBE_PATHS = (
    "state/x",
    "state/x.json",
    "state/x.jsonl",
    "state/sub/x",
)


@functools.lru_cache(maxsize=64)
def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Convert a Claude Code CLI glob to a compiled regex.

    Handles ``**/`` (zero-or-more directory prefix), ``**`` (recursive match),
    ``*`` (single directory level), and ``?`` (single character).
    """
    parts: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        if pattern[i : i + 3] == "**/":
            parts.append("(.*/)?")
            i += 3
        elif pattern[i : i + 2] == "**":
            parts.append(".*")
            i += 2
        elif pattern[i] == "*":
            parts.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            parts.append("[^/]")
            i += 1
        else:
            parts.append(re.escape(pattern[i]))
            i += 1
    return re.compile(f"^{''.join(parts)}$")


def _could_match_state_dir(glob_pattern: str) -> bool:
    """Check if a file glob could match any path under ``state/``."""
    regex = _glob_to_regex(glob_pattern)
    return any(regex.match(p) for p in _STATE_PROBE_PATHS)


def validate_pattern(pattern: str) -> list[str]:
    errors: list[str] = []

    pattern = pattern.strip()
    if not pattern:
        errors.append("empty tool pattern")
        return errors

    match = _TOOL_WITH_ARGS_RE.match(pattern)
    if match:
        tool_name, args = match.group(1), match.group(2)

        if tool_name == "Bash":
            if args == "*":
                errors.append("Bash(*) is too broad — specify a command prefix")
                return errors
            if _BASH_CHAIN_RE.search(args):
                errors.append(f"Bash pattern contains chaining operators: {args!r}")
        elif args == "*":
            errors.append(f"{tool_name}(*) is overly broad — add a path restriction")

        if tool_name in FILE_WRITE_TOOLS and _could_match_state_dir(args):
            errors.append(f"{tool_name} pattern could match protected state/ directory")

    return errors


def validate_tool_set(patterns: list[str], source: str) -> list[ToolPatternError]:
    results: list[ToolPatternError] = []
    for pattern in patterns:
        for msg in validate_pattern(pattern):
            severity = "warning" if "overly broad" in msg else "error"
            results.append(ToolPatternError(pattern=pattern, source=source, message=msg, severity=severity))
    return results


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


def scan_all(tool_sets: dict[str, list[str]]) -> list[ToolPatternError]:
    errors: list[ToolPatternError] = []
    for source, tools in tool_sets.items():
        errors.extend(validate_tool_set(tools, source))

    for err in errors:
        if err.severity == "error":
            log.error("Tool policy: [%s] %s — %s", err.source, err.pattern, err.message)
        else:
            log.warning("Tool policy: [%s] %s — %s", err.source, err.pattern, err.message)

    return errors


# ---------------------------------------------------------------------------
# Main session tools — the interactive context's declared tool set
# ---------------------------------------------------------------------------

MAIN_SESSION_TOOLS: list[str] = [
    "Bash(ollim-bot tasks *)",
    "Bash(ollim-bot cal *)",
    "Bash(ollim-bot reminder *)",
    "Bash(ollim-bot gmail *)",
    "Bash(ollim-bot help)",
    "Bash(claude-history *)",
    "Read(./**.md)",
    "Write(./**.md)",
    "Edit(./**.md)",
    "Glob(./**.md)",
    "Grep(./**.md)",
    "WebFetch",
    "WebSearch",
    "mcp__discord__discord_embed",
    "mcp__discord__ping_user",
    "mcp__discord__follow_up_chain",
    "mcp__discord__save_context",
    "mcp__discord__report_updates",
    "mcp__discord__enter_fork",
    "mcp__discord__exit_fork",
    "mcp__discord__update_names",
    "mcp__discord__add_reminder",
    "mcp__discord__list_reminders",
    "mcp__discord__cancel_reminder",
    "mcp__docs__*",
    "Agent",
    "Skill",
]


# ---------------------------------------------------------------------------
# Default bg fork tools — pre-approved when a job declares no tool restrictions.
# Discord MCP tools are not listed here — they're dynamically gated via
# canUseTool based on BgForkConfig (allow_ping, update_main_session).
# ---------------------------------------------------------------------------

_HELP_TOOL = "Bash(ollim-bot help)"

DEFAULT_BG_TOOLS: list[str] = [
    _HELP_TOOL,
    "Bash(ollim-bot tasks *)",
    "Read(./**.md)",
    "Glob(./**.md)",
    "Grep(./**.md)",
    "mcp__discord__add_reminder",
    "mcp__discord__list_reminders",
    "mcp__discord__cancel_reminder",
]


def validate_dispatch(allowed_tools: list[str] | None, source: str) -> bool:
    if allowed_tools is None:
        return True
    errors = validate_tool_set(allowed_tools, source=source)
    if any(e.severity == "error" for e in errors):
        log.error("Skipping %s: invalid tool patterns", source)
        return False
    return True


def apply_tool_restrictions(
    opts: ClaudeAgentOptions,
    allowed: list[str] | None,
) -> ClaudeAgentOptions:
    """Apply per-job tool restrictions to agent options.

    Strips Write/Edit patterns that could reach the protected ``state/`` directory.
    """
    if allowed is not None:
        tools = strip_state_dir_writes(allowed)
        if _HELP_TOOL not in tools:
            tools = [_HELP_TOOL, *tools]
        return replace(opts, allowed_tools=tools)
    return opts


def strip_state_dir_writes(tools: list[str]) -> list[str]:
    """Remove Write/Edit patterns that could match the protected ``state/`` directory.

    Called both at SDK ceiling construction and per-fork tool restriction
    to ensure no tool set — however declared — grants write access to state/.
    """
    result: list[str] = []
    for tool in tools:
        match = _TOOL_WITH_ARGS_RE.match(tool.strip())
        if match:
            name, args = match.groups()
            if name in FILE_WRITE_TOOLS and _could_match_state_dir(args):
                log.warning("Stripped %s: matches protected state/", tool)
                continue
        result.append(tool)
    return result


# ---------------------------------------------------------------------------
# YAML tool config — user-managed tool policy overrides
# ---------------------------------------------------------------------------

_yaml_cache_mtime: float = 0.0
_yaml_cache_data: dict[str, Any] = {}


def _yaml_config_path() -> Path:
    from ollim_bot.storage import DATA_DIR

    return DATA_DIR / "tool-policy.yaml"


def reset_yaml_cache() -> None:
    global _yaml_cache_mtime, _yaml_cache_data
    _yaml_cache_mtime = 0.0
    _yaml_cache_data = {}


def load_yaml_config() -> dict[str, Any]:
    """Load tool-policy.yaml with mtime-based caching.

    Returns empty dict if the file doesn't exist. Re-parses only when
    the file's mtime changes.
    """
    global _yaml_cache_mtime, _yaml_cache_data

    path = _yaml_config_path()
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        _yaml_cache_mtime = 0.0
        _yaml_cache_data = {}
        return _yaml_cache_data

    if mtime == _yaml_cache_mtime:
        return _yaml_cache_data

    import yaml

    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    _yaml_cache_mtime = mtime
    _yaml_cache_data = data if isinstance(data, dict) else {}
    return _yaml_cache_data


def build_main_tools() -> list[str]:
    """MAIN_SESSION_TOOLS extended with YAML additional_allowed."""
    config = load_yaml_config()
    main_config = config.get("main_session", {})
    additional = main_config.get("additional_allowed", [])
    if not additional:
        return MAIN_SESSION_TOOLS
    return MAIN_SESSION_TOOLS + [t for t in additional if t not in MAIN_SESSION_TOOLS]


def build_bg_tools() -> list[str]:
    """DEFAULT_BG_TOOLS, optionally overridden or extended by YAML config."""
    config = load_yaml_config()
    bg_config = config.get("bg_forks", {})
    override = bg_config.get("override")
    if override is not None:
        return list(override)
    additional = bg_config.get("additional_allowed", [])
    if not additional:
        return DEFAULT_BG_TOOLS
    return DEFAULT_BG_TOOLS + [t for t in additional if t not in DEFAULT_BG_TOOLS]
