"""Discord-based permission approval for the Claude Agent SDK canUseTool callback."""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

import discord
from claude_agent_sdk.types import (
    PermissionResult,
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)

from ollim_bot.formatting import format_tool_label
from ollim_bot.forks import in_bg_fork

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_channel: discord.abc.Messageable | None = None
_pending: dict[int, asyncio.Future[str]] = {}
_session_allowed: set[str] = set()
_dont_ask: bool = True

# Emoji constants
APPROVE = "\N{WHITE HEAVY CHECK MARK}"
DENY = "\N{CROSS MARK}"
ALWAYS = "\N{OPEN LOCK}"


def dont_ask() -> bool:
    return _dont_ask


def set_dont_ask(value: bool) -> None:
    global _dont_ask
    _dont_ask = value


def set_channel(channel: discord.abc.Messageable | None) -> None:
    """Set channel global — called alongside agent_tools.set_channel."""
    global _channel
    _channel = channel


# ---------------------------------------------------------------------------
# Session-allowed management
# ---------------------------------------------------------------------------


def is_session_allowed(tool_name: str) -> bool:
    return tool_name in _session_allowed


def session_allow(tool_name: str) -> None:
    _session_allowed.add(tool_name)


# ---------------------------------------------------------------------------
# Future resolution
# ---------------------------------------------------------------------------


def resolve_approval(message_id: int, emoji: str) -> None:
    """Resolve a pending approval Future. Safe to call from any context."""
    future = _pending.get(message_id)
    if future is None or future.done():
        return
    future.set_result(emoji)


def cancel_pending() -> None:
    """Cancel all pending approval Futures."""
    for future in _pending.values():
        if not future.done():
            future.cancel()
    _pending.clear()


def reset() -> None:
    """Clear session-allowed set and cancel all pending Futures. Called on /clear."""
    cancel_pending()
    _session_allowed.clear()


# ---------------------------------------------------------------------------
# Approval flow
# ---------------------------------------------------------------------------


async def request_approval(
    tool_name: str, input_data: dict[str, Any]
) -> PermissionResult:
    """Send approval message to Discord, await reaction, return result."""
    if is_session_allowed(tool_name):
        return PermissionResultAllow()

    channel = _channel
    assert channel is not None, "permissions.set_channel() not called before approval"

    label = format_tool_label(tool_name, json.dumps(input_data))
    text = f"`{label}` — react {APPROVE} allow {DENY} deny {ALWAYS} always"

    try:
        msg = await channel.send(text)
        await msg.add_reaction(APPROVE)
        await msg.add_reaction(DENY)
        await msg.add_reaction(ALWAYS)
    except discord.DiscordException:
        return PermissionResultDeny(message="failed to send approval request")

    loop = asyncio.get_running_loop()
    future: asyncio.Future[str] = loop.create_future()
    _pending[msg.id] = future

    try:
        emoji = await asyncio.wait_for(future, timeout=60)
    except (TimeoutError, asyncio.CancelledError):
        with contextlib.suppress(discord.DiscordException):
            await msg.edit(content=f"~~{text}~~ — timed out")
        return PermissionResultDeny(message="approval timed out")
    finally:
        _pending.pop(msg.id, None)

    if emoji == APPROVE:
        with contextlib.suppress(discord.DiscordException):
            await msg.edit(content=f"~~{text}~~ — allowed")
        return PermissionResultAllow()
    if emoji == ALWAYS:
        session_allow(tool_name)
        with contextlib.suppress(discord.DiscordException):
            await msg.edit(content=f"~~{text}~~ — always allowed")
        return PermissionResultAllow()

    with contextlib.suppress(discord.DiscordException):
        await msg.edit(content=f"~~{text}~~ — denied")
    return PermissionResultDeny(message="denied via Discord")


async def handle_tool_permission(
    tool_name: str,
    input_data: dict[str, Any],
    context: ToolPermissionContext,
) -> PermissionResult:
    """canUseTool callback — bg forks: deny; dontAsk: silent deny; else: Discord approval."""
    if in_bg_fork():
        return PermissionResultDeny(message=f"{tool_name} is not allowed")
    if _dont_ask:
        if is_session_allowed(tool_name):
            return PermissionResultAllow()
        return PermissionResultDeny(message=f"{tool_name} is not allowed")
    return await request_approval(tool_name, input_data)
