"""Tests for ChatChannel duck type."""

import pytest

from ollim_bot.chat import ChatChannel


@pytest.mark.asyncio
async def test_chat_channel_send_records():
    channel = ChatChannel()
    msg = await channel.send("hello", embed=object())
    assert msg.id == 1
    assert len(channel.messages) == 1
    assert channel.messages[0]["content"] == "hello"
    assert channel.messages[0]["embed"] is not None


@pytest.mark.asyncio
async def test_chat_channel_send_file():
    channel = ChatChannel()
    sentinel = object()
    msg = await channel.send(content="here", file=sentinel)
    assert msg.id == 1
    assert channel.messages[0]["file"] is sentinel


@pytest.mark.asyncio
async def test_chat_channel_increments_id():
    channel = ChatChannel()
    m1 = await channel.send("a")
    m2 = await channel.send("b")
    assert m1.id == 1
    assert m2.id == 2
    assert len(channel.messages) == 2
