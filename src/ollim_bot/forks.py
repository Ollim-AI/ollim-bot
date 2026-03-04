"""Pending updates I/O and background fork execution."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from ollim_bot.agent_tools import ChainContext

from ollim_bot.channel import get_channel
from ollim_bot.config import TZ
from ollim_bot.fork_state import (
    init_bg_tracking,
    set_bg_fork_config,
    set_busy,
    set_in_fork,
)
from ollim_bot.storage import STATE_DIR, atomic_write

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    import discord
    from claude_agent_sdk import ClaudeSDKClient

    from ollim_bot.agent import Agent
    from ollim_bot.fork_state import BgForkConfig


# ---------------------------------------------------------------------------
# Pending updates (fork → main session bridge)
# ---------------------------------------------------------------------------

_UPDATES_FILE = STATE_DIR / "pending_updates.json"
_updates_lock = asyncio.Lock()
MAX_PENDING_UPDATES = 10


class PendingUpdate(NamedTuple):
    ts: str
    message: str


async def append_update(message: str) -> None:
    """Append a timestamped update to the pending updates file.

    Lock protects the read-modify-write cycle so concurrent bg forks
    don't lose each other's updates.  Capped at MAX_PENDING_UPDATES —
    oldest entries are dropped when the cap is exceeded.
    """
    async with _updates_lock:
        updates = json.loads(_UPDATES_FILE.read_text()) if _UPDATES_FILE.exists() else []
        updates.append({"ts": datetime.now(TZ).isoformat(), "message": message})
        if len(updates) > MAX_PENDING_UPDATES:
            # Keep the most-recent (MAX_PENDING_UPDATES - 1) real entries and
            # use the freed slot for a sentinel so the agent knows omission occurred.
            dropped = len(updates) - (MAX_PENDING_UPDATES - 1)
            updates = updates[-(MAX_PENDING_UPDATES - 1) :]
            sentinel = {
                "ts": datetime.now(TZ).isoformat(),
                "message": f"({dropped} earlier update(s) omitted — cap reached)",
            }
            updates.insert(0, sentinel)
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
# Background fork execution
# ---------------------------------------------------------------------------


def _extract_prompt_tag(prompt: str) -> str:
    """Extract the job tag from a bg fork prompt (e.g. '[routine-bg:morning-checkin]')."""
    if prompt.startswith("["):
        return prompt.split("]", 1)[0] + "]"
    return "bg fork"


def _tag_to_human_name(tag: str) -> str:
    """Convert a raw prompt tag to a human-readable task name.

    '[routine-bg:morning-checkin]' → 'morning checkin'
    'bg fork' → 'background task'
    """
    inner = tag.strip("[]")
    if ":" in inner:
        slug = inner.split(":", 1)[1]
    else:
        slug = inner
    return slug.replace("-", " ")


async def _notify_fork_failure(
    channel: discord.abc.Messageable, tag: str, *, timed_out: bool = False, timeout_seconds: int = 0
) -> None:
    """Best-effort DM notification when a bg fork fails or times out."""
    name = _tag_to_human_name(tag)
    if timed_out:
        msg = f"{name} timed out after {timeout_seconds // 60} minutes."
    else:
        msg = f"{name} couldn't complete."
    with contextlib.suppress(Exception):
        await channel.send(msg)


async def run_agent_background(
    agent: Agent,
    prompt: str,
    *,
    model: str | None = None,
    thinking: str = "adaptive",
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
            client: ClaudeSDKClient | None = None
            backoffs = (5, 15)
            for attempt in range(1 + len(backoffs)):
                try:
                    if isolated:
                        client = await agent.create_isolated_client(
                            model=model,
                            thinking=thinking,
                            allowed_tools=allowed,
                        )
                    else:
                        client = await agent.create_forked_client(
                            thinking=thinking,
                            allowed_tools=allowed,
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
                with contextlib.suppress(RuntimeError):
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
    *,
    chain_ctx: ChainContext | None = None,
) -> None:
    """Inject a prompt into the agent session and stream the response as a DM."""
    from ollim_bot.agent_tools import set_chain_context
    from ollim_bot.streamer import stream_to_channel

    dm = get_channel()
    async with agent.lock():
        if chain_ctx:
            set_chain_context(chain_ctx)
        await dm.typing()
        await stream_to_channel(dm, agent.stream_chat(prompt))
