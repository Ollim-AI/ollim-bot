"""Stream agent responses to Discord channels with progressive message editing."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Literal

import discord

from ollim_bot.forks import enter_fork_requested
from ollim_bot.sessions import track_message

# Discord allows ~5 edits per 5 seconds per channel.  0.5s gives a
# responsive feel; discord.py handles any 429s transparently.
EDIT_INTERVAL = 0.5
# Short initial delay so the first message accumulates a meaningful
# chunk of text instead of showing a single token like "I".
FIRST_FLUSH_DELAY = 0.2
MAX_MSG_LEN = 2000
# Seconds between timer ticks on the status message (e.g. "Thinking... (3s)").
STATUS_TICK = 3.0


@dataclass(frozen=True)
class StreamStatus:
    """Phase-transition signal from stream_chat to stream_to_channel."""

    kind: Literal["thinking_start", "tool_start", "phase_end"]
    label: str = ""


async def stream_to_channel(
    channel: discord.abc.Messageable,
    deltas: AsyncGenerator[str | StreamStatus, None],
) -> None:
    """Consume text deltas and stream them into a Discord channel.

    StreamStatus events control an ephemeral status message that shows
    live timers during thinking and tool execution phases.
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
        status_label = label or "Thinking"
        now = time.monotonic()
        status_start = now
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
    try:
        async for item in deltas:
            if isinstance(item, StreamStatus):
                if item.kind == "thinking_start":
                    await _set_status("")
                elif item.kind == "tool_start":
                    await _set_status(item.label)
                else:  # phase_end
                    await _clear_status()
            else:
                if status_label is not None:
                    await _clear_status()
                buf += item
                stale = True
    finally:
        stop.set()
        await task

    await _clear_status()

    stale = True
    await flush()

    if not buf and not enter_fork_requested():
        msg = await channel.send("hmm, I didn't have a response for that.")
        track_message(msg.id)
