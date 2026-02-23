"""Tests for agent_tools.py — chain context, follow_up_chain, tool handlers."""

import asyncio

from ollim_bot.agent_tools import (
    ChainContext,
    discord_embed,
    enter_fork,
    exit_fork,
    follow_up_chain,
    ping_user,
    report_updates,
    save_context,
    set_chain_context,
    set_channel,
    set_fork_channel,
)
from ollim_bot import ping_budget
from ollim_bot.forks import (
    ForkExitAction,
    pop_enter_fork,
    pop_exit_action,
    pop_pending_updates,
    set_in_fork,
    set_interactive_fork,
)

# @tool decorator wraps the function in SdkMcpTool; .handler is the raw async fn
_follow_up = follow_up_chain.handler
_save_ctx = save_context.handler
_report = report_updates.handler
_enter = enter_fork.handler
_exit = exit_fork.handler
_ping = ping_user.handler
_embed = discord_embed.handler


class _FakeMessage:
    _next_id = 1

    def __init__(self):
        self.id = _FakeMessage._next_id
        _FakeMessage._next_id += 1


class InMemoryChannel:
    """Collects messages and embeds sent to a channel."""

    def __init__(self):
        self.messages: list[dict] = []

    async def send(self, content=None, *, embed=None, view=None):
        self.messages.append({"content": content, "embed": embed, "view": view})
        return _FakeMessage()


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
    assert "not in an interactive fork" in result["content"][0]["text"]


def test_save_context_blocked_in_bg_fork():
    set_in_fork(True)

    result = _run(_save_ctx({}))

    assert "Error" in result["content"][0]["text"]
    assert "not available in background forks" in result["content"][0]["text"]
    set_in_fork(False)


# --- report_updates (bg fork mode) ---


def test_report_updates_not_in_fork():
    set_in_fork(False)

    result = _run(_report({"message": "test"}))

    assert "Error" in result["content"][0]["text"]
    assert "not in a forked session" in result["content"][0]["text"]


def test_report_updates_appends_to_file():
    _run(pop_pending_updates())
    set_in_fork(True)

    _run(_report({"message": "Found 2 actionable emails"}))

    updates = _run(pop_pending_updates())
    assert [u.message for u in updates] == ["Found 2 actionable emails"]
    set_in_fork(False)


# --- enter_fork ---


def test_enter_fork_sets_request():
    result = _run(_enter({"topic": "research ML papers", "idle_timeout": 15}))

    assert "Entering fork" in result["content"][0]["text"]
    topic, timeout = pop_enter_fork()
    assert topic == "research ML papers"
    assert timeout == 15


def test_enter_fork_no_topic():
    result = _run(_enter({}))

    assert "Entering fork" in result["content"][0]["text"]
    topic, timeout = pop_enter_fork()
    assert topic is None
    assert timeout == 10


def test_enter_fork_while_in_bg_fork():
    set_in_fork(True)

    result = _run(_enter({}))

    assert "Error" in result["content"][0]["text"]
    assert "already in a fork" in result["content"][0]["text"]
    pop_enter_fork()
    set_in_fork(False)


def test_enter_fork_while_in_interactive_fork():
    set_interactive_fork(True, idle_timeout=10)

    result = _run(_enter({}))

    assert "Error" in result["content"][0]["text"]
    assert "already in a fork" in result["content"][0]["text"]
    pop_enter_fork()
    set_interactive_fork(False)


# --- exit_fork ---


def test_exit_fork_not_in_fork():
    result = _run(_exit({}))

    assert "Error" in result["content"][0]["text"]
    assert "not in an interactive fork" in result["content"][0]["text"]


def test_exit_fork_in_interactive_fork():
    set_interactive_fork(True, idle_timeout=10)

    result = _run(_exit({}))

    assert "discarded" in result["content"][0]["text"].lower()
    assert pop_exit_action() is ForkExitAction.EXIT
    set_interactive_fork(False)


# --- save_context (interactive fork mode) ---


def test_save_context_in_interactive_fork():
    set_interactive_fork(True, idle_timeout=10)

    result = _run(_save_ctx({}))

    assert "promoted" in result["content"][0]["text"].lower()
    assert pop_exit_action() is ForkExitAction.SAVE
    set_interactive_fork(False)


