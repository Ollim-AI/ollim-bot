"""Fork state management, pending updates I/O, and background fork execution."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import tempfile
import time
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

BG_FORK_TIMEOUT = 1800  # 30 minutes

if TYPE_CHECKING:
    import discord

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
# Bg output tracking — mutable container so mutations propagate across
# sibling tasks in the SDK's anyio task group (ContextVar with immutable
# bool does NOT propagate between start_soon tasks).
# ---------------------------------------------------------------------------

_bg_output_flag: ContextVar[list[bool] | None] = ContextVar(
    "_bg_output_flag", default=None
)


def init_bg_output_flag() -> None:
    """Call before client connect() so all child tasks share the mutable ref."""
    _bg_output_flag.set([False])


def mark_bg_output(sent: bool) -> None:
    flag = _bg_output_flag.get()
    if flag is not None:
        flag[0] = sent


def bg_output_sent() -> bool:
    flag = _bg_output_flag.get()
    return bool(flag and flag[0])


# ---------------------------------------------------------------------------
# Bg fork config — controls ping and reporting behavior per routine/reminder
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BgForkConfig:
    update_main_session: str = "on_ping"  # always | on_ping | freely | blocked
    allow_ping: bool = True


_bg_fork_config_var: ContextVar[BgForkConfig] = ContextVar(
    "_bg_fork_config", default=BgForkConfig()
)


def set_bg_fork_config(config: BgForkConfig) -> None:
    _bg_fork_config_var.set(config)


def get_bg_fork_config() -> BgForkConfig:
    return _bg_fork_config_var.get()


# ---------------------------------------------------------------------------
# Bg reported flag — tracks whether report_updates was called (for "always" mode).
# Mutable container, same pattern as _bg_output_flag.
# ---------------------------------------------------------------------------

_bg_reported_flag: ContextVar[list[bool] | None] = ContextVar(
    "_bg_reported_flag", default=None
)


def init_bg_reported_flag() -> None:
    """Call before client connect() so all child tasks share the mutable ref."""
    _bg_reported_flag.set([False])


def mark_bg_reported() -> None:
    flag = _bg_reported_flag.get()
    if flag is not None:
        flag[0] = True


def bg_reported() -> bool:
    flag = _bg_reported_flag.get()
    return bool(flag and flag[0])


# ---------------------------------------------------------------------------
# Pending updates (fork → main session bridge)
# ---------------------------------------------------------------------------

_UPDATES_FILE = Path.home() / ".ollim-bot" / "pending_updates.json"
_TZ = ZoneInfo("America/Los_Angeles")
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
        _UPDATES_FILE.parent.mkdir(parents=True, exist_ok=True)
        updates = (
            json.loads(_UPDATES_FILE.read_text()) if _UPDATES_FILE.exists() else []
        )
        updates.append({"ts": datetime.now(_TZ).isoformat(), "message": message})
        fd, tmp = tempfile.mkstemp(dir=_UPDATES_FILE.parent, suffix=".tmp")
        try:
            os.write(fd, json.dumps(updates).encode())
        finally:
            os.close(fd)
        os.replace(tmp, _UPDATES_FILE)
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


def set_interactive_fork(active: bool, *, idle_timeout: int = 10) -> None:
    """Enter or exit interactive fork mode."""
    global \
        _in_interactive_fork, \
        _fork_exit_action, \
        _fork_idle_timeout, \
        _fork_prompted_at
    _in_interactive_fork = active
    _fork_idle_timeout = idle_timeout
    if active:
        _fork_exit_action = ForkExitAction.NONE
        _fork_prompted_at = None
    else:
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


def request_enter_fork(topic: str | None, *, idle_timeout: int = 10) -> None:
    global _enter_fork_requested, _enter_fork_topic, _enter_fork_timeout
    _enter_fork_requested = True
    _enter_fork_topic = topic
    _enter_fork_timeout = idle_timeout


def pop_enter_fork() -> tuple[str | None, int]:
    """Read and clear the enter-fork request. Returns (topic, idle_timeout)."""
    global _enter_fork_requested, _enter_fork_topic, _enter_fork_timeout
    if not _enter_fork_requested:
        return None, 10
    topic = _enter_fork_topic
    timeout = _enter_fork_timeout
    _enter_fork_requested = False
    _enter_fork_topic = None
    _enter_fork_timeout = 10
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
    channel: discord.abc.Messageable, tag: str, *, timed_out: bool = False
) -> None:
    """Best-effort DM notification when a bg fork fails or times out."""
    if timed_out:
        msg = (
            f"Background task timed out after {BG_FORK_TIMEOUT // 60} minutes: `{tag}`"
        )
    else:
        msg = f"Background task failed: `{tag}` -- check logs for details."
    with contextlib.suppress(Exception):
        await channel.send(msg)


async def run_agent_background(
    owner: discord.User,
    agent: Agent,
    prompt: str,
    *,
    model: str | None = None,
    thinking: bool = True,
    isolated: bool = False,
    bg_config: BgForkConfig | None = None,
) -> None:
    """Run agent on a disposable forked session — no lock needed.

    Contextvars scope channel and in_fork state to this task, so bg forks
    run concurrently without stomping on main session or other forks.
    """
    from ollim_bot.agent_tools import set_fork_channel
    from ollim_bot.sessions import (
        cancel_message_collector,
        flush_message_collector,
        load_session_id,
        log_session_event,
        start_message_collector,
    )

    tag = _extract_prompt_tag(prompt)
    busy = agent.lock().locked()
    if busy:
        log.info("bg fork running in quiet mode (user busy): %s", tag)

    log.info("bg fork started: %s", tag)

    dm = await owner.create_dm()
    set_fork_channel(dm)
    main_session_id = load_session_id()
    # CRITICAL: set_in_fork(True) and set_busy() must precede
    # create_forked_client() so the contextvars propagate through the SDK's
    # task-group spawn chain to reach the can_use_tool callback.
    set_in_fork(True)
    set_busy(busy)
    init_bg_output_flag()
    init_bg_reported_flag()
    if bg_config:
        set_bg_fork_config(bg_config)
    start_message_collector()

    try:
        async with asyncio.timeout(BG_FORK_TIMEOUT):
            if isolated:
                client = await agent.create_isolated_client(
                    model=model, thinking=thinking
                )
            else:
                client = await agent.create_forked_client()
            try:
                fork_session_id = await agent.run_on_client(
                    client, prompt, prepend_updates=not isolated
                )
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
        log.warning("bg fork timed out after %ds: %s", BG_FORK_TIMEOUT, tag)
        await _notify_fork_failure(dm, tag, timed_out=True)
    except Exception:
        log.exception("bg fork failed: %s", tag)
        await _notify_fork_failure(dm, tag)
        raise
    finally:
        set_in_fork(False)
        set_busy(False)
        cancel_message_collector()


async def send_agent_dm(
    owner: discord.User,
    agent: Agent,
    prompt: str,
) -> None:
    """Inject a prompt into the agent session and stream the response as a DM."""
    from ollim_bot.agent_tools import set_channel
    from ollim_bot.streamer import stream_to_channel

    from ollim_bot import permissions

    dm = await owner.create_dm()
    async with agent.lock():
        set_channel(dm)
        permissions.set_channel(dm)
        await dm.typing()
        await stream_to_channel(dm, agent.stream_chat(prompt))
