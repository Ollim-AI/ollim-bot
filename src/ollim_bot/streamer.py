"""Stream agent responses to Discord channels with progressive message editing."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from ollim_bot.agent import Agent

# Discord allows ~5 edits per 5 seconds per channel.  0.5s gives a
# responsive feel; discord.py handles any 429s transparently.
EDIT_INTERVAL = 0.5
# Short initial delay so the first message accumulates a meaningful
# chunk of text instead of showing a single token like "I".
FIRST_FLUSH_DELAY = 0.2
MAX_MSG_LEN = 2000


async def stream_to_channel(
    channel: discord.abc.Messageable,
    deltas: AsyncGenerator[str, None],
) -> None:
    """Consume text deltas and stream them into a Discord channel.

    A background task edits the message at a fixed interval, so
    updates appear even during pauses (e.g. tool execution).
    Overflow (>2000 chars) finalizes the current message and starts
    a new one.
    """
    buf = ""
    msg: discord.Message | None = None
    msg_start = 0  # index into buf where the current message begins
    stale = False  # True when buf has unflushed content
    stop = asyncio.Event()

    async def flush():
        nonlocal msg, msg_start, stale
        chunk = buf[msg_start:]
        if not chunk or not stale:
            return
        if msg is None:
            msg = await channel.send(chunk[:MAX_MSG_LEN])
        else:
            await msg.edit(content=chunk[:MAX_MSG_LEN])
        # Only overflow when the snapshot itself exceeded the limit.
        # If chunk < MAX_MSG_LEN, the message isn't full yet -- new text
        # that arrived during the await will be picked up by the next flush.
        if len(chunk) <= MAX_MSG_LEN:
            stale = False
            return
        # Overflow: finalize current message, start new ones
        while len(buf) - msg_start > MAX_MSG_LEN:
            msg_start += MAX_MSG_LEN
            remaining = buf[msg_start:]
            if remaining:
                msg = await channel.send(remaining[:MAX_MSG_LEN])
        stale = False

    async def _wait(seconds: float) -> None:
        """Sleep that can be interrupted by the stop event."""
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=seconds)

    async def editor():
        await _wait(FIRST_FLUSH_DELAY)
        if stop.is_set():
            return
        await flush()
        while not stop.is_set():
            await _wait(EDIT_INTERVAL)
            if stop.is_set():
                return
            if stale:
                await flush()
            elif msg is not None:
                # No new content but response isn't done -- show typing
                # during pauses (e.g. tool execution).
                await channel.typing()

    task = asyncio.create_task(editor())
    try:
        async for text in deltas:
            buf += text
            stale = True
    finally:
        stop.set()
        await task

    stale = True
    await flush()

    if not buf:
        await channel.send("hmm, I didn't have a response for that.")


async def dispatch_agent_response(
    agent: Agent,
    channel: discord.abc.Messageable,
    user_id: str,
    prompt: str,
    *,
    images: list[dict[str, str]] | None = None,
) -> None:
    """set_channel → typing → stream. Caller must hold agent.lock(user_id)."""
    from ollim_bot.discord_tools import set_channel

    set_channel(channel)
    await channel.typing()
    await stream_to_channel(
        channel, agent.stream_chat(prompt, user_id=user_id, images=images)
    )


async def send_agent_dm(
    owner: discord.User, agent: Agent, user_id: str, prompt: str
) -> None:
    """Inject a prompt into the agent session and stream the response as a DM."""
    dm = await owner.create_dm()
    async with agent.lock(user_id):
        await dispatch_agent_response(agent, dm, user_id, prompt)


async def run_agent_background(
    owner: discord.User,
    agent: Agent,
    user_id: str,
    prompt: str,
    *,
    skip_if_busy: bool,
) -> None:
    """Run agent on a forked session -- discard fork unless save_context is called."""
    from ollim_bot.discord_tools import pop_fork_saved, set_channel, set_in_fork
    from ollim_bot.sessions import save_session_id

    dm = await owner.create_dm()

    if skip_if_busy and agent.lock(user_id).locked():
        return

    async with agent.lock(user_id):
        set_channel(dm)
        set_in_fork(True)

        forked_session_id: str | None = None
        try:
            client = await agent.create_forked_client(user_id)
            try:
                forked_session_id = await agent.run_on_client(client, prompt)
            finally:
                with contextlib.suppress(Exception):
                    await client.disconnect()
        finally:
            set_in_fork(False)
            if forked_session_id is None:
                pop_fork_saved()  # clear leaked flag on error

        if pop_fork_saved():
            save_session_id(user_id, forked_session_id)
            await agent.drop_client(user_id)