def test_save_context_blocked_in_bg_fork_even_with_interactive():
    """Bg fork check is authoritative — blocks save_context even if interactive fork exists."""
    set_in_fork(True)
    set_interactive_fork(True, idle_timeout=10)

    result = _run(_save_ctx({}))

    assert "Error" in result["content"][0]["text"]
    assert "not available in background forks" in result["content"][0]["text"]
    assert pop_exit_action() is ForkExitAction.NONE
    set_interactive_fork(False)
    set_in_fork(False)


# --- report_updates (interactive fork mode) ---


def test_report_updates_in_interactive_fork():
    _run(pop_pending_updates())
    set_in_fork(False)
    set_interactive_fork(True, idle_timeout=10)

    _run(_report({"message": "found 3 papers"}))

    assert pop_exit_action() is ForkExitAction.REPORT
    assert [u.message for u in _run(pop_pending_updates())] == ["found 3 papers"]
    set_interactive_fork(False)


# --- ping_user source gating ---


def test_ping_user_blocked_on_main():
    set_in_fork(False)
    set_interactive_fork(False)

    result = _run(_ping({"message": "hello"}))

    assert "Error" in result["content"][0]["text"]
    assert "only available in background forks" in result["content"][0]["text"]


def test_ping_user_blocked_on_interactive_fork():
    set_interactive_fork(True, idle_timeout=10)

    result = _run(_ping({"message": "hello"}))

    assert "Error" in result["content"][0]["text"]
    assert "only available in background forks" in result["content"][0]["text"]
    set_interactive_fork(False)


def test_ping_user_prefixed_in_bg_fork(data_dir):
    ch = InMemoryChannel()
    set_fork_channel(ch)
    set_in_fork(True)

    result = _run(_ping({"message": "check your tasks"}))

    assert result["content"][0]["text"] == "Message sent."
    assert ch.messages[0]["content"] == "[bg] check your tasks"
    set_in_fork(False)


# --- discord_embed footer ---  # duplicate-ok (implementing from plan)


def test_embed_no_footer_on_main():
    ch = InMemoryChannel()
    set_fork_channel(None)  # clear contextvar from prior bg fork test
    set_channel(ch)
    set_in_fork(False)
    set_interactive_fork(False)

    _run(_embed({"title": "Tasks"}))

    assert ch.messages[0]["embed"].footer.text is None
    set_channel(None)


def test_embed_footer_bg_fork(data_dir):
    ch = InMemoryChannel()
    set_fork_channel(ch)
    set_in_fork(True)

    _run(_embed({"title": "Tasks"}))

    assert ch.messages[0]["embed"].footer.text == "bg"
    set_in_fork(False)


def test_embed_footer_interactive_fork(data_dir):
    ch = InMemoryChannel()
    set_fork_channel(None)  # clear contextvar from prior bg fork test
    set_channel(ch)
    set_interactive_fork(True, idle_timeout=10)

    _run(_embed({"title": "Tasks"}))

    assert ch.messages[0]["embed"].footer.text == "fork"
    set_interactive_fork(False)
    set_channel(None)


# --- bg output tracking + stop hook ---  # duplicate-ok (implementing from plan)


def test_bg_output_flag_set_on_ping(data_dir):
    from ollim_bot.agent_tools import bg_output_sent

    ch = InMemoryChannel()
    set_fork_channel(ch)
    set_in_fork(True)

    async def _check():
        await _ping({"message": "test"})
        return bg_output_sent()

    assert _run(_check()) is True
    set_in_fork(False)


def test_bg_output_flag_set_on_embed(data_dir):
    from ollim_bot.agent_tools import bg_output_sent

    ch = InMemoryChannel()
    set_fork_channel(ch)
    set_in_fork(True)

    async def _check():
        await _embed({"title": "Test"})
        return bg_output_sent()

    assert _run(_check()) is True
    set_in_fork(False)


def test_bg_output_flag_cleared_on_report(data_dir):
    from ollim_bot.agent_tools import bg_output_sent

    ch = InMemoryChannel()
    set_fork_channel(ch)
    _run(pop_pending_updates())
    set_in_fork(True)

    async def _check():
        await _ping({"message": "test"})
        await _report({"message": "summary"})
        return bg_output_sent()

    assert _run(_check()) is False
    set_in_fork(False)


