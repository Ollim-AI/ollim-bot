"""Tool pattern validation, scanning, and superset construction.

Validates tool patterns declared across routines, reminders, webhooks,
subagents, and skills. Blocks dangerous patterns (Bash(*), bash chaining),
warns on overly broad wildcards, and enforces write-protection on state/.
Builds the dynamic SDK ceiling as the union of all declared tool sets.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ollim_bot.skills import Skill
    from ollim_bot.subagents import SubagentSpec

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Validation types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolPatternError:
    pattern: str
    source: str  # e.g. "routine:heartbeat", "subagent:guide", "main"
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
_FILE_WRITE_TOOLS = frozenset(("Write", "Edit"))


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
    """Return error messages for a single tool pattern. Empty list = valid."""
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

        if tool_name in _FILE_WRITE_TOOLS and _could_match_state_dir(args):
            errors.append(f"{tool_name} pattern could match protected state/ directory")

    return errors


def validate_tool_set(patterns: list[str], source: str) -> list[ToolPatternError]:
    """Validate a complete tool set declaration."""
    results: list[ToolPatternError] = []
    for pattern in patterns:
        for msg in validate_pattern(pattern):
            severity = "warning" if "overly broad" in msg else "error"
            results.append(ToolPatternError(pattern=pattern, source=source, message=msg, severity=severity))
    return results


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


def scan_all(tool_sets: dict[str, list[str]] | None = None) -> list[ToolPatternError]:
    """Validate all tool declarations. Accepts pre-collected tool_sets to avoid re-reading."""
    if tool_sets is None:
        tool_sets = collect_all_tool_sets()

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
    "Read(**.md)",
    "Write(**.md)",
    "Edit(**.md)",
    "Glob(**.md)",
    "Grep(**.md)",
    "WebFetch",
    "WebSearch",
    "mcp__discord__discord_embed",
    "mcp__discord__ping_user",
    "mcp__discord__follow_up_chain",
    "mcp__discord__save_context",
    "mcp__discord__report_updates",
    "mcp__discord__enter_fork",
    "mcp__discord__exit_fork",
    "mcp__docs__*",
    "Task",
]


# ---------------------------------------------------------------------------
# Minimal bg fork tools — default when a job declares no tool restrictions
# ---------------------------------------------------------------------------

MINIMAL_BG_TOOLS: list[str] = [
    "mcp__discord__report_updates",
    "mcp__discord__ping_user",
    "mcp__discord__discord_embed",
    "mcp__discord__follow_up_chain",
    "Bash(ollim-bot help)",
]


# ---------------------------------------------------------------------------
# Dynamic superset construction
# ---------------------------------------------------------------------------


def collect_all_tool_sets(
    specs: Mapping[str, SubagentSpec] | None = None,
    skills: Sequence[Skill] | None = None,
) -> dict[str, list[str]]:
    """Collect tool sets from all sources.

    Returns a mapping of source name -> tool list.
    Accepts pre-loaded subagent specs and skills to avoid redundant disk reads.
    Imports are deferred to avoid circular dependencies.
    """
    from ollim_bot.scheduling.reminders import list_reminders
    from ollim_bot.scheduling.routines import list_routines
    from ollim_bot.webhook import list_webhooks

    tool_sets: dict[str, list[str]] = {"main": list(MAIN_SESSION_TOOLS)}

    if specs is None:
        from ollim_bot.subagents import load_subagent_specs

        specs = load_subagent_specs()
    for name, spec in specs.items():
        if spec.tools:
            tool_sets[f"subagent:{name}"] = spec.tools

    for routine in list_routines():
        if routine.allowed_tools:
            tool_sets[f"routine:{routine.id}"] = routine.allowed_tools

    for reminder in list_reminders():
        if reminder.allowed_tools:
            tool_sets[f"reminder:{reminder.id}"] = reminder.allowed_tools

    if skills is None:
        from ollim_bot.skills import list_skills

        skills = list_skills()
    for skill in skills:
        if skill.allowed_tools:
            tool_sets[f"skill:{skill.name}"] = skill.allowed_tools

    for webhook in list_webhooks():
        if webhook.allowed_tools:
            tool_sets[f"webhook:{webhook.id}"] = webhook.allowed_tools

    return tool_sets


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
            if name in _FILE_WRITE_TOOLS and _could_match_state_dir(args):
                log.warning("Stripped %s: matches protected state/", tool)
                continue
        result.append(tool)
    return result


def build_superset(tool_sets: dict[str, list[str]]) -> list[str]:
    """Deduplicated union of all tool sets.

    Strips Write/Edit patterns that could reach the protected ``state/`` directory.
    """
    seen: set[str] = set()
    result: list[str] = []
    for tools in tool_sets.values():
        for tool in strip_state_dir_writes(tools):
            if tool not in seen:
                seen.add(tool)
                result.append(tool)
    return result
