"""Persist Agent SDK session ID so conversations survive bot restarts."""

import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal
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
