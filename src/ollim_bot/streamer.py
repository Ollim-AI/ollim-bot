"""Stream agent responses to Discord channels with progressive message editing."""

import asyncio
from collections.abc import AsyncGenerator

import discord

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

    async def flush():
        nonlocal msg, msg_start, stale
        chunk = buf[msg_start:]
        if not chunk or not stale:
            return
        if msg is None:
            msg = await channel.send(chunk[:MAX_MSG_LEN])
        else:
            await msg.edit(content=chunk[:MAX_MSG_LEN])
        # Overflow: finalize current message, start new ones
        while len(buf) - msg_start > MAX_MSG_LEN:
            msg_start += MAX_MSG_LEN
            remaining = buf[msg_start:]
            if remaining:
                msg = await channel.send(remaining[:MAX_MSG_LEN])
        stale = False

    async def editor():
        # Short initial delay to buffer first message, then regular interval.
        await asyncio.sleep(FIRST_FLUSH_DELAY)
        await flush()
        while True:
            await asyncio.sleep(EDIT_INTERVAL)
            await flush()

    task = asyncio.create_task(editor())
    try:
        async for text in deltas:
            buf += text
            stale = True
    finally:
        task.cancel()

    stale = True
    await flush()

    if not buf:
        await channel.send("hmm, I didn't have a response for that.")
