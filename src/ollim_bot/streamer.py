"""Stream agent responses to Discord channels with progressive message editing."""

import asyncio
from collections.abc import AsyncGenerator

import discord

# Edit at most once per second (Discord allows ~5 edits / 5 seconds).
EDIT_INTERVAL = 1.0
MAX_MSG_LEN = 2000


async def stream_to_channel(
    channel: discord.abc.Messageable,
    deltas: AsyncGenerator[str, None],
) -> None:
    """Consume text deltas and stream them into a Discord channel.

    Sends a Discord message on the first delta, then edits it at a
    throttled rate as more text arrives.  When the buffer exceeds
    2 000 chars the first message is frozen and overflow is sent as
    additional messages at the end.
    """
    buf = ""
    msg: discord.Message | None = None
    last_edit = 0.0

    async for text in deltas:
        buf += text
        now = asyncio.get_event_loop().time()

        if msg is None and buf:
            msg = await channel.send(buf[:MAX_MSG_LEN])
            last_edit = now
        elif msg and len(buf) <= MAX_MSG_LEN and now - last_edit >= EDIT_INTERVAL:
            await msg.edit(content=buf)
            last_edit = now

    # Final flush
    if not buf:
        await channel.send("hmm, I didn't have a response for that.")
        return

    if msg:
        await msg.edit(content=buf[:MAX_MSG_LEN])
        for i in range(MAX_MSG_LEN, len(buf), MAX_MSG_LEN):
            await channel.send(buf[i : i + MAX_MSG_LEN])
    else:
        for i in range(0, len(buf), MAX_MSG_LEN):
            await channel.send(buf[i : i + MAX_MSG_LEN])
