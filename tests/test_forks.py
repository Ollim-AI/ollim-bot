"""Tests for forks.py — fork state, pending updates, interactive fork lifecycle."""

import asyncio
import time

from ollim_bot.forks import (
    ForkExitAction,
    clear_pending_updates,
    idle_timeout,
    in_interactive_fork,
    is_idle,
    peek_pending_updates,
    pop_enter_fork,
    pop_exit_action,
    pop_pending_updates,
    prompted_at,
    request_enter_fork,
    set_exit_action,
    set_interactive_fork,
    set_prompted_at,
    should_auto_exit,
    touch_activity,
)

# --- Pending updates ---


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_peek_reads_without_clearing():
    _run(pop_pending_updates())
    from ollim_bot.forks import append_update

    _run(append_update("peeked"))

    first = peek_pending_updates()
    second = peek_pending_updates()

    assert first == ["peeked"]
    assert second == ["peeked"]
    _run(pop_pending_updates())


def test_pop_clears_updates():
    _run(pop_pending_updates())
    from ollim_bot.forks import append_update

    _run(append_update("cleared"))
    _run(pop_pending_updates())

    assert _run(pop_pending_updates()) == []


def test_multiple_updates_accumulate():
    _run(pop_pending_updates())
    from ollim_bot.forks import append_update

    _run(append_update("first"))
    _run(append_update("second"))

    assert _run(pop_pending_updates()) == ["first", "second"]


def test_clear_is_idempotent():
    _run(pop_pending_updates())

    clear_pending_updates()
    clear_pending_updates()

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
