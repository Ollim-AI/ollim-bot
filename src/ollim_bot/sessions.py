"""Persist Agent SDK session ID so conversations survive bot restarts."""

import os
import tempfile
from pathlib import Path

SESSIONS_FILE = Path.home() / ".ollim-bot" / "sessions.json"


def load_session_id() -> str | None:
    if not SESSIONS_FILE.exists():
        return None
    text = SESSIONS_FILE.read_text().strip()
    if not text or text.startswith("{"):
        return None
    return text


def save_session_id(session_id: str) -> None:
    """Atomic write -- safe to call mid-stream without corrupting concurrent reads."""
    SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=SESSIONS_FILE.parent, suffix=".tmp")
    os.write(fd, session_id.encode())
    os.close(fd)
    os.replace(tmp, SESSIONS_FILE)


def delete_session_id() -> None:
    SESSIONS_FILE.unlink(missing_ok=True)
