"""Stream agent responses to Discord channels with progressive message editing."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any, Literal

import discord

from ollim_bot.forks import enter_fork_requested
from ollim_bot.formatting import format_tool_label
from ollim_bot.permissions import is_denied
from ollim_bot.sessions import track_message

log = logging.getLogger(__name__)

# Discord allows ~5 edits per 5 seconds per channel.  0.5s gives a
# responsive feel; discord.py handles any 429s transparently.
EDIT_INTERVAL = 0.5
# Short initial delay so the first message accumulates a meaningful
# chunk of text instead of showing a single token like "I".
FIRST_FLUSH_DELAY = 0.2
MAX_MSG_LEN = 2000
# Seconds between timer ticks on the status message (e.g. "Thinking... (1s)").
STATUS_TICK = 1.0


@dataclass(frozen=True)
class StreamStatus:
    """Phase-transition signal from stream_chat to stream_to_channel."""

    kind: Literal["thinking_start", "tool_start", "phase_end", "compact_start"]
    label: str = ""
    compact_tokens: int | None = None


class StreamParser:
    """Stateful parser: Anthropic SSE event dicts → text deltas + StreamStatus signals."""

    def __init__(self) -> None:
        self._tool_name: str | None = None
        self._tool_input_buf = ""
        self._status_active = False
        self._deferred_labels: list[str] = []

    async def feed(self, event: dict[str, Any]) -> AsyncGenerator[str | StreamStatus, None]:
        """Process one SSE event dict."""
        etype = event.get("type")

        if etype == "content_block_start":
            block = event["content_block"]
            is_tool = block["type"] == "tool_use"
            async for item in self._drain(defer=is_tool):
                yield item
            if block["type"] == "thinking":
                yield StreamStatus(kind="thinking_start")
                self._status_active = True
            elif is_tool:
                self._tool_name = block["name"]
                self._tool_input_buf = ""

        elif etype == "content_block_delta":
            delta = event["delta"]
            if delta.get("type") == "input_json_delta":
                self._tool_input_buf += delta.get("partial_json", "")
            elif text := delta.get("text", ""):
                async for item in self._drain(defer=False):
                    yield item
                yield text

        elif etype == "content_block_stop":
            if self._tool_name is not None:
                label = format_tool_label(self._tool_name, self._tool_input_buf)
                yield StreamStatus(kind="tool_start", label=label)
                self._status_active = True
                self._deferred_labels.append(label)
                self._tool_name = None
            elif self._status_active:
                self._status_active = False
                yield StreamStatus(kind="phase_end")

    async def drain(self) -> AsyncGenerator[str | StreamStatus, None]:
        """Flush any active status phase. Call after the stream ends."""
        async for item in self._drain(defer=False):
            yield item

    async def _drain(self, *, defer: bool) -> AsyncGenerator[str | StreamStatus, None]:
        if self._status_active:
            self._status_active = False
            yield StreamStatus(kind="phase_end")
        if not defer and self._deferred_labels:
            for label in self._deferred_labels:
                if is_denied(label):
                    yield f"\n-# *~~{label}~~ — denied*\n"
                else:
                    yield f"\n-# *{label}*\n"
            self._deferred_labels.clear()


async def stream_to_channel(
    channel: discord.abc.Messageable,
    deltas: AsyncGenerator[str | StreamStatus, None],
) -> None:
    """Consume text deltas and stream them into a Discord channel.

    StreamStatus events control an ephemeral status message that shows
    live timers during thinking and tool execution.
    """
    buf = ""
    msg: discord.Message | None = None
    msg_start = 0  # index into buf where the current message begins
    stale = False  # True when buf has unflushed content
    stop = asyncio.Event()

    # Status line state -------------------------------------------------------
    status_msg: discord.Message | None = None
    status_label: str | None = None  # None = no active status
    status_start: float = 0.0
    status_last_edit: float = 0.0

    def _status_text() -> str:
        secs = int(time.monotonic() - status_start)
        label = status_label or "Thinking"
        if secs < STATUS_TICK:
            return f"-# *{label}...*"
        return f"-# *{label}... ({secs}s)*"

    async def _set_status(label: str) -> None:
        nonlocal status_msg, status_label, status_start, status_last_edit
        new_label = label or "Thinking"
        now = time.monotonic()
        # Only reset timer when the label changes (e.g. Thinking → tool).
        # When the same label is re-set (initial status → real thinking_start),
        # the timer keeps counting from the original start.
        if status_label != new_label:
            status_start = now
        status_label = new_label
        status_last_edit = now
        text = _status_text()
        if status_msg is None:
            status_msg = await channel.send(text)
        else:
            with contextlib.suppress(discord.NotFound, discord.HTTPException):
                await status_msg.edit(content=text)

    async def _clear_status() -> None:
        nonlocal status_msg, status_label
        if status_msg is not None:
            with contextlib.suppress(discord.NotFound, discord.HTTPException):
                await status_msg.delete()
            status_msg = None
        status_label = None

    # Auto-compaction state ----------------------------------------------------
    in_compact = False
    was_compacted = False
    _compact_tokens: int | None = None

    async def _finalize_compact() -> None:
        """Edit compaction timer to permanent annotation, force new message."""
        nonlocal status_msg, status_label, in_compact, msg, msg_start
        if status_msg is not None:
            secs = int(time.monotonic() - status_start)
            parts: list[str] = ["auto-compacted"]
            if _compact_tokens is not None:
                parts.append(f"{_compact_tokens / 1000:.0f}k tokens")
            if secs > 0:
                parts.append(f"{secs}s")
            note = " · ".join(parts)
            with contextlib.suppress(discord.NotFound, discord.HTTPException):
                await status_msg.edit(content=f"-# *{note}*")
            status_msg = None
        status_label = None
        in_compact = False
        # Force new message for post-compaction content
        msg = None
        msg_start = len(buf)

    # Response message management ----------------------------------------------

    async def flush() -> None:
        nonlocal msg, msg_start, stale
        chunk = buf[msg_start:]
        if not chunk or not stale:
            return
        if msg is None:
            msg = await channel.send(chunk[:MAX_MSG_LEN])
            track_message(msg.id)
        else:
            await msg.edit(content=chunk[:MAX_MSG_LEN])
        if len(chunk) <= MAX_MSG_LEN:
            stale = False
            return
        while len(buf) - msg_start > MAX_MSG_LEN:
            msg_start += MAX_MSG_LEN
            remaining = buf[msg_start:]
            if remaining:
                msg = await channel.send(remaining[:MAX_MSG_LEN])
                track_message(msg.id)
        stale = False

    async def _wait(seconds: float) -> None:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=seconds)

    async def editor() -> None:
        nonlocal status_last_edit
        await _wait(FIRST_FLUSH_DELAY)
        if stop.is_set():
            return
        await flush()
        while not stop.is_set():
            await _wait(EDIT_INTERVAL)
            if stop.is_set():
                return
            now = time.monotonic()
            if status_label is not None and status_msg is not None and now - status_last_edit >= STATUS_TICK:
                status_last_edit = now
                with contextlib.suppress(discord.NotFound, discord.HTTPException):
                    await status_msg.edit(content=_status_text())
            elif stale:
                await flush()
            elif msg is not None:
                await channel.typing()

    task = asyncio.create_task(editor())
    # Immediate feedback: show "Thinking..." before the API sends its first
    # event.  Eliminates the dead zone between client.query() and the first
    # SSE event where only the typing indicator was visible.  When the real
    # thinking_start arrives, _set_status sees the same label and keeps the
    # timer running (no reset).  If text arrives first (no thinking), the
    # text-delta handler clears it automatically.
    await _set_status("")
    try:
        async for item in deltas:
            if isinstance(item, StreamStatus):
                if in_compact and item.kind != "compact_start":
                    await _finalize_compact()
                if item.kind == "compact_start":
                    await flush()  # commit pre-compaction content to its own msg
                    await _set_status(item.label)
                    _compact_tokens = item.compact_tokens
                    in_compact = True
                    was_compacted = True
                elif item.kind == "thinking_start":
                    await _set_status("")
                elif item.kind == "tool_start":
                    await _set_status(item.label)
                else:  # phase_end
                    await _clear_status()
            else:
                if in_compact:
                    await _finalize_compact()
                elif status_label is not None:
                    await _clear_status()
                buf += item
                stale = True
    finally:
        stop.set()
        await task

    if in_compact:
        await _finalize_compact()
    else:
        await _clear_status()

    stale = True
    await flush()

    if not buf and not enter_fork_requested() and not was_compacted:
        log.error("empty agent response — no text or tool output received")
        msg = await channel.send("error: empty response from agent.")
        track_message(msg.id)
