"""Tests for ChatChannel duck type."""

import os
from types import SimpleNamespace

import pytest

from ollim_bot.chat import ChatChannel
from ollim_bot.runtime_config import BYPASS_PERMISSIONS


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


@pytest.mark.asyncio
async def test_chat_channel_multi_turn():
    channel = ChatChannel()
    m1 = await channel.send("first")
    m2 = await channel.send("second")
    assert m1.id == 1
    assert m2.id == 2
    assert len(channel.messages) == 2
    assert channel.messages[0]["content"] == "first"
    assert channel.messages[1]["content"] == "second"


@pytest.mark.asyncio
async def test_chat_channel_embed_captured():
    embed = SimpleNamespace(title="Status Update")
    channel = ChatChannel()
    await channel.send("with embed", embed=embed)
    assert channel.messages[0]["embed"] is embed
    assert channel.messages[0]["embed"].title == "Status Update"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chat_round_trip(data_dir):
    """Full agent pipeline with real model — requires OLLIM_CHAT_MODEL env var."""
    model = os.environ.get("OLLIM_CHAT_MODEL")
    if not model:
        pytest.skip("OLLIM_CHAT_MODEL not set")

    from dataclasses import replace

    from ollim_bot.agent import Agent
    from ollim_bot.channel import init_channel
    from ollim_bot.main import _ensure_sdk_layout
    from ollim_bot.streamer import StreamStatus

    _ensure_sdk_layout()
    channel = ChatChannel()
    init_channel(channel)

    agent = Agent()
    agent.options = replace(agent.options, model=model, permission_mode=BYPASS_PERMISSIONS)

    chunks = []
    async for chunk in agent.stream_chat("Say exactly: PONG. Nothing else."):
        if not isinstance(chunk, StreamStatus):
            chunks.append(chunk)

    await agent.close()
    text = "".join(chunks)
    assert "PONG" in text.upper(), f"Expected PONG in response, got: {text[:200]}"
