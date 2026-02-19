"""Tests for agent_tools.py — chain context, follow_up_chain, tool handlers."""

import asyncio

import ollim_bot.forks as forks_mod
from ollim_bot.agent_tools import (
    ChainContext,
    follow_up_chain,
    report_updates,
    save_context,
    set_chain_context,
)
from ollim_bot.forks import pop_fork_saved, pop_pending_updates, set_in_fork

# @tool decorator wraps the function in SdkMcpTool; .handler is the raw async fn
_follow_up = follow_up_chain.handler
_save_ctx = save_context.handler
_report = report_updates.handler


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --- Chain context ---


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


# --- save_context (bg fork mode) ---


def test_save_context_not_in_fork():
    set_in_fork(False)

    result = _run(_save_ctx({}))

    assert "Error" in result["content"][0]["text"]
    assert "not in a forked background session" in result["content"][0]["text"]


def test_save_context_sets_flag():
    set_in_fork(True)

    _run(_save_ctx({}))

    assert pop_fork_saved() is True
    set_in_fork(False)


def test_save_context_clears_pending_updates():
    pop_pending_updates()
    set_in_fork(True)
    forks_mod._append_update("pre-save update")

    _run(_save_ctx({}))

    assert forks_mod.peek_pending_updates() == []
    pop_fork_saved()
    set_in_fork(False)


# --- report_updates (bg fork mode) ---


def test_report_updates_not_in_fork():
    set_in_fork(False)

    result = _run(_report({"message": "test"}))

    assert "Error" in result["content"][0]["text"]
    assert "not in a forked background session" in result["content"][0]["text"]


def test_report_updates_appends_to_file():
    pop_pending_updates()
    set_in_fork(True)

    _run(_report({"message": "Found 2 actionable emails"}))

    updates = pop_pending_updates()
    assert updates == ["Found 2 actionable emails"]
    set_in_fork(False)


def test_report_updates_does_not_save_fork():
    set_in_fork(True)

    _run(_report({"message": "minor update"}))

    assert pop_fork_saved() is False
    pop_pending_updates()
    set_in_fork(False)
