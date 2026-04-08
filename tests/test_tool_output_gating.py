"""Tests for agent_tools.py — ping_user, discord_embed, budget, busy, and output gating."""

import asyncio
from typing import cast

from claude_agent_sdk.types import HookContext, HookInput, StopHookInput

from ollim_bot import ping_budget
from ollim_bot.agent_tools import (
    discord_embed,
    ping_user,
    report_updates,
)
from ollim_bot.channel import init_channel
from ollim_bot.fork_state import (
    BgForkConfig,
    init_bg_tracking,
    set_bg_fork_config,
    set_busy,
    set_in_fork,
    set_interactive_fork,
)
from ollim_bot.forks import pop_pending_updates

_report = report_updates.handler
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


_STOP_INPUT = cast(
    HookInput,
    StopHookInput(
        session_id="",
        transcript_path="",
        cwd="",
        hook_event_name="Stop",
        stop_hook_active=True,
    ),
)
_STOP_CTX = cast(HookContext, {"signal": None})


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


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
    init_channel(ch)
    set_in_fork(True)
    init_bg_tracking()

    result = _run(_ping({"message": "check your tasks"}))

    assert result["content"][0]["text"] == "Message sent."
    assert ch.messages[0]["content"] == "[bg] check your tasks"
    set_in_fork(False)


# --- discord_embed footer ---


def test_embed_no_footer_on_main():
    ch = InMemoryChannel()
    init_channel(ch)
    set_in_fork(False)
    set_interactive_fork(False)

    _run(_embed({"title": "Tasks"}))

    assert ch.messages[0]["embed"].footer.text is None
    init_channel(None)


def test_embed_footer_bg_fork(data_dir):
    ch = InMemoryChannel()
    init_channel(ch)
    set_in_fork(True)
    init_bg_tracking()

    _run(_embed({"title": "Tasks"}))

    assert ch.messages[0]["embed"].footer.text == "bg"
    set_in_fork(False)


def test_embed_footer_interactive_fork(data_dir):
    ch = InMemoryChannel()
    init_channel(ch)
    set_interactive_fork(True, idle_timeout=10)

    _run(_embed({"title": "Tasks"}))

    assert ch.messages[0]["embed"].footer.text == "fork"
    set_interactive_fork(False)
    init_channel(None)


# --- bg output tracking + stop hook ---


def test_bg_output_flag_set_on_ping(data_dir):
    from ollim_bot.fork_state import get_bg_tracking

    ch = InMemoryChannel()
    init_channel(ch)
    set_in_fork(True)
    init_bg_tracking()

    async def _check():
        await _ping({"message": "test"})
        t = get_bg_tracking()
        assert t is not None
        return t.output_sent

    assert _run(_check()) is True
    set_in_fork(False)


def test_bg_output_flag_set_on_embed(data_dir):
    from ollim_bot.fork_state import get_bg_tracking

    ch = InMemoryChannel()
    init_channel(ch)
    set_in_fork(True)
    init_bg_tracking()

    async def _check():
        await _embed({"title": "Test"})
        t = get_bg_tracking()
        assert t is not None
        return t.output_sent

    assert _run(_check()) is True
    set_in_fork(False)


def test_bg_output_flag_cleared_on_report(data_dir):
    from ollim_bot.fork_state import get_bg_tracking

    ch = InMemoryChannel()
    init_channel(ch)
    _run(pop_pending_updates())
    set_in_fork(True)
    init_bg_tracking()

    async def _check():
        await _ping({"message": "test"})
        await _report({"message": "summary"})
        t = get_bg_tracking()
        assert t is not None
        return t.output_sent

    assert _run(_check()) is False
    set_in_fork(False)


def test_stop_hook_allows_normal_stop():
    from ollim_bot.agent_tools import require_report_hook

    set_in_fork(False)

    result = _run(require_report_hook(_STOP_INPUT, None, _STOP_CTX))

    assert result == {}


def test_stop_hook_allows_bg_stop_without_output():
    from ollim_bot.agent_tools import require_report_hook

    set_in_fork(True)
    init_bg_tracking()

    result = _run(require_report_hook(_STOP_INPUT, None, _STOP_CTX))

    assert result == {}
    set_in_fork(False)


def test_stop_hook_blocks_bg_stop_with_unreported_output(data_dir):
    from ollim_bot.agent_tools import require_report_hook

    ch = InMemoryChannel()
    init_channel(ch)
    set_in_fork(True)
    init_bg_tracking()

    async def _check():
        await _ping({"message": "test"})
        return await require_report_hook(_STOP_INPUT, None, _STOP_CTX)

    result = _run(_check())

    assert "report_updates" in result.get("systemMessage", "")
    set_in_fork(False)


# --- ping budget enforcement ---


def _exhausted_budget() -> ping_budget.BudgetState:
    from datetime import date, datetime

    from ollim_bot.config import TZ

    return ping_budget.BudgetState(
        capacity=5,
        available=0.0,
        refill_rate_minutes=90,
        last_refill=datetime.now(TZ).isoformat(),
        critical_used=0,
        critical_reset_date=date.today().isoformat(),
        daily_used=5,
        daily_used_reset=date.today().isoformat(),
    )


