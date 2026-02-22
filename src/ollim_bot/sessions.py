"""Persist Agent SDK session ID so conversations survive bot restarts."""

import json
import os
import tempfile
import time
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, TypedDict
from zoneinfo import ZoneInfo

from ollim_bot.storage import append_jsonl

SESSIONS_FILE = Path.home() / ".ollim-bot" / "sessions.json"
HISTORY_FILE = Path.home() / ".ollim-bot" / "session_history.jsonl"

SessionEventType = Literal[
    "created",
    "compacted",
    "swapped",
    "cleared",
    "interactive_fork",
    "bg_fork",
    "isolated_bg",
]

_TZ = ZoneInfo("America/Los_Angeles")


@dataclass(frozen=True)
class SessionEvent:
    session_id: str
    event: SessionEventType
    timestamp: str
    parent_session_id: str | None = None


def log_session_event(
    session_id: str,
    event: SessionEventType,
    *,
    parent_session_id: str | None = None,
) -> None:
    ts = datetime.now(_TZ).isoformat()
    entry = SessionEvent(
        session_id=session_id,
        event=event,
        timestamp=ts,
        parent_session_id=parent_session_id,
    )
    append_jsonl(HISTORY_FILE, entry, f"session {event}: {session_id[:8]}")


def load_session_id() -> str | None:
    if not SESSIONS_FILE.exists():
        return None
    text = SESSIONS_FILE.read_text().strip()
    if not text or text.startswith("{"):
        return None
    return text


_swap_in_progress: bool = False  # duplicate-ok


def set_swap_in_progress(active: bool) -> None:
    global _swap_in_progress
    _swap_in_progress = active


def save_session_id(session_id: str) -> None:
    """Atomic write with auto-detection of session lifecycle events.

    Logs 'created' when no prior session ID exists, 'compacted' when the ID
    changes (SDK auto-compaction). Suppressed when _swap_in_progress is set
    because swap_client() logs its own 'swapped' event.
    """
    if not _swap_in_progress:
        current = load_session_id()
        if current is None:
            log_session_event(session_id, "created")
        elif current != session_id:
            log_session_event(session_id, "compacted", parent_session_id=current)

    SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=SESSIONS_FILE.parent, suffix=".tmp")
    os.write(fd, session_id.encode())
    os.close(fd)
    os.replace(tmp, SESSIONS_FILE)


def delete_session_id() -> None:
    SESSIONS_FILE.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Fork message tracking — maps Discord message IDs to fork session IDs
# ---------------------------------------------------------------------------

FORK_MESSAGES_FILE = Path.home() / ".ollim-bot" / "fork_messages.json"
_MAX_AGE = 7 * 24 * 3600  # 7 days

_msg_collector: ContextVar[list[int] | None] = ContextVar(
    "_msg_collector", default=None
)


class _ForkMessageRecord(TypedDict):
    message_id: int
    fork_session_id: str
    parent_session_id: str | None
    ts: float


def start_message_collector() -> None:
    """Initialize a contextvar list to collect Discord message IDs during a bg fork."""
    _msg_collector.set([])


def cancel_message_collector() -> None:
    """Discard any collected message IDs without writing. Safe to call if already flushed."""
    _msg_collector.set(None)


def track_message(message_id: int) -> None:
    """Append a Discord message ID to the active collector. No-op if no collector."""
    collector = _msg_collector.get()
    if collector is not None:
        collector.append(message_id)


def flush_message_collector(
    fork_session_id: str, parent_session_id: str | None
) -> None:
    """Write collected message IDs to fork_messages.json and clear the collector."""
    collector = _msg_collector.get()
    _msg_collector.set(None)
    if not collector:
        return
    records = _read_fork_messages()
    ts = time.time()
    for mid in collector:
        records.append(
            _ForkMessageRecord(
                message_id=mid,
                fork_session_id=fork_session_id,
                parent_session_id=parent_session_id,
                ts=ts,
            )
        )
    _write_fork_messages(records)


def lookup_fork_session(message_id: int) -> str | None:
    """Return the fork session ID for a Discord message, or None."""
    for record in _read_fork_messages():
        if record["message_id"] == message_id:
            return record["fork_session_id"]
    return None


def _read_fork_messages() -> list[_ForkMessageRecord]:
    if not FORK_MESSAGES_FILE.exists():
        return []
    data: list[_ForkMessageRecord] = json.loads(FORK_MESSAGES_FILE.read_text())
    cutoff = time.time() - _MAX_AGE
    return [r for r in data if r["ts"] > cutoff]


def _write_fork_messages(records: list[_ForkMessageRecord]) -> None:
    FORK_MESSAGES_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=FORK_MESSAGES_FILE.parent, suffix=".tmp")
    os.write(fd, json.dumps(records).encode())
    os.close(fd)
    os.replace(tmp, FORK_MESSAGES_FILE)
