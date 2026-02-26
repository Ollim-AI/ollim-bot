"""Tests for forks.py — fork state, pending updates, interactive fork lifecycle."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

import ollim_bot.forks as forks_mod
from ollim_bot.forks import (
    BG_FORK_TIMEOUT,
    BgForkConfig,
    ForkExitAction,
    append_update,
    bg_reported,
    clear_pending_updates,
    get_bg_fork_config,
    idle_timeout,
    in_interactive_fork,
    init_bg_reported_flag,
    is_busy,
    is_idle,
    mark_bg_reported,
    peek_pending_updates,
    pop_enter_fork,
    pop_exit_action,
    pop_pending_updates,
    prompted_at,
    request_enter_fork,
    run_agent_background,
    set_bg_fork_config,
    set_busy,
    set_exit_action,
    set_interactive_fork,
    set_prompted_at,
    should_auto_exit,
    touch_activity,
)

# --- Pending updates ---


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_peek_reads_without_clearing(data_dir):
    _run(pop_pending_updates())
    from ollim_bot.forks import append_update

    _run(append_update("peeked"))

    first = peek_pending_updates()
    second = peek_pending_updates()

    assert [u.message for u in first] == ["peeked"]
    assert [u.message for u in second] == ["peeked"]
    _run(pop_pending_updates())


def test_pop_clears_updates(data_dir):
    _run(pop_pending_updates())
    from ollim_bot.forks import append_update

    _run(append_update("cleared"))
    _run(pop_pending_updates())

    assert _run(pop_pending_updates()) == []


def test_multiple_updates_accumulate(data_dir):
    _run(pop_pending_updates())
    from ollim_bot.forks import append_update

    _run(append_update("first"))
    _run(append_update("second"))

    result = _run(pop_pending_updates())
    assert [u.message for u in result] == ["first", "second"]
    assert all(u.ts for u in result)


def test_clear_is_idempotent(data_dir):
    _run(pop_pending_updates())

    _run(clear_pending_updates())
    _run(clear_pending_updates())

    assert peek_pending_updates() == []


# --- Interactive fork state ---


def test_interactive_fork_default():
    assert in_interactive_fork() is False


def test_set_interactive_fork():
    set_interactive_fork(True, idle_timeout=5)

    assert in_interactive_fork() is True

    set_interactive_fork(False)

    assert in_interactive_fork() is False


def test_exit_action_default():
    set_interactive_fork(True, idle_timeout=10)

    assert pop_exit_action() is ForkExitAction.NONE

    set_interactive_fork(False)


def test_set_and_pop_exit_action():
    set_interactive_fork(True, idle_timeout=10)
    set_exit_action(ForkExitAction.SAVE)

    assert pop_exit_action() is ForkExitAction.SAVE
    assert pop_exit_action() is ForkExitAction.NONE

    set_interactive_fork(False)


def test_enter_fork_request_with_topic():
    request_enter_fork("research topic", idle_timeout=15)

    topic, timeout = pop_enter_fork()

    assert topic == "research topic"
    assert timeout == 15


def test_enter_fork_request_second_pop_empty():
    request_enter_fork("topic", idle_timeout=10)
    pop_enter_fork()

    topic, timeout = pop_enter_fork()

    assert topic is None
    assert timeout == 10


def test_enter_fork_no_topic():
    request_enter_fork(None, idle_timeout=10)

    topic, timeout = pop_enter_fork()

    assert topic is None
    assert timeout == 10


def test_idle_timeout_stored():
    set_interactive_fork(True, idle_timeout=15)

    assert idle_timeout() == 15

    set_interactive_fork(False)


# --- Idle detection ---


def test_not_idle_when_recently_active():
    set_interactive_fork(True, idle_timeout=10)
    touch_activity()

    assert is_idle() is False

    set_interactive_fork(False)


def test_idle_after_timeout():
    import ollim_bot.forks as forks_mod

    set_interactive_fork(True, idle_timeout=10)
    forks_mod._fork_last_activity = time.monotonic() - 601

    assert is_idle() is True

    set_interactive_fork(False)


def test_not_idle_when_not_in_fork():
    assert is_idle() is False


# --- Prompted tracking ---


def test_prompted_default_none():
    set_interactive_fork(True, idle_timeout=10)

    assert prompted_at() is None

    set_interactive_fork(False)


def test_set_and_clear_prompted():
    from ollim_bot.forks import clear_prompted

    set_interactive_fork(True, idle_timeout=10)
    set_prompted_at()

    assert prompted_at() is not None

    clear_prompted()

    assert prompted_at() is None

    set_interactive_fork(False)


def test_should_auto_exit_false_when_recently_prompted():
    set_interactive_fork(True, idle_timeout=10)
    set_prompted_at()

    assert should_auto_exit() is False

    set_interactive_fork(False)


def test_should_auto_exit_true_after_timeout():
    import ollim_bot.forks as forks_mod

    set_interactive_fork(True, idle_timeout=10)
    forks_mod._fork_prompted_at = time.monotonic() - 601

    assert should_auto_exit() is True

    set_interactive_fork(False)


def test_should_auto_exit_false_when_not_prompted():
    set_interactive_fork(True, idle_timeout=10)

    assert should_auto_exit() is False

    set_interactive_fork(False)


# --- Background fork timeout ---


def test_bg_fork_timeout_constant():
    assert BG_FORK_TIMEOUT == 1800


def test_bg_fork_timeout_cancels_and_notifies(monkeypatch, data_dir):
    """A bg fork that exceeds the timeout is cancelled and sends a DM alert."""
    sent_messages: list[str] = []

    async def fake_create_dm():
        channel = AsyncMock()
        channel.send = AsyncMock(side_effect=lambda msg, **kw: sent_messages.append(msg))
        return channel

    owner = AsyncMock()
    owner.create_dm = fake_create_dm

    agent = AsyncMock()
    agent.lock = MagicMock(return_value=asyncio.Lock())

    async def hang_forever(*args, **kwargs):
        await asyncio.sleep(3600)

    client = AsyncMock()
    agent.create_forked_client = AsyncMock(return_value=client)
    agent.run_on_client = AsyncMock(side_effect=hang_forever)

    # Shrink timeout to 0.1s so the test runs fast
    monkeypatch.setattr(forks_mod, "BG_FORK_TIMEOUT", 0.1)

    _run(run_agent_background(owner, agent, "[routine-bg:test] do stuff"))

    # Client should have been disconnected
    client.disconnect.assert_awaited()

    # User should have received a timeout notification
    assert len(sent_messages) == 1
    assert "timed out" in sent_messages[0].lower()


# --- Concurrent append_update (reproduction for lost updates bug) ---


def test_concurrent_append_update_via_asyncio_tasks(data_dir):
    """Two concurrent asyncio.create_task(append_update) — both must survive.

    Simulates two bg forks fired by APScheduler at the same time.
    APScheduler's AsyncIOExecutor uses loop.create_task() for coroutine jobs.
    """

    async def _scenario():
        t1 = asyncio.create_task(append_update("fork-A update"))
        t2 = asyncio.create_task(append_update("fork-B update"))
        await asyncio.gather(t1, t2)

        result = await pop_pending_updates()
        messages = [u.message for u in result]
        assert "fork-A update" in messages
        assert "fork-B update" in messages
        assert len(messages) == 2

    _run(_scenario())


def test_concurrent_append_update_via_anyio_task_groups(data_dir):
    """Two concurrent append_update calls inside separate anyio task groups.

    Simulates the SDK execution model: each ClaudeSDKClient has its own
    anyio task group, and MCP tool calls are dispatched via start_soon().
    The module-level asyncio.Lock must provide mutual exclusion across
    tasks from different task groups on the same event loop.
    """
    import anyio

    async def _scenario():
        async def fork_a():
            async with anyio.create_task_group() as tg:
                tg.start_soon(append_update, "tg-A update")

        async def fork_b():
            async with anyio.create_task_group() as tg:
                tg.start_soon(append_update, "tg-B update")

        # Run both task groups concurrently (simulating two bg forks)
        async with anyio.create_task_group() as parent:
            parent.start_soon(fork_a)
            parent.start_soon(fork_b)

        result = await pop_pending_updates()
        messages = [u.message for u in result]
        assert "tg-A update" in messages
        assert "tg-B update" in messages
        assert len(messages) == 2

    _run(_scenario())


def test_concurrent_append_and_pop(data_dir):
    """append_update and pop_pending_updates racing — pop must not lose in-flight data.

    Sequence: append A, then concurrently (append B, pop). The pop should
    return at least A. If the lock works, B either lands before or after pop.
    """

    async def _scenario():
        await append_update("before-race")

        popped = []

        async def do_pop():
            popped.extend(await pop_pending_updates())

        t1 = asyncio.create_task(append_update("during-race"))
        t2 = asyncio.create_task(do_pop())
        await asyncio.gather(t1, t2)

        popped_msgs = [u.message for u in popped]
        # "before-race" MUST appear in either popped or the file
        leftover = await pop_pending_updates()
        leftover_msgs = [u.message for u in leftover]

        all_msgs = popped_msgs + leftover_msgs
        assert "before-race" in all_msgs
        assert "during-race" in all_msgs

    _run(_scenario())


def test_concurrent_append_and_clear(data_dir):
    """append_update and clear_pending_updates racing — no data corruption."""

    async def _scenario():
        await append_update("will-be-cleared")

        t1 = asyncio.create_task(append_update("after-clear"))
        t2 = asyncio.create_task(clear_pending_updates())
        await asyncio.gather(t1, t2)

        # After both complete, either the file has "after-clear" or is empty
        # depending on ordering — but there must be no corruption
        result = await pop_pending_updates()
        messages = [u.message for u in result]
        # Only valid outcomes: empty (clear ran last) or ["after-clear"] (append ran last)
        assert messages == [] or messages == ["after-clear"]

    _run(_scenario())


def test_many_concurrent_appends(data_dir):
    """Stress test: 20 concurrent append_update calls — all must survive."""

    async def _scenario():
        tasks = [asyncio.create_task(append_update(f"update-{i}")) for i in range(20)]
        await asyncio.gather(*tasks)

        result = await pop_pending_updates()
        messages = sorted([u.message for u in result])
        expected = sorted([f"update-{i}" for i in range(20)])
        assert messages == expected

    _run(_scenario())


# --- Busy contextvar ---


def test_busy_contextvar_default_false():
    assert is_busy() is False


def test_busy_contextvar_set_and_read():
    set_busy(True)
    assert is_busy() is True
    set_busy(False)
    assert is_busy() is False


def test_bg_fork_sets_busy_when_lock_held(monkeypatch, data_dir):
    """When agent lock is held, the _busy contextvar is set during fork execution."""
    observed_busy: list[bool] = []

    owner = AsyncMock()
    owner.create_dm = AsyncMock(return_value=AsyncMock())

    agent = AsyncMock()
    lock = asyncio.Lock()
    agent.lock = MagicMock(return_value=lock)

    async def capture_busy(client, prompt, **kwargs):
        observed_busy.append(is_busy())
        return "fork-session-id"

    client = AsyncMock()
    agent.create_forked_client = AsyncMock(return_value=client)
    agent.run_on_client = AsyncMock(side_effect=capture_busy)

    _run(lock.acquire())
    try:
        _run(run_agent_background(owner, agent, "[routine-bg:test] do stuff"))
    finally:
        lock.release()

    assert observed_busy == [True]


def test_bg_fork_not_busy_when_lock_free(monkeypatch, data_dir):
    """When agent lock is free, the _busy contextvar stays False."""
    observed_busy: list[bool] = []

    owner = AsyncMock()
    owner.create_dm = AsyncMock(return_value=AsyncMock())

    agent = AsyncMock()
    agent.lock = MagicMock(return_value=asyncio.Lock())

    async def capture_busy(client, prompt, **kwargs):
        observed_busy.append(is_busy())
        return "fork-session-id"

    client = AsyncMock()
    agent.create_forked_client = AsyncMock(return_value=client)
    agent.run_on_client = AsyncMock(side_effect=capture_busy)

    _run(run_agent_background(owner, agent, "[routine-bg:test] do stuff"))

    assert observed_busy == [False]


# --- BgForkConfig ---


def test_bg_fork_config_defaults():
    config = BgForkConfig()

    assert config.update_main_session == "on_ping"
    assert config.allow_ping is True


def test_bg_fork_config_custom():
    config = BgForkConfig(update_main_session="always", allow_ping=False)

    assert config.update_main_session == "always"
    assert config.allow_ping is False


def test_set_and_get_bg_fork_config():
    config = BgForkConfig(update_main_session="blocked", allow_ping=False)
    set_bg_fork_config(config)

    result = get_bg_fork_config()

    assert result.update_main_session == "blocked"
    assert result.allow_ping is False
    set_bg_fork_config(BgForkConfig())


def test_bg_fork_config_default_when_unset():
    set_bg_fork_config(BgForkConfig())

    result = get_bg_fork_config()

    assert result.update_main_session == "on_ping"
    assert result.allow_ping is True


def test_bg_fork_config_with_allowed_tools():
    config = BgForkConfig(allowed_tools=["Bash(ollim-bot gmail *)"])

    assert config.allowed_tools == ["Bash(ollim-bot gmail *)"]
    assert config.disallowed_tools is None


def test_bg_fork_config_with_disallowed_tools():
    config = BgForkConfig(disallowed_tools=["WebFetch"])

    assert config.disallowed_tools == ["WebFetch"]
    assert config.allowed_tools is None


def test_bg_fork_config_both_tools_raises():
    with pytest.raises(ValueError, match="Cannot specify both"):
        BgForkConfig(
            allowed_tools=["Read(**.md)"],
            disallowed_tools=["WebFetch"],
        )


# --- Reported flag ---


def test_bg_reported_flag_default_false():
    init_bg_reported_flag()

    assert bg_reported() is False


def test_bg_reported_flag_set_true():
    init_bg_reported_flag()
    mark_bg_reported()

    assert bg_reported() is True
