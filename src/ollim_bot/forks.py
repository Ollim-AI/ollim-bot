"""Fork state management, pending updates I/O, and background fork execution."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, NamedTuple

from ollim_bot.channel import get_channel
from ollim_bot.config import TZ
from ollim_bot.storage import STATE_DIR, atomic_write

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    import discord
    from claude_agent_sdk import ClaudeSDKClient

    from ollim_bot.agent import Agent


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
    disallowed_tools: list[str] | None = None

    def __post_init__(self) -> None:
        if self.allowed_tools is not None and self.disallowed_tools is not None:
            raise ValueError("Cannot specify both allowed_tools and disallowed_tools")

    @classmethod
    def from_item(cls, item: Any) -> BgForkConfig:
        """Build from a Routine, Reminder, or WebhookSpec."""
        return cls(
            update_main_session=item.update_main_session,
            allow_ping=item.allow_ping,
            allowed_tools=getattr(item, "allowed_tools", None),
            disallowed_tools=getattr(item, "disallowed_tools", None),
        )


_bg_fork_config_var: ContextVar[BgForkConfig] = ContextVar(
    "_bg_fork_config",
    default=BgForkConfig(),  # noqa: B039 — frozen dataclass, immutable
)


def set_bg_fork_config(config: BgForkConfig) -> None:
    _bg_fork_config_var.set(config)


def get_bg_fork_config() -> BgForkConfig:
    return _bg_fork_config_var.get()


# ---------------------------------------------------------------------------
# Pending updates (fork → main session bridge)
# ---------------------------------------------------------------------------

_UPDATES_FILE = STATE_DIR / "pending_updates.json"
_TZ = TZ
_updates_lock = asyncio.Lock()


class PendingUpdate(NamedTuple):
    ts: str
    message: str


async def append_update(message: str) -> None:
    """Append a timestamped update to the pending updates file.

    Lock protects the read-modify-write cycle so concurrent bg forks
    don't lose each other's updates.
    """
    async with _updates_lock:
        updates = json.loads(_UPDATES_FILE.read_text()) if _UPDATES_FILE.exists() else []
        updates.append({"ts": datetime.now(_TZ).isoformat(), "message": message})
        atomic_write(_UPDATES_FILE, json.dumps(updates).encode())
        log.info("pending update appended (now %d): %.80s", len(updates), message)


def peek_pending_updates() -> list[PendingUpdate]:
    """Read pending updates without clearing."""
    if not _UPDATES_FILE.exists():
        return []
    updates = json.loads(_UPDATES_FILE.read_text())
    return [PendingUpdate(ts=u["ts"], message=u["message"]) for u in updates]


async def clear_pending_updates() -> None:
    """Delete the pending updates file if it exists.

    Lock ensures atomicity with concurrent append_update calls —
    without it a bg fork's in-progress append can restore cleared data.
    """
    async with _updates_lock:
        if _UPDATES_FILE.exists():
            _UPDATES_FILE.unlink()


async def pop_pending_updates() -> list[PendingUpdate]:
    """Read and clear all pending updates.

    Lock ensures atomicity with concurrent append_update calls —
    without it a bg fork's append can re-introduce already-popped updates.
    """
    async with _updates_lock:
        if not _UPDATES_FILE.exists():
            log.debug("pop_pending_updates: file does not exist")
            return []
        updates = json.loads(_UPDATES_FILE.read_text())
        _UPDATES_FILE.unlink()
        log.info("popped %d pending update(s)", len(updates))
        return [PendingUpdate(ts=u["ts"], message=u["message"]) for u in updates]


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


# ---------------------------------------------------------------------------
# Background fork execution
# ---------------------------------------------------------------------------


def _extract_prompt_tag(prompt: str) -> str:
    """Extract the job tag from a bg fork prompt (e.g. '[routine-bg:morning-checkin]')."""
    if prompt.startswith("["):
        return prompt.split("]", 1)[0] + "]"
    return "bg fork"


async def _notify_fork_failure(
    channel: discord.abc.Messageable, tag: str, *, timed_out: bool = False, timeout_seconds: int = 0
) -> None:
    """Best-effort DM notification when a bg fork fails or times out."""
    if timed_out:
        msg = f"Background task timed out after {timeout_seconds // 60} minutes: `{tag}`"
    else:
        msg = f"Background task failed: `{tag}` -- check logs for details."
    with contextlib.suppress(Exception):
        await channel.send(msg)


async def run_agent_background(
    agent: Agent,
    prompt: str,
    *,
    model: str | None = None,
    thinking: bool = True,
    isolated: bool = False,
    bg_config: BgForkConfig | None = None,
) -> None:
    """Run agent on a disposable forked session — no lock needed.

    Contextvars scope in_fork state to this task, so bg forks run
    concurrently without stomping on main session or other forks.
    """
    from ollim_bot import runtime_config
    from ollim_bot.sessions import (
        cancel_message_collector,
        flush_message_collector,
        load_session_id,
        log_session_event,
        start_message_collector,
    )

    tag = _extract_prompt_tag(prompt)
    bg_timeout = runtime_config.load().bg_fork_timeout
    busy = agent.lock().locked()
    if busy:
        log.info("bg fork running in quiet mode (user busy): %s", tag)

    log.info("bg fork started: %s", tag)

    dm = get_channel()
    main_session_id = load_session_id()
    # CRITICAL: set_in_fork(True) and set_busy() must precede
    # create_forked_client() so the contextvars propagate through the SDK's
    # task-group spawn chain to reach the can_use_tool callback.
    set_in_fork(True)
    set_busy(busy)
    init_bg_tracking()
    if bg_config:
        set_bg_fork_config(bg_config)
    start_message_collector()

    try:
        async with asyncio.timeout(bg_timeout):
            allowed = bg_config.allowed_tools if bg_config else None
            blocked = bg_config.disallowed_tools if bg_config else None
            client: ClaudeSDKClient | None = None
            backoffs = (5, 15)
            for attempt in range(1 + len(backoffs)):
                try:
                    if isolated:
                        client = await agent.create_isolated_client(
                            model=model,
                            thinking=thinking,
                            allowed_tools=allowed,
                            disallowed_tools=blocked,
                        )
                    else:
                        client = await agent.create_forked_client(
                            thinking=thinking,
                            allowed_tools=allowed,
                            disallowed_tools=blocked,
                        )
                    break
                except Exception as exc:
                    if "Control request timeout" not in str(exc):
                        raise
                    if attempt < len(backoffs):
                        delay = backoffs[attempt]
                        log.warning(
                            "bg fork init timeout (attempt %d/%d), retrying in %ds: %s",
                            attempt + 1,
                            1 + len(backoffs),
                            delay,
                            tag,
                        )
                        await asyncio.sleep(delay)
                    else:
                        raise
            assert client is not None
            try:
                fork_session_id = await agent.run_on_client(client, prompt, prepend_updates=not isolated)
                log_session_event(
                    fork_session_id,
                    "isolated_bg" if isolated else "bg_fork",
                    parent_session_id=None if isolated else main_session_id,
                )
                flush_message_collector(
                    fork_session_id,
                    None if isolated else main_session_id,
                )
            finally:
                await client.disconnect()
        log.info("bg fork completed: %s", tag)
    except TimeoutError:
        log.warning("bg fork timed out after %ds: %s", bg_timeout, tag)
        await _notify_fork_failure(dm, tag, timed_out=True, timeout_seconds=bg_timeout)
    except Exception:
        log.exception("bg fork failed: %s", tag)
        await _notify_fork_failure(dm, tag)
        raise
    finally:
        set_in_fork(False)
        set_busy(False)
        cancel_message_collector()


async def send_agent_dm(
    agent: Agent,
    prompt: str,
) -> None:
    """Inject a prompt into the agent session and stream the response as a DM."""
    from ollim_bot.streamer import stream_to_channel

    dm = get_channel()
    async with agent.lock():
        await dm.typing()
        await stream_to_channel(dm, agent.stream_chat(prompt))