def test_stop_hook_allows_normal_stop():
    from ollim_bot.agent_tools import require_report_hook

    set_in_fork(False)

    result = _run(require_report_hook({}, None, {"signal": None}))

    assert result == {}


def test_stop_hook_allows_bg_stop_without_output():
    from ollim_bot.agent_tools import require_report_hook

    set_in_fork(True)

    result = _run(require_report_hook({}, None, {"signal": None}))

    assert result == {}
    set_in_fork(False)


def test_stop_hook_blocks_bg_stop_with_unreported_output(data_dir):
    from ollim_bot.agent_tools import require_report_hook

    ch = InMemoryChannel()
    set_fork_channel(ch)
    set_in_fork(True)

    async def _check():
        await _ping({"message": "test"})
        return await require_report_hook({}, None, {"signal": None})

    result = _run(_check())

    assert "report_updates" in result.get("systemMessage", "")
    set_in_fork(False)


# --- ping budget enforcement ---


def test_ping_user_blocked_when_budget_exhausted(data_dir):
    from datetime import date

    ch = InMemoryChannel()
    set_fork_channel(ch)
    set_in_fork(True)
    ping_budget.save(
        ping_budget.BudgetState(
            daily_limit=2,
            used=2,
            critical_used=0,
            last_reset=date.today().isoformat(),
        )
    )

    result = _run(_ping({"message": "hello"}))

    assert "Budget exhausted" in result["content"][0]["text"]
    assert len(ch.messages) == 0
    set_in_fork(False)


def test_ping_user_critical_bypasses_budget(data_dir):
    from datetime import date

    ch = InMemoryChannel()
    set_fork_channel(ch)
    set_in_fork(True)
    ping_budget.save(
        ping_budget.BudgetState(
            daily_limit=2,
            used=2,
            critical_used=0,
            last_reset=date.today().isoformat(),
        )
    )

    result = _run(_ping({"message": "urgent!", "critical": True}))

    assert result["content"][0]["text"] == "Message sent."
    assert ping_budget.load().critical_used == 1
    set_in_fork(False)


def test_embed_blocked_when_budget_exhausted_in_bg(data_dir):
    from datetime import date

    ch = InMemoryChannel()
    set_fork_channel(ch)
    set_in_fork(True)
    ping_budget.save(
        ping_budget.BudgetState(
            daily_limit=1,
            used=1,
            critical_used=0,
            last_reset=date.today().isoformat(),
        )
    )

    result = _run(_embed({"title": "Tasks"}))

    assert "Budget exhausted" in result["content"][0]["text"]
    assert len(ch.messages) == 0
    set_in_fork(False)


def test_embed_not_blocked_on_main_session(data_dir):
    from datetime import date

    ch = InMemoryChannel()
    set_fork_channel(None)
    set_channel(ch)
    set_in_fork(False)
    set_interactive_fork(False)
    ping_budget.save(
        ping_budget.BudgetState(
            daily_limit=1,
            used=1,
            critical_used=0,
            last_reset=date.today().isoformat(),
        )
    )

    result = _run(_embed({"title": "Tasks"}))

    assert result["content"][0]["text"] == "Embed sent."
    assert len(ch.messages) == 1
    set_channel(None)


def test_embed_critical_bypasses_budget_in_bg(data_dir):
    from datetime import date

    ch = InMemoryChannel()
    set_fork_channel(ch)
    set_in_fork(True)
    ping_budget.save(
        ping_budget.BudgetState(
            daily_limit=1,
            used=1,
            critical_used=0,
            last_reset=date.today().isoformat(),
        )
    )

    result = _run(_embed({"title": "Urgent", "critical": True}))

    assert result["content"][0]["text"] == "Embed sent."
    assert ping_budget.load().critical_used == 1
    assert len(ch.messages) == 1
    set_in_fork(False)


def test_ping_user_decrements_budget(data_dir):
    from datetime import date

    ch = InMemoryChannel()
    set_fork_channel(ch)
    set_in_fork(True)
    ping_budget.save(
        ping_budget.BudgetState(
            daily_limit=5,
            used=0,
            critical_used=0,
            last_reset=date.today().isoformat(),
        )
    )

    _run(_ping({"message": "test"}))

    assert ping_budget.load().used == 1
    set_in_fork(False)
