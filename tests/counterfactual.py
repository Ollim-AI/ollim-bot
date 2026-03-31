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
"""Counterfactual trajectory testing for ollim-bot sessions.

Load a real production transcript, rewind to a specific point, apply an
intervention (modified system prompt, tool restrictions, model swap, etc.),
and compare the agent's response against the original.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    query,
)
from claude_agent_sdk.types import SystemPromptPreset, TextBlock, ToolUseBlock
from claude_history.chain import (
    build_record_indexes,
    extract_all_text,
    extract_all_tools,
    get_full_response,
)
from claude_history.io import parse_jsonl_file
from claude_history.models import extract_content_text
from claude_history.resolve import get_project_dir

from ollim_bot.prompts import build_system_prompt

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Intervention:
    """Describes how to modify agent configuration for the variant run."""

    system_prompt_append: str | None = None
    system_prompt_replace: str | None = None
    allowed_tools: list[str] | None = None
    disallowed_tools: list[str] | None = None
    model: str | None = None
    message_override: str | None = None
    max_turns: int = 5
    max_budget_usd: float = 0.50

    def __post_init__(self) -> None:
        if self.system_prompt_append and self.system_prompt_replace:
            msg = "system_prompt_append and system_prompt_replace are mutually exclusive"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ResponseSummary:
    """Summarised output from one trajectory (original, baseline, or variant)."""

    text: str
    tool_calls: list[dict[str, Any]]
    total_cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    session_id: str | None = None
    num_turns: int | None = None


@dataclass(frozen=True, slots=True)
class CounterfactualResult:
    """Full comparison of original vs baseline vs variant."""

    session_id: str
    rewind_uuid: str
    original_message: str
    intervention: Intervention
    original: ResponseSummary
    baseline: ResponseSummary | None
    variant: ResponseSummary


# ---------------------------------------------------------------------------
# Session file helpers
# ---------------------------------------------------------------------------

_UUID_RE = re.compile(r'"uuid":"([^"]+)"')


def find_session_file(session_id: str, cwd: str | Path) -> Path:
    """Locate the JSONL file for a session on disk.

    Raises FileNotFoundError if no matching session is found.
    """
    project_dir = get_project_dir(str(Path(cwd).expanduser()))
    if project_dir is None:
        msg = (
            f"No Claude project directory found for cwd={cwd}. "
            "Ensure cwd matches the working directory used when the session was created."
        )
        raise FileNotFoundError(msg)

    matches = sorted(project_dir.glob(f"{session_id}*.jsonl"))
    if not matches:
        msg = f"No session file matching '{session_id}*' in {project_dir}. Check the session ID and cwd."
        raise FileNotFoundError(msg)
    return matches[0]


def _extract_last_uuid(line: str) -> str | None:
    """Extract the top-level uuid from a JSONL line (last occurrence)."""
    pos = line.rfind('"uuid":"')
    if pos == -1:
        return None
    m = _UUID_RE.search(line, pos)
    return m.group(1) if m else None


def truncate_session(filepath: Path, rewind_uuid: str) -> tuple[Path, str]:
    """Create a truncated copy of the session JSONL at the rewind point.

    Returns (temp_path, original_message_text).
    Raises ValueError if rewind_uuid is not found.
    """
    temp_id = str(uuid4())
    temp_path = filepath.parent / f"{temp_id}.jsonl"
    lines_to_write: list[str] = []
    original_message: str | None = None

    with open(filepath, encoding="utf-8", errors="replace") as f:
        for line in f:
            uuid = _extract_last_uuid(line)
            if uuid == rewind_uuid:
                record = json.loads(line)
                content = record.get("message", {}).get("content", "")
                original_message = extract_content_text(content)
                break
            lines_to_write.append(line)

    if original_message is None:
        # Scan for available user message UUIDs to help the caller
        available = _scan_user_uuids(filepath)
        hint = ", ".join(available[:10]) if available else "(none found)"
        msg = f"UUID '{rewind_uuid}' not found in {filepath.name}. Available user message UUIDs: {hint}"
        raise ValueError(msg)

    with open(temp_path, "w", encoding="utf-8") as f:
        f.writelines(lines_to_write)

    log.info("Truncated session to %d lines at %s -> %s", len(lines_to_write), rewind_uuid[:8], temp_path.name)
    return temp_path, original_message


def _scan_user_uuids(filepath: Path) -> list[str]:
    """Quick scan for user message UUIDs (for error messages)."""
    uuids: list[str] = []
    with open(filepath, encoding="utf-8", errors="replace") as f:
        for line in f:
            if '"type":"user"' not in line or '"type":"tool_result"' in line:
                continue
            uuid = _extract_last_uuid(line)
            if uuid:
                uuids.append(uuid)
    return uuids


# ---------------------------------------------------------------------------
# Original response extraction
# ---------------------------------------------------------------------------


def extract_original_response(filepath: Path, rewind_uuid: str) -> ResponseSummary:
    """Extract the original response chain for the message at rewind_uuid."""
    records = parse_jsonl_file(filepath)
    indexes = build_record_indexes(records)
    chain = get_full_response(records, rewind_uuid, indexes)

    text = extract_all_text(chain)
    tool_calls = extract_all_tools(chain)

    # Extract cost from the first assistant message's usage field
    input_tokens: int | None = None
    output_tokens: int | None = None
    for record in chain:
        usage = record.get("message", {}).get("usage", {})
        if usage:
            input_tokens = usage.get("input_tokens")
            output_tokens = usage.get("output_tokens")
            break

    return ResponseSummary(
        text=text,
        tool_calls=tool_calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        num_turns=len(chain),
    )


# ---------------------------------------------------------------------------
# SDK query helpers
# ---------------------------------------------------------------------------


def _build_system_prompt(intervention: Intervention | None) -> SystemPromptPreset | str:
    """Build the system_prompt option for ClaudeAgentOptions."""
    base_append = build_system_prompt()

    if intervention and intervention.system_prompt_replace:
        return intervention.system_prompt_replace

    extra = ""
    if intervention and intervention.system_prompt_append:
        extra = f"\n\n{intervention.system_prompt_append}"

    return SystemPromptPreset(
        type="preset",
        preset="claude_code",
        append=f"{base_append}{extra}",
    )


def _build_options(intervention: Intervention | None, cwd: Path) -> ClaudeAgentOptions:
    """Build ClaudeAgentOptions for a counterfactual run."""
    i = intervention or Intervention()
    return ClaudeAgentOptions(
        cwd=str(cwd),
        permission_mode="bypassPermissions",
        system_prompt=_build_system_prompt(intervention),
        setting_sources=["project"],
        mcp_servers={
            "docs": {"type": "http", "url": "https://docs.ollim.ai/mcp"},
        },
        allowed_tools=i.allowed_tools
        or [
            "mcp__docs__*",
            "Read",
            "Glob",
            "Grep",
            "Bash",
            "WebFetch",
            "WebSearch",
            "Edit",
            "Write",
            "Agent",
            "Skill",
        ],
        disallowed_tools=i.disallowed_tools or [],
        model=i.model,
        max_turns=i.max_turns,
        max_budget_usd=i.max_budget_usd,
    )


async def _run_query(session_id: str, message: str, options: ClaudeAgentOptions) -> ResponseSummary:
    """Run a single forked query and collect the response."""
    opts = replace(options, resume=session_id, fork_session=True)

    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    result_msg: ResultMessage | None = None

    async for msg in query(prompt=message, options=opts):
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    text_parts.append(block.text)
                elif isinstance(block, ToolUseBlock):
                    tool_calls.append(
                        {
                            "name": block.name,
                            "id": block.id,
                            "input": block.input,
                        }
                    )
        elif isinstance(msg, ResultMessage):
            result_msg = msg

    usage = result_msg.usage if result_msg else None
    return ResponseSummary(
        text="\n\n".join(text_parts),
        tool_calls=tool_calls,
        total_cost_usd=result_msg.total_cost_usd if result_msg else None,
        input_tokens=usage.get("input_tokens") if usage else None,
        output_tokens=usage.get("output_tokens") if usage else None,
        session_id=result_msg.session_id if result_msg else None,
        num_turns=result_msg.num_turns if result_msg else None,
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def run_counterfactual(
    session_id: str,
    rewind_uuid: str,
    intervention: Intervention,
    *,
    cwd: str | Path,
    skip_baseline: bool = False,
) -> CounterfactualResult:
    """Run a counterfactual trajectory test.

    Finds the session, truncates at rewind_uuid, runs baseline and variant
    queries from the truncated session, and returns a structured comparison.

    Args:
        session_id: Session to analyse (full UUID or prefix).
        rewind_uuid: UUID of the user message to rewind to.
        intervention: Configuration changes for the variant run.
        cwd: Working directory for the session (must match the original).
        skip_baseline: Skip the baseline run to save cost.
    """
    cwd_path = Path(cwd).expanduser()
    filepath = find_session_file(session_id, cwd_path)
    log.info("Found session file: %s", filepath)

    original = extract_original_response(filepath, rewind_uuid)
    temp_path, original_message = truncate_session(filepath, rewind_uuid)
    temp_session_id = temp_path.stem
    project_dir = temp_path.parent

    fork_session_ids: list[str] = []
    try:
        message = intervention.message_override or original_message

        baseline: ResponseSummary | None = None
        if not skip_baseline:
            log.info("Running baseline query...")
            baseline = await _run_query(temp_session_id, message, _build_options(None, cwd_path))
            if baseline.session_id:
                fork_session_ids.append(baseline.session_id)
            log.info("Baseline done (cost=$%.4f)", baseline.total_cost_usd or 0)

        log.info("Running variant query...")
        variant = await _run_query(temp_session_id, message, _build_options(intervention, cwd_path))
        if variant.session_id:
            fork_session_ids.append(variant.session_id)
        log.info("Variant done (cost=$%.4f)", variant.total_cost_usd or 0)

    finally:
        # Clean up temp truncated file
        temp_path.unlink(missing_ok=True)
        # Clean up fork session files
        for fork_sid in fork_session_ids:
            fork_file = project_dir / f"{fork_sid}.jsonl"
            fork_file.unlink(missing_ok=True)
            log.info("Cleaned up fork session: %s", fork_sid[:8])

    return CounterfactualResult(
        session_id=session_id,
        rewind_uuid=rewind_uuid,
        original_message=original_message,
        intervention=intervention,
        original=original,
        baseline=baseline,
        variant=variant,
    )
