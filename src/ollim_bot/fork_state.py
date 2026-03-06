"""Fork state: enums, dataclasses, contextvars, and accessor functions.

Pure state management — no I/O, no async execution. Separated from forks.py
so that consumers needing only fork state (permissions, streamer, embeds, etc.)
don't depend on the heavier fork execution module.
"""

from __future__ import annotations

import time
from contextvars import ContextVar
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any


class ForkExitAction(Enum):
    NONE = "none"
    SAVE = "save"
    REPORT = "report"
    EXIT = "exit"


# ---------------------------------------------------------------------------
# Background fork state — contextvar so bg forks don't need agent lock
# ---------------------------------------------------------------------------

_in_fork_var: ContextVar[bool] = ContextVar("_in_fork", default=False)
_busy_var: ContextVar[bool] = ContextVar("_busy", default=False)


def set_in_fork(active: bool) -> None:
    _in_fork_var.set(active)


def in_bg_fork() -> bool:
    return _in_fork_var.get()


def set_busy(busy: bool) -> None:
    _busy_var.set(busy)


def is_busy() -> bool:
    return _busy_var.get()


# ---------------------------------------------------------------------------
# Bg fork tracking — single mutable container so mutations propagate across
# sibling tasks in the SDK's anyio task group (ContextVar with immutable
# values does NOT propagate between start_soon tasks).
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class BgForkTracking:
    """Mutable state shared across anyio task group siblings in a bg fork."""

    output_sent: bool = False
    reported: bool = False
    ping_count: int = 0


_bg_tracking: ContextVar[BgForkTracking | None] = ContextVar("_bg_tracking", default=None)


def init_bg_tracking() -> None:
    """Call before client connect() so all child tasks share the mutable ref."""
    _bg_tracking.set(BgForkTracking())


def get_bg_tracking() -> BgForkTracking | None:
    return _bg_tracking.get()


# ---------------------------------------------------------------------------
# Bg fork config — controls ping and reporting behavior per routine/reminder
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BgForkConfig:
    update_main_session: str = "on_ping"  # always | on_ping | freely | blocked
    allow_ping: bool = True
    allowed_tools: list[str] | None = None

    @classmethod
    def from_item(cls, item: Any) -> BgForkConfig:
        """Build from a Routine, Reminder, or WebhookSpec.

        MINIMAL_BG_TOOLS are always present — they form the communication channel
        back to the user. User-declared tools are merged in after them. Duplicates
        are dropped so declaring a system tool explicitly has no effect.
        """
        from ollim_bot.tool_policy import MINIMAL_BG_TOOLS

        base = list(MINIMAL_BG_TOOLS)
        declared = item.allowed_tools
        allowed = base if declared is None else base + [t for t in declared if t not in base]
        return cls(
            update_main_session=item.update_main_session,
            allow_ping=item.allow_ping,
            allowed_tools=allowed,
        )


# ---------------------------------------------------------------------------
# BgForkConfig restriction helpers — applied in scheduler and webhook dispatch
# ---------------------------------------------------------------------------

_PING_TOOLS = ["mcp__discord__ping_user", "mcp__discord__discord_embed"]
_REPORTING_TOOLS = ["mcp__discord__report_updates", "mcp__discord__follow_up_chain"]


def apply_ping_restrictions(config: BgForkConfig) -> BgForkConfig:
    """Strip ping/embed tools from SDK when allow_ping is false."""
    if config.allow_ping:
        return config
    filtered = [t for t in (config.allowed_tools or []) if t not in _PING_TOOLS]
    return replace(config, allowed_tools=filtered)


def apply_reporting_restrictions(config: BgForkConfig) -> BgForkConfig:
    """Strip report_updates/follow_up_chain from SDK when update_main_session is blocked.

    Upgrades from a runtime-only check to a proper SDK-level permission gate,
    consistent with apply_ping_restrictions(). The runtime check in report_updates
    is retained as defense-in-depth.
    """
    if config.update_main_session != "blocked":
        return config
    filtered = [t for t in (config.allowed_tools or []) if t not in _REPORTING_TOOLS]
    return replace(config, allowed_tools=filtered)


_bg_fork_config_var: ContextVar[BgForkConfig] = ContextVar(
    "_bg_fork_config",
    default=BgForkConfig(),  # noqa: B039 — frozen dataclass, immutable
)


def set_bg_fork_config(config: BgForkConfig) -> None:
    _bg_fork_config_var.set(config)


def get_bg_fork_config() -> BgForkConfig:
    return _bg_fork_config_var.get()


# ---------------------------------------------------------------------------
# Interactive fork state
# ---------------------------------------------------------------------------

_in_interactive_fork: bool = False
_fork_exit_action: ForkExitAction = ForkExitAction.NONE
_enter_fork_requested: bool = False
_enter_fork_topic: str | None = None
_enter_fork_timeout: int = 10
_fork_idle_timeout: int = 10
_fork_last_activity: float = 0.0
_fork_prompted_at: float | None = None


def in_interactive_fork() -> bool:
    return _in_interactive_fork


def set_interactive_fork(active: bool, *, idle_timeout: int | None = None) -> None:
    """Enter or exit interactive fork mode."""
    from ollim_bot import runtime_config

    global _in_interactive_fork, _fork_exit_action, _fork_idle_timeout, _fork_prompted_at
    _in_interactive_fork = active
    _fork_idle_timeout = idle_timeout if idle_timeout is not None else runtime_config.load().fork_idle_timeout
    _fork_exit_action = ForkExitAction.NONE
    _fork_prompted_at = None


def set_exit_action(action: ForkExitAction) -> None:
    global _fork_exit_action
    _fork_exit_action = action


def pop_exit_action() -> ForkExitAction:
    global _fork_exit_action
    action = _fork_exit_action
    _fork_exit_action = ForkExitAction.NONE
    return action


def enter_fork_requested() -> bool:
    return _enter_fork_requested


def request_enter_fork(topic: str | None, *, idle_timeout: int) -> None:
    global _enter_fork_requested, _enter_fork_topic, _enter_fork_timeout
    _enter_fork_requested = True
    _enter_fork_topic = topic
    _enter_fork_timeout = idle_timeout


def pop_enter_fork() -> tuple[str | None, int]:
    """Read and clear the enter-fork request. Returns (topic, idle_timeout)."""
    from ollim_bot import runtime_config

    cfg_timeout = runtime_config.load().fork_idle_timeout
    global _enter_fork_requested, _enter_fork_topic, _enter_fork_timeout
    if not _enter_fork_requested:
        return None, cfg_timeout
    topic = _enter_fork_topic
    timeout = _enter_fork_timeout
    _enter_fork_requested = False
    _enter_fork_topic = None
    _enter_fork_timeout = cfg_timeout
    return topic, timeout


def idle_timeout() -> int:
    return _fork_idle_timeout


def touch_activity() -> None:
    global _fork_last_activity
    _fork_last_activity = time.monotonic()


def is_idle() -> bool:
    """True if interactive fork has been idle longer than idle_timeout."""
    if not _in_interactive_fork:
        return False
    return time.monotonic() - _fork_last_activity > _fork_idle_timeout * 60


def prompted_at() -> float | None:
    return _fork_prompted_at


def set_prompted_at() -> None:
    global _fork_prompted_at
    _fork_prompted_at = time.monotonic()


def clear_prompted() -> None:
    global _fork_prompted_at
    _fork_prompted_at = None


def should_auto_exit() -> bool:
    """True if timeout prompt was sent and idle_timeout has passed since."""
    if _fork_prompted_at is None:
        return False
    return time.monotonic() - _fork_prompted_at > _fork_idle_timeout * 60