def test_ping_user_blocked_when_budget_exhausted(data_dir):
    ch = InMemoryChannel()
    init_channel(ch)
    set_in_fork(True)
    ping_budget.save(_exhausted_budget())

    result = _run(_ping({"message": "hello"}))

    assert "Budget exhausted" in result["content"][0]["text"]
    assert len(ch.messages) == 0
    set_in_fork(False)


def test_ping_user_critical_bypasses_budget(data_dir):
    ch = InMemoryChannel()
    init_channel(ch)
    set_in_fork(True)
    ping_budget.save(_exhausted_budget())

    result = _run(_ping({"message": "urgent!", "critical": True}))

    assert result["content"][0]["text"] == "Message sent."
    assert ping_budget.load().critical_used == 1
    set_in_fork(False)


def test_embed_blocked_when_budget_exhausted_in_bg(data_dir):
    ch = InMemoryChannel()
    init_channel(ch)
    set_in_fork(True)
    ping_budget.save(_exhausted_budget())

    result = _run(_embed({"title": "Tasks"}))

    assert "Budget exhausted" in result["content"][0]["text"]
    assert len(ch.messages) == 0
    set_in_fork(False)


def test_embed_not_blocked_on_main_session(data_dir):
    ch = InMemoryChannel()
    init_channel(None)
    init_channel(ch)
    set_in_fork(False)
    set_interactive_fork(False)
    ping_budget.save(_exhausted_budget())

    result = _run(_embed({"title": "Tasks"}))

    assert result["content"][0]["text"] == "Embed sent."
    assert len(ch.messages) == 1
    init_channel(None)


def test_embed_critical_bypasses_budget_in_bg(data_dir):
    ch = InMemoryChannel()
    init_channel(ch)
    set_in_fork(True)
    ping_budget.save(_exhausted_budget())

    result = _run(_embed({"title": "Urgent", "critical": True}))

    assert result["content"][0]["text"] == "Embed sent."
    assert ping_budget.load().critical_used == 1
    assert len(ch.messages) == 1
    set_in_fork(False)


def test_ping_user_decrements_budget(data_dir):
    ch = InMemoryChannel()
    init_channel(ch)
    set_in_fork(True)
    ping_budget.load()  # ensure defaults (5 available)

    _run(_ping({"message": "test"}))

    assert ping_budget.load().daily_used == 1
    set_in_fork(False)


# --- busy enforcement ---


def test_ping_user_blocked_when_busy():
    ch = InMemoryChannel()
    init_channel(ch)
    set_in_fork(True)
    set_busy(True)

    result = _run(_ping({"message": "hey"}))

    assert "mid-conversation" in result["content"][0]["text"]
    assert len(ch.messages) == 0
    set_in_fork(False)
    set_busy(False)


def test_ping_user_critical_bypasses_busy(data_dir):
    ch = InMemoryChannel()
    init_channel(ch)
    set_in_fork(True)
    set_busy(True)

    result = _run(_ping({"message": "urgent", "critical": True}))

    assert result["content"][0]["text"] == "Message sent."
    assert len(ch.messages) == 1
    set_in_fork(False)
    set_busy(False)


def test_embed_blocked_when_busy():
    ch = InMemoryChannel()
    init_channel(ch)
    set_in_fork(True)
    set_busy(True)

    result = _run(_embed({"title": "test"}))

    assert "mid-conversation" in result["content"][0]["text"]
    assert len(ch.messages) == 0
    set_in_fork(False)
    set_busy(False)


def test_embed_critical_bypasses_busy(data_dir):
    ch = InMemoryChannel()
    init_channel(ch)
    set_in_fork(True)
    set_busy(True)

    result = _run(_embed({"title": "Urgent", "critical": True}))

    assert result["content"][0]["text"] == "Embed sent."
    assert len(ch.messages) == 1
    set_in_fork(False)
    set_busy(False)


# --- allow_ping enforcement ---


def test_ping_user_blocked_when_allow_ping_false(data_dir):
    ch = InMemoryChannel()
    init_channel(ch)
    set_in_fork(True)
    set_bg_fork_config(BgForkConfig(allow_ping=False))

    result = _run(_ping({"message": "hello"}))

    assert "disabled" in result["content"][0]["text"].lower()
    assert len(ch.messages) == 0
    set_in_fork(False)
    set_bg_fork_config(BgForkConfig())


def test_embed_blocked_when_allow_ping_false(data_dir):
    ch = InMemoryChannel()
    init_channel(ch)
    set_in_fork(True)
    set_bg_fork_config(BgForkConfig(allow_ping=False))

    result = _run(_embed({"title": "Tasks"}))

    assert "disabled" in result["content"][0]["text"].lower()
    assert len(ch.messages) == 0
    set_in_fork(False)
    set_bg_fork_config(BgForkConfig())


