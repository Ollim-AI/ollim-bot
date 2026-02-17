"""Tests for discord_tools.py — chain context, follow_up_chain, fork tools."""

import asyncio

from ollim_bot.discord_tools import (
    ChainContext,
    follow_up_chain,
    pop_fork_saved,
    pop_pending_updates,
    report_updates,
    save_context,
    set_chain_context,
    set_in_fork,
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


# --- save_context tests ---

_save_ctx = save_context.handler


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


def test_fork_saved_cleared_after_pop():
    set_in_fork(True)
    _run(_save_ctx({}))
    pop_fork_saved()

    assert pop_fork_saved() is False
    set_in_fork(False)


def test_set_in_fork_resets_saved():
    set_in_fork(True)
    _run(_save_ctx({}))

    set_in_fork(True)  # re-entering fork resets the saved flag

    assert pop_fork_saved() is False
    set_in_fork(False)


# --- report_updates tests ---

_report = report_updates.handler


def test_report_updates_not_in_fork():
    set_in_fork(False)

    result = _run(_report({"message": "test"}))

    assert "Error" in result["content"][0]["text"]
    assert "not in a forked background session" in result["content"][0]["text"]


def test_report_updates_appends_to_file():
    pop_pending_updates()  # clear any stale state
    set_in_fork(True)

    _run(_report({"message": "Found 2 actionable emails"}))

    updates = pop_pending_updates()
    assert updates == ["Found 2 actionable emails"]
    set_in_fork(False)


def test_report_updates_does_not_save_fork():
    set_in_fork(True)

    _run(_report({"message": "minor update"}))

    assert pop_fork_saved() is False
    pop_pending_updates()  # cleanup
    set_in_fork(False)


def test_pop_pending_updates_clears_file():
    pop_pending_updates()  # clear stale state
    set_in_fork(True)
    _run(_report({"message": "update"}))
    pop_pending_updates()  # first pop clears

    assert pop_pending_updates() == []
    set_in_fork(False)


def test_multiple_updates_accumulate():
    pop_pending_updates()  # clear stale state
    set_in_fork(True)

    _run(_report({"message": "first finding"}))
    _run(_report({"message": "second finding"}))

    updates = pop_pending_updates()
    assert updates == ["first finding", "second finding"]
    set_in_fork(False)
