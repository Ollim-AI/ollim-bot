"""Message context helpers for the Agent SDK wrapper.

Stateless functions that prepare timestamps, format durations, assemble
pending updates, and build ThinkingConfig dicts.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal

from claude_agent_sdk import ResultMessage
from claude_agent_sdk.types import ThinkingConfig

from ollim_bot.config import TZ as _TZ
from ollim_bot.sessions import session_start_time

log = logging.getLogger(__name__)

ModelName = Literal["opus", "sonnet", "haiku"]


def _format_duration(seconds: float) -> str:
    """Format seconds as '3h 12m', '45m', or '< 1m'."""
    minutes = int(seconds // 60)
    if minutes < 1:
        return "< 1m"
    hours, mins = divmod(minutes, 60)
    if hours:
        return f"{hours}h {mins}m" if mins else f"{hours}h"
    return f"{mins}m"


def format_compact_stats(result: ResultMessage | None, pre_tokens: int | None) -> str:
    """Format compaction result as productivity stats."""
    parts: list[str] = []
    if result:
        parts.append(f"{result.num_turns} turns")
    start = session_start_time()
    if start:
        age = (datetime.now(_TZ) - start).total_seconds()
        parts.append(_format_duration(age))
    if pre_tokens is not None:
        k = pre_tokens / 1000
        parts.append(f"{k:.0f}k tokens compacted")
    return " · ".join(parts)


def timestamp() -> str:
    return datetime.now(_TZ).strftime("[%Y-%m-%d %a %I:%M %p PT]")


def _relative_time(iso_ts: str) -> str:
    """Format an ISO timestamp as relative time (e.g. '2h ago')."""
    delta = datetime.now(_TZ) - datetime.fromisoformat(iso_ts)
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


async def prepend_context(message: str, *, clear: bool = True) -> str:
    """Prepend timestamp and any pending background updates to a user message.

    clear=True (default): pops updates (main session clears the file).
    clear=False: peeks updates (fork reads without clearing).
    """
    from ollim_bot.forks import peek_pending_updates, pop_pending_updates

    ts = timestamp()
    updates = (await pop_pending_updates()) if clear else peek_pending_updates()
    if updates:
        lines = [f"- ({_relative_time(u.ts)}) {u.message}" for u in updates]
        header = "RECENT BACKGROUND UPDATES:\n" + "\n".join(lines)
        assembled = f"{ts} {header}\n\n{message}"
    else:
        assembled = f"{ts} {message}" if message else ts
    log.debug("assembled context: %.500s", assembled)
    return assembled


def thinking(enabled: bool, budget: int = 10_000) -> ThinkingConfig:
    """Build a ThinkingConfig from a boolean toggle and token budget."""
    if enabled:
        return {"type": "enabled", "budget_tokens": budget}
    return {"type": "disabled"}