def test_ping_user_critical_still_blocked_when_allow_ping_false(data_dir):
    ch = InMemoryChannel()
    init_channel(ch)
    set_in_fork(True)
    set_bg_fork_config(BgForkConfig(allow_ping=False))

    result = _run(_ping({"message": "urgent!", "critical": True}))

    assert "disabled" in result["content"][0]["text"].lower()
    assert len(ch.messages) == 0
    set_in_fork(False)
    set_bg_fork_config(BgForkConfig())


# --- report_updates blocked mode ---


def test_report_updates_blocked_when_update_blocked(data_dir):
    set_in_fork(True)
    set_bg_fork_config(BgForkConfig(update_main_session="blocked"))

    result = _run(_report({"message": "summary"}))

    assert "disabled" in result["content"][0]["text"].lower()
    set_in_fork(False)
    set_bg_fork_config(BgForkConfig())


# --- stop hook update_main_session modes ---


def test_stop_hook_blocks_on_always_without_report():
    from ollim_bot.agent_tools import require_report_hook

    set_in_fork(True)
    init_bg_tracking()
    set_bg_fork_config(BgForkConfig(update_main_session="always"))

    result = _run(require_report_hook(_STOP_INPUT, None, _STOP_CTX))

    assert "report_updates" in result.get("systemMessage", "")
    set_in_fork(False)
    set_bg_fork_config(BgForkConfig())


def test_stop_hook_allows_on_always_with_report():
    from ollim_bot.agent_tools import require_report_hook
    from ollim_bot.fork_state import get_bg_tracking

    set_in_fork(True)
    init_bg_tracking()
    t = get_bg_tracking()
    assert t is not None
    t.reported = True
    set_bg_fork_config(BgForkConfig(update_main_session="always"))

    result = _run(require_report_hook(_STOP_INPUT, None, _STOP_CTX))

    assert result == {}
    set_in_fork(False)
    set_bg_fork_config(BgForkConfig())


def test_stop_hook_allows_on_freely_with_unreported_output(data_dir):
    from ollim_bot.agent_tools import require_report_hook

    ch = InMemoryChannel()
    init_channel(ch)
    set_in_fork(True)
    init_bg_tracking()
    set_bg_fork_config(BgForkConfig(update_main_session="freely"))

    async def _check():
        await _ping({"message": "test"})
        return await require_report_hook(_STOP_INPUT, None, _STOP_CTX)

    result = _run(_check())

    assert result == {}
    set_in_fork(False)
    set_bg_fork_config(BgForkConfig())


def test_stop_hook_allows_on_blocked():
    from ollim_bot.agent_tools import require_report_hook

    set_in_fork(True)
    init_bg_tracking()
    set_bg_fork_config(BgForkConfig(update_main_session="blocked"))

    result = _run(require_report_hook(_STOP_INPUT, None, _STOP_CTX))

    assert result == {}
    set_in_fork(False)
    set_bg_fork_config(BgForkConfig())


# --- 1-ping-per-session enforcement ---


def test_second_ping_user_blocked_in_bg_fork(data_dir):
    ch = InMemoryChannel()
    init_channel(ch)
    set_in_fork(True)
    init_bg_tracking()

    async def _check():
        first = await _ping({"message": "first"})
        second = await _ping({"message": "second"})
        return first, second

    first, second = _run(_check())

    assert first["content"][0]["text"] == "Message sent."
    assert "Already sent 1 ping" in second["content"][0]["text"]
    assert len(ch.messages) == 1
    set_in_fork(False)


def test_second_embed_blocked_in_bg_fork(data_dir):
    ch = InMemoryChannel()
    init_channel(ch)
    set_in_fork(True)
    init_bg_tracking()

    async def _check():
        first = await _embed({"title": "First"})
        second = await _embed({"title": "Second"})
        return first, second

    first, second = _run(_check())

    assert first["content"][0]["text"] == "Embed sent."
    assert "Already sent 1 ping" in second["content"][0]["text"]
    assert len(ch.messages) == 1
    set_in_fork(False)


def test_critical_bypasses_ping_limit_in_bg_fork(data_dir):
    ch = InMemoryChannel()
    init_channel(ch)
    set_in_fork(True)
    init_bg_tracking()

    async def _check():
        first = await _ping({"message": "first"})
        second = await _ping({"message": "critical", "critical": True})
        return first, second

    first, second = _run(_check())

    assert first["content"][0]["text"] == "Message sent."
    assert second["content"][0]["text"] == "Message sent."
    assert len(ch.messages) == 2
    set_in_fork(False)


def test_ping_limit_not_checked_on_main_or_interactive_fork(data_dir):
    """Counter not initialized outside bg forks, so limit never triggers."""
    ch = InMemoryChannel()
    init_channel(None)
    init_channel(ch)
    set_in_fork(False)
    set_interactive_fork(False)

    async def _check():
        first = await _embed({"title": "First"})
        second = await _embed({"title": "Second"})
        return first, second

    first, second = _run(_check())

    assert first["content"][0]["text"] == "Embed sent."
    assert second["content"][0]["text"] == "Embed sent."
    assert len(ch.messages) == 2
    init_channel(None)
