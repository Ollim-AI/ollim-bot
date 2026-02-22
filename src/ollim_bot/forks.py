"""Fork state management, pending updates I/O, and background fork execution."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from contextvars import ContextVar
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

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


def set_in_fork(active: bool) -> None:
    _in_fork_var.set(active)


def in_bg_fork() -> bool:
    return _in_fork_var.get()


# ---------------------------------------------------------------------------
# Pending updates (fork → main session bridge)
# ---------------------------------------------------------------------------

_UPDATES_FILE = Path.home() / ".ollim-bot" / "pending_updates.json"
_TZ = ZoneInfo("America/Los_Angeles")
_updates_lock = asyncio.Lock()


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
        os.write(fd, json.dumps(updates).encode())
        os.close(fd)
        os.replace(tmp, _UPDATES_FILE)


def peek_pending_updates() -> list[str]:
    """Read pending updates without clearing."""
    if not _UPDATES_FILE.exists():
        return []
    updates = json.loads(_UPDATES_FILE.read_text())
    return [u["message"] for u in updates]


def clear_pending_updates() -> None:
    """Delete the pending updates file if it exists."""
    if _UPDATES_FILE.exists():
        _UPDATES_FILE.unlink()


async def pop_pending_updates() -> list[str]:
    """Read and clear all pending updates.

    Lock ensures atomicity with concurrent append_update calls —
    without it a bg fork's append can re-introduce already-popped updates.
    """
    async with _updates_lock:
        if not _UPDATES_FILE.exists():
            return []
        updates = json.loads(_UPDATES_FILE.read_text())
        _UPDATES_FILE.unlink()
        return [u["message"] for u in updates]


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


async def run_agent_background(
    owner: discord.User,
    agent: Agent,
    prompt: str,
    *,
    skip_if_busy: bool,
) -> None:
    """Run agent on a disposable forked session — no lock needed.

    Contextvars scope channel and in_fork state to this task, so bg forks
    run concurrently without stomping on main session or other forks.
    """
    from ollim_bot.agent_tools import set_fork_channel
    from ollim_bot.sessions import (
        flush_message_collector,
        load_session_id,
        log_session_event,
        start_message_collector,
    )

    if skip_if_busy and agent.lock().locked():
        return

    dm = await owner.create_dm()
    set_fork_channel(dm)
    main_session_id = load_session_id()
    # CRITICAL: set_in_fork(True) must precede create_forked_client() so the
    # contextvar propagates through the SDK's task-group spawn chain to reach
    # the can_use_tool callback. See design doc for details.
    set_in_fork(True)
    start_message_collector()

    try:
        client = await agent.create_forked_client()
        try:
            fork_session_id = await agent.run_on_client(client, prompt)
            log_session_event(
                fork_session_id,
                "bg_fork",
                parent_session_id=main_session_id,
            )
            flush_message_collector(fork_session_id, main_session_id)
        finally:
            await client.disconnect()
    finally:
        set_in_fork(False)


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
