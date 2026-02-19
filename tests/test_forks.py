"""Tests for forks.py — fork state, pending updates, interactive fork lifecycle."""

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
    pop_fork_saved,
    pop_pending_updates,
    prompted_at,
    request_enter_fork,
    set_exit_action,
    set_in_fork,
    set_interactive_fork,
    set_prompted_at,
    should_auto_exit,
    touch_activity,
)

# --- Background fork state (migrated from test_discord_tools.py) ---


def test_bg_fork_saved_default():
    set_in_fork(True)

    assert pop_fork_saved() is False

    set_in_fork(False)


def test_set_in_fork_resets_saved():
    set_in_fork(True)
    # Simulate save_context setting the flag via the internal global
    import ollim_bot.forks as forks_mod

    forks_mod._fork_saved = True
    set_in_fork(True)  # re-entering resets

    assert pop_fork_saved() is False

    set_in_fork(False)


def test_pop_fork_saved_clears():
    import ollim_bot.forks as forks_mod

    set_in_fork(True)
    forks_mod._fork_saved = True
    pop_fork_saved()

    assert pop_fork_saved() is False

    set_in_fork(False)


# --- Pending updates ---


def test_peek_reads_without_clearing():
    pop_pending_updates()
    from ollim_bot.forks import _append_update

    _append_update("peeked")

    first = peek_pending_updates()
    second = peek_pending_updates()

    assert first == ["peeked"]
    assert second == ["peeked"]
    pop_pending_updates()


def test_pop_clears_updates():
    pop_pending_updates()
    from ollim_bot.forks import _append_update

    _append_update("cleared")
    pop_pending_updates()

    assert pop_pending_updates() == []


def test_multiple_updates_accumulate():
    pop_pending_updates()
    from ollim_bot.forks import _append_update

    _append_update("first")
    _append_update("second")

    assert pop_pending_updates() == ["first", "second"]


def test_clear_is_idempotent():
    pop_pending_updates()

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
