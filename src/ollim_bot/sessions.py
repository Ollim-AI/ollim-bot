"""Persist Agent SDK session IDs so conversations survive bot restarts."""

import json
import os
import tempfile
from pathlib import Path

SESSIONS_FILE = Path.home() / ".ollim-bot" / "sessions.json"


def load_session_id(user_id: str) -> str | None:
    return _read().get(user_id)


def save_session_id(user_id: str, session_id: str) -> None:
    """Atomic write -- safe to call mid-stream without corrupting concurrent reads."""
    _write({**_read(), user_id: session_id})


def delete_session_id(user_id: str) -> None:
    _write({k: v for k, v in _read().items() if k != user_id})


def _read() -> dict[str, str]:
    if not SESSIONS_FILE.exists():
        return {}
    return json.loads(SESSIONS_FILE.read_text())


def _write(data: dict[str, str]) -> None:
    SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=SESSIONS_FILE.parent, suffix=".tmp")
    os.write(fd, json.dumps(data).encode())
    os.close(fd)
    os.replace(tmp, SESSIONS_FILE)
