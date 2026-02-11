"""Persist Agent SDK session IDs so conversations survive bot restarts."""

import json
import os
import tempfile
from pathlib import Path

SESSIONS_FILE = Path.home() / ".ollim-bot" / "sessions.json"


def load_session_id(user_id: str) -> str | None:
    """Load persisted session ID for a user."""
    if not SESSIONS_FILE.exists():
        return None
    data = json.loads(SESSIONS_FILE.read_text())
    return data.get(user_id)


def save_session_id(user_id: str, session_id: str) -> None:
    """Persist session ID for a user (atomic write)."""
    SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if SESSIONS_FILE.exists():
        data = json.loads(SESSIONS_FILE.read_text())
    data[user_id] = session_id
    fd, tmp = tempfile.mkstemp(dir=SESSIONS_FILE.parent, suffix=".tmp")
    os.write(fd, json.dumps(data).encode())
    os.close(fd)
    os.replace(tmp, SESSIONS_FILE)
