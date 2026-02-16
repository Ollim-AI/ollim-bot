"""Tests for discord_tools.py — chain context and follow_up_chain tool."""

import asyncio

from ollim_bot.discord_tools import (
    ChainContext,
    follow_up_chain,
    set_chain_context,
)

# @tool decorator wraps the function in SdkMcpTool; .handler is the raw async fn
_follow_up = follow_up_chain.handler


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_chain_context_is_frozen():
    ctx = ChainContext(
        reminder_id="abc",
        message="test",
        chain_depth=0,
        max_chain=2,
        chain_parent="abc",
        background=True,
    )

    assert ctx.reminder_id == "abc"
    assert ctx.chain_depth == 0


def test_follow_up_chain_no_context():
    set_chain_context(None)

    result = _run(_follow_up({"minutes_from_now": 30}))

    assert "Error" in result["content"][0]["text"]
    assert "no active reminder context" in result["content"][0]["text"]


def test_follow_up_chain_at_max_depth():
    ctx = ChainContext(
        reminder_id="abc",
        message="test",
        chain_depth=2,
        max_chain=2,
        chain_parent="abc",
        background=True,
    )
    set_chain_context(ctx)

    result = _run(_follow_up({"minutes_from_now": 30}))

    assert "Error" in result["content"][0]["text"]
    assert "limit reached" in result["content"][0]["text"]
    set_chain_context(None)


def test_set_chain_context_roundtrip():
    ctx = ChainContext(
        reminder_id="xyz",
        message="check",
        chain_depth=1,
        max_chain=3,
        chain_parent="xyz",
        background=False,
    )

    set_chain_context(ctx)
    set_chain_context(None)

    result = _run(_follow_up({"minutes_from_now": 10}))
    assert "no active reminder context" in result["content"][0]["text"]
