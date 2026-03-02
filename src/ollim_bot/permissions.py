"""Discord-based permission approval for the Claude Agent SDK canUseTool callback."""

from __future__ import annotations

import contextlib
import json
import logging
from pathlib import Path
from typing import Any, NamedTuple

import anyio
import discord
from claude_agent_sdk.types import (
    PermissionResult,
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)

from ollim_bot import storage
from ollim_bot.channel import get_channel
from ollim_bot.forks import in_bg_fork
from ollim_bot.formatting import format_tool_label
from ollim_bot.tool_policy import _FILE_WRITE_TOOLS

log = logging.getLogger(__name__)


def _is_protected_path(file_path: str) -> bool:
    """Return True if *file_path* resolves under the protected ``state/`` directory."""
    resolved = Path(file_path).resolve()
    state_resolved = storage.STATE_DIR.resolve()
    return resolved == state_resolved or state_resolved in resolved.parents


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_session_allowed: set[str] = set()
_dont_ask: bool = True
_denied_labels: set[str] = set()

# Emoji constants
APPROVE = "\N{WHITE HEAVY CHECK MARK}"
DENY = "\N{CROSS MARK}"
ALWAYS = "\N{OPEN LOCK}"


class _PendingApproval(NamedTuple):
    event: anyio.Event
    result: list[str]  # mutable container — first element is the emoji


_pending: dict[int, _PendingApproval] = {}


def dont_ask() -> bool:
    return _dont_ask


def set_dont_ask(value: bool) -> None:
    global _dont_ask
    _dont_ask = value


def is_denied(label: str) -> bool:
    """Check (and consume) whether a tool label was denied by canUseTool."""
    if label in _denied_labels:
        _denied_labels.discard(label)
        return True
    return False


# ---------------------------------------------------------------------------
# Session-allowed management
# ---------------------------------------------------------------------------


def is_session_allowed(tool_name: str) -> bool:
    return tool_name in _session_allowed


def session_allow(tool_name: str) -> None:
    _session_allowed.add(tool_name)


# ---------------------------------------------------------------------------
# Approval resolution
# ---------------------------------------------------------------------------


def resolve_approval(message_id: int, emoji: str) -> None:
    """Resolve a pending approval. Safe to call from any context."""
    entry = _pending.get(message_id)
    if entry is None or entry.event.is_set():
        return
    entry.result.append(emoji)
    entry.event.set()


def cancel_pending() -> None:
    """Wake all pending approvals so they return (with empty result → deny)."""
    for entry in _pending.values():
        if not entry.event.is_set():
            entry.event.set()
    _pending.clear()


def reset() -> None:
    """Clear session-allowed set and cancel all pending approvals. Called on /clear."""
    cancel_pending()
    _session_allowed.clear()
    _denied_labels.clear()


# ---------------------------------------------------------------------------
# Approval flow
# ---------------------------------------------------------------------------


async def request_approval(tool_name: str, input_data: dict[str, Any]) -> PermissionResult:
    """Send approval message to Discord, await reaction, return result.

    Uses anyio primitives (Event + fail_after) because this callback runs
    inside the SDK's anyio task group.  Raw asyncio.Future + wait_for can
    leave the anyio task in a broken state after resolution, causing the
    SDK's subsequent transport.write() to silently hang.
    """
    if is_session_allowed(tool_name):
        return PermissionResultAllow()

    channel = get_channel()
    assert channel is not None, "channel.init_channel() not called before approval"

    label = format_tool_label(tool_name, json.dumps(input_data))

    try:
        msg = await channel.send(f"`{label}`")
        await msg.add_reaction(APPROVE)
        await msg.add_reaction(DENY)
        await msg.add_reaction(ALWAYS)
    except discord.DiscordException:
        return PermissionResultDeny(message="failed to send approval request")

    entry = _PendingApproval(event=anyio.Event(), result=[])
    _pending[msg.id] = entry

    try:
        with anyio.fail_after(60):
            await entry.event.wait()
    except TimeoutError:
        with contextlib.suppress(discord.DiscordException):
            await msg.edit(content=f"~~`{label}`~~ — timed out")
        return PermissionResultDeny(message="approval timed out")
    finally:
        _pending.pop(msg.id, None)

    if not entry.result:
        # Woken by cancel_pending() with no emoji → treat as deny
        with contextlib.suppress(discord.DiscordException):
            await msg.edit(content=f"~~`{label}`~~ — cancelled")
        return PermissionResultDeny(message="approval cancelled")

    emoji = entry.result[0]

    if emoji == APPROVE:
        with contextlib.suppress(discord.DiscordException):
            await msg.edit(content=f"`{label}` — allowed")
        return PermissionResultAllow()
    if emoji == ALWAYS:
        session_allow(tool_name)
        with contextlib.suppress(discord.DiscordException):
            await msg.edit(content=f"`{label}` — always allowed")
        return PermissionResultAllow()

    with contextlib.suppress(discord.DiscordException):
        await msg.edit(content=f"`{label}` — denied")
    return PermissionResultDeny(message="denied via Discord")


async def handle_tool_permission(
    tool_name: str,
    input_data: dict[str, Any],
    context: ToolPermissionContext,
) -> PermissionResult:
    """canUseTool callback — bg forks: deny; dontAsk: silent deny; else: Discord approval."""
    if tool_name in _FILE_WRITE_TOOLS and _is_protected_path(input_data["file_path"]):
        return PermissionResultDeny(
            message=f"{tool_name} to state/ is blocked — system files are write-protected",
        )
    if in_bg_fork():
        return PermissionResultDeny(message=f"{tool_name} is not allowed")
    if _dont_ask:
        if is_session_allowed(tool_name):
            return PermissionResultAllow()
        _denied_labels.add(format_tool_label(tool_name, json.dumps(input_data)))
        return PermissionResultDeny(message=f"{tool_name} is not allowed")
    result = await request_approval(tool_name, input_data)
    if isinstance(result, PermissionResultDeny):
        _denied_labels.add(format_tool_label(tool_name, json.dumps(input_data)))
    return result
