"""Tests for fork_state.py — pure state management with enums, dataclasses, contextvars."""

from types import SimpleNamespace

import pytest

import ollim_bot.fork_state as fs
from ollim_bot.fork_state import (
    BgForkConfig,
    BgForkTracking,
    ForkExitAction,
    bump_fork_turn,
    bump_main_generation,
    bump_updates_generation,
    clear_prompted,
    enter_fork_requested,
    get_bg_fork_config,
    get_bg_tracking,
    has_new_updates_since_fork,
    idle_timeout,
    in_bg_fork,
    in_interactive_fork,
    init_bg_tracking,
    is_busy,
    is_first_fork_turn,
    is_fork_stale,
    is_idle,
    main_generation,
    pop_enter_fork,
    pop_exit_action,
    prompted_at,
    request_enter_fork,
    set_bg_fork_config,
    set_busy,
    set_exit_action,
    set_in_fork,
    set_interactive_fork,
    set_prompted_at,
    should_auto_exit,
    touch_activity,
)


class _MutableClock:
    """Fake time module with a mutable monotonic clock."""

    def __init__(self, now: float):
        self.now = now

    def monotonic(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def _reset_enter_fork_globals():
    """Reset enter-fork request globals that conftest doesn't cover."""
    fs._enter_fork_requested = False
    fs._enter_fork_topic = None
    fs._enter_fork_timeout = 10


@pytest.fixture()
def _fake_runtime_config(monkeypatch):
    """Monkeypatch runtime_config.load() to return a fake config."""
    import ollim_bot.runtime_config as rc_mod

    fake_cfg = SimpleNamespace(fork_idle_timeout=10)
    monkeypatch.setattr(rc_mod, "load", lambda: fake_cfg)
    return fake_cfg


# --- ForkExitAction enum ---


def test_fork_exit_action_values():
    assert ForkExitAction.NONE.value == "none"
    assert ForkExitAction.SAVE.value == "save"
    assert ForkExitAction.REPORT.value == "report"
    assert ForkExitAction.EXIT.value == "exit"


def test_fork_exit_action_has_exactly_four_members():
    assert len(ForkExitAction) == 4


# --- set_in_fork / in_bg_fork ---


def test_in_bg_fork_default_false():
    assert in_bg_fork() is False


def test_set_in_fork_round_trip():
    set_in_fork(True)
    assert in_bg_fork() is True
    set_in_fork(False)
    assert in_bg_fork() is False


# --- set_busy / is_busy ---


def test_is_busy_default_false():
    assert is_busy() is False


def test_set_busy_round_trip():
    set_busy(True)
    assert is_busy() is True
    set_busy(False)
    assert is_busy() is False


# --- BgForkTracking ---


def test_bg_fork_tracking_defaults():
    t = BgForkTracking()
    assert t.output_sent is False
    assert t.reported is False
    assert t.ping_count == 0


def test_bg_fork_tracking_mutation_propagates():
    t = BgForkTracking()
    ref = t
    t.output_sent = True
    t.ping_count = 3
    assert ref.output_sent is True
    assert ref.ping_count == 3


# --- init_bg_tracking / get_bg_tracking ---


def test_get_bg_tracking_default_none():
    assert get_bg_tracking() is None


def test_init_bg_tracking_creates_instance():
    init_bg_tracking()
    tracking = get_bg_tracking()
    assert isinstance(tracking, BgForkTracking)
    assert tracking.output_sent is False


# --- BgForkConfig.from_item ---


def test_bg_fork_config_from_item_no_declared_tools(monkeypatch):
    import ollim_bot.tool_policy as tp

    monkeypatch.setattr(tp, "build_bg_tools", lambda: ["Read", "Glob", "Grep"])
    monkeypatch.setattr(tp, "GATED_TOOLS", {"ping_user"})

    item = SimpleNamespace(
        update_main_session="on_ping",
        allow_ping=True,
        allowed_tools=None,
    )
    cfg = BgForkConfig.from_item(item)
    assert cfg.update_main_session == "on_ping"
    assert cfg.allow_ping is True
    assert cfg.allowed_tools == ["Read", "Glob", "Grep"]


def test_bg_fork_config_from_item_merges_declared_tools(monkeypatch):
    import ollim_bot.tool_policy as tp

    monkeypatch.setattr(tp, "build_bg_tools", lambda: ["Read", "Glob"])
    monkeypatch.setattr(tp, "GATED_TOOLS", set())

    item = SimpleNamespace(
        update_main_session="always",
        allow_ping=False,
        allowed_tools=["Write", "Edit"],
    )
    cfg = BgForkConfig.from_item(item)
    assert cfg.allowed_tools == ["Read", "Glob", "Write", "Edit"]


def test_bg_fork_config_from_item_strips_gated_tools(monkeypatch):
    import ollim_bot.tool_policy as tp

    monkeypatch.setattr(tp, "build_bg_tools", lambda: ["Read", "ping_user"])
    monkeypatch.setattr(tp, "GATED_TOOLS", {"ping_user", "report_updates"})

    item = SimpleNamespace(
        update_main_session="on_ping",
        allow_ping=True,
        allowed_tools=["report_updates"],
    )
    cfg = BgForkConfig.from_item(item)
    assert cfg.allowed_tools is not None
    assert "ping_user" not in cfg.allowed_tools
    assert "report_updates" not in cfg.allowed_tools
    assert cfg.allowed_tools == ["Read"]


def test_bg_fork_config_from_item_drops_duplicates(monkeypatch):
    import ollim_bot.tool_policy as tp

    monkeypatch.setattr(tp, "build_bg_tools", lambda: ["Read", "Glob"])
    monkeypatch.setattr(tp, "GATED_TOOLS", set())

    item = SimpleNamespace(
        update_main_session="on_ping",
        allow_ping=True,
        allowed_tools=["Glob", "Read", "Write"],
    )
    cfg = BgForkConfig.from_item(item)
    # Duplicates of base tools should be dropped; only Write is new
    assert cfg.allowed_tools == ["Read", "Glob", "Write"]


# --- set_bg_fork_config / get_bg_fork_config ---


def test_bg_fork_config_default():
    cfg = get_bg_fork_config()
    assert cfg.update_main_session == "on_ping"
    assert cfg.allow_ping is True
    assert cfg.allowed_tools is None


def test_set_bg_fork_config_round_trip():
    custom = BgForkConfig(update_main_session="always", allow_ping=False, allowed_tools=["Read"])
    set_bg_fork_config(custom)
    assert get_bg_fork_config() is custom


# --- Generation counters ---


def test_main_generation_starts_at_zero():
    assert main_generation() == 0


def test_bump_main_generation_increments():
    bump_main_generation()
    assert main_generation() == 1
    bump_main_generation()
    assert main_generation() == 2


def test_bump_updates_generation():
    bump_updates_generation()
    assert fs._updates_generation == 1


# --- set_interactive_fork ---


def test_set_interactive_fork_true_snapshots_generations(_fake_runtime_config):
    bump_main_generation()
    bump_main_generation()
    bump_updates_generation()

    set_interactive_fork(True)

    assert in_interactive_fork() is True
    assert fs._fork_ctx is not None
    assert fs._fork_ctx.main_gen_snapshot == 2
    assert fs._fork_ctx.updates_gen_snapshot == 1
    assert fs._fork_ctx.idle_timeout == 10


def test_set_interactive_fork_true_with_explicit_timeout(_fake_runtime_config):
    set_interactive_fork(True, idle_timeout=5)
    assert fs._fork_ctx is not None
    assert fs._fork_ctx.idle_timeout == 5


def test_set_interactive_fork_false_clears_context(_fake_runtime_config):
    set_interactive_fork(True)
    assert in_interactive_fork() is True
    set_interactive_fork(False)
    assert in_interactive_fork() is False
    assert fs._fork_ctx is None


# --- is_fork_stale ---


def test_is_fork_stale_no_fork():
    assert is_fork_stale() is False


def test_is_fork_stale_same_generation(_fake_runtime_config):
    set_interactive_fork(True)
    assert is_fork_stale() is False


def test_is_fork_stale_after_main_bump(_fake_runtime_config):
    set_interactive_fork(True)
    bump_main_generation()
    assert is_fork_stale() is True


# --- has_new_updates_since_fork ---


def test_has_new_updates_no_fork():
    assert has_new_updates_since_fork() is False


def test_has_new_updates_same_generation(_fake_runtime_config):
    set_interactive_fork(True)
    assert has_new_updates_since_fork() is False


def test_has_new_updates_after_bump(_fake_runtime_config):
    set_interactive_fork(True)
    bump_updates_generation()
    assert has_new_updates_since_fork() is True


# --- in_interactive_fork ---


def test_in_interactive_fork_default_false():
    assert in_interactive_fork() is False


# --- set_exit_action / pop_exit_action ---


def test_set_exit_action_and_pop(_fake_runtime_config):
    set_interactive_fork(True)
    set_exit_action(ForkExitAction.SAVE)
    result = pop_exit_action()
    assert result is ForkExitAction.SAVE


def test_pop_exit_action_resets_to_none(_fake_runtime_config):
    set_interactive_fork(True)
    set_exit_action(ForkExitAction.REPORT)
    pop_exit_action()
    assert pop_exit_action() is ForkExitAction.NONE


def test_set_exit_action_without_fork_raises():
    with pytest.raises(AssertionError):
        set_exit_action(ForkExitAction.SAVE)


def test_pop_exit_action_without_fork_raises():
    with pytest.raises(AssertionError):
        pop_exit_action()


# --- bump_fork_turn / is_first_fork_turn ---


def test_is_first_fork_turn_initially_true(_fake_runtime_config):
    set_interactive_fork(True)
    assert is_first_fork_turn() is True


def test_bump_fork_turn_makes_not_first(_fake_runtime_config):
    set_interactive_fork(True)
    bump_fork_turn()
    assert is_first_fork_turn() is False


def test_bump_fork_turn_without_fork_raises():
    with pytest.raises(AssertionError):
        bump_fork_turn()


def test_is_first_fork_turn_without_fork_raises():
    with pytest.raises(AssertionError):
        is_first_fork_turn()


# --- request_enter_fork / enter_fork_requested / pop_enter_fork ---


def test_enter_fork_requested_default_false():
    assert enter_fork_requested() is False


def test_request_enter_fork_round_trip(_fake_runtime_config):
    request_enter_fork("my topic", idle_timeout=15)
    assert enter_fork_requested() is True

    topic, timeout = pop_enter_fork()
    assert topic == "my topic"
    assert timeout == 15


def test_pop_enter_fork_clears_request(_fake_runtime_config):
    request_enter_fork("topic", idle_timeout=20)
    pop_enter_fork()
    assert enter_fork_requested() is False


def test_pop_enter_fork_when_not_requested(_fake_runtime_config):
    topic, timeout = pop_enter_fork()
    assert topic is None
    assert timeout == 10  # from fake config fork_idle_timeout


# --- idle_timeout ---


def test_idle_timeout_returns_configured_value(_fake_runtime_config):
    set_interactive_fork(True, idle_timeout=7)
    assert idle_timeout() == 7


def test_idle_timeout_without_fork_raises():
    with pytest.raises(AssertionError):
        idle_timeout()


# --- touch_activity / is_idle ---


def test_is_idle_no_fork_returns_false():
    assert is_idle() is False


def test_is_idle_fresh_fork_not_idle(monkeypatch, _fake_runtime_config):
    clock = _MutableClock(1000.0)
    monkeypatch.setattr(fs, "time", clock)
    set_interactive_fork(True, idle_timeout=5)
    # Pin last_activity to our clock (default_factory captures real time.monotonic)
    assert fs._fork_ctx is not None
    fs._fork_ctx.last_activity = 1000.0
    assert is_idle() is False


def test_is_idle_after_timeout(monkeypatch, _fake_runtime_config):
    clock = _MutableClock(1000.0)
    monkeypatch.setattr(fs, "time", clock)
    set_interactive_fork(True, idle_timeout=1)  # 1 minute
    assert fs._fork_ctx is not None
    fs._fork_ctx.last_activity = 1000.0

    # Advance past 1 minute
    clock.now = 1061.0
    assert is_idle() is True


def test_touch_activity_resets_idle(monkeypatch, _fake_runtime_config):
    clock = _MutableClock(1000.0)
    monkeypatch.setattr(fs, "time", clock)
    set_interactive_fork(True, idle_timeout=1)
    assert fs._fork_ctx is not None
    fs._fork_ctx.last_activity = 1000.0

    # Advance past timeout
    clock.now = 1061.0
    assert is_idle() is True

    # Touch resets the clock (uses patched fs.time.monotonic → 1061.0)
    touch_activity()
    assert is_idle() is False


def test_touch_activity_without_fork_raises():
    with pytest.raises(AssertionError):
        touch_activity()


# --- set_prompted_at / prompted_at / clear_prompted ---


def test_prompted_at_no_fork_returns_none():
    assert prompted_at() is None


def test_set_prompted_at_stores_value(monkeypatch, _fake_runtime_config):
    now = 5000.0
    monkeypatch.setattr(fs, "time", _MutableClock(now))
    set_interactive_fork(True)

    set_prompted_at()
    assert prompted_at() == 5000.0


def test_clear_prompted_resets_to_none(_fake_runtime_config):
    set_interactive_fork(True)
    set_prompted_at()
    assert prompted_at() is not None
    clear_prompted()
    assert prompted_at() is None


def test_set_prompted_at_without_fork_raises():
    with pytest.raises(AssertionError):
        set_prompted_at()


def test_clear_prompted_without_fork_raises():
    with pytest.raises(AssertionError):
        clear_prompted()


# --- should_auto_exit ---


def test_should_auto_exit_no_fork():
    assert should_auto_exit() is False


def test_should_auto_exit_no_prompt(_fake_runtime_config):
    set_interactive_fork(True)
    assert should_auto_exit() is False


def test_should_auto_exit_prompt_not_expired(monkeypatch, _fake_runtime_config):
    clock = _MutableClock(1000.0)
    monkeypatch.setattr(fs, "time", clock)
    set_interactive_fork(True, idle_timeout=5)

    set_prompted_at()
    # Only 1 second later — well within 5 minutes
    clock.now = 1001.0
    assert should_auto_exit() is False


def test_should_auto_exit_prompt_expired(monkeypatch, _fake_runtime_config):
    clock = _MutableClock(1000.0)
    monkeypatch.setattr(fs, "time", clock)
    set_interactive_fork(True, idle_timeout=1)  # 1 minute

    set_prompted_at()
    # Advance past idle_timeout (1 min = 60s)
    clock.now = 1061.0
    assert should_auto_exit() is True
