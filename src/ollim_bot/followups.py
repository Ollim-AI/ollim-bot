"""Persist button followup prompts so agent buttons survive bot restarts."""

import json
import os
import tempfile
import time
from pathlib import Path
from uuid import uuid4

FOLLOWUPS_FILE = Path.home() / ".ollim-bot" / "followups.json"
MAX_AGE = 7 * 24 * 3600  # 7 days


def register(prompt: str) -> str:
    """Store a prompt for agent followup, return its 8-char ID."""
    uid = uuid4().hex[:8]
    data = _read()
    data[uid] = {"prompt": prompt, "ts": time.time()}
    _write(data)
    return uid


def pop(uid: str) -> str | None:
    """Remove and return a followup prompt, or None if expired/missing."""
    data = _read()
    entry = data.pop(uid, None)
    if entry is None:
        return None
    _write(data)
    return entry["prompt"]


def _read() -> dict:
    if not FOLLOWUPS_FILE.exists():
        return {}
    data = json.loads(FOLLOWUPS_FILE.read_text())
    cutoff = time.time() - MAX_AGE
    return {k: v for k, v in data.items() if v.get("ts", 0) > cutoff}


def _write(data: dict) -> None:
    FOLLOWUPS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=FOLLOWUPS_FILE.parent, suffix=".tmp")
    os.write(fd, json.dumps(data).encode())
    os.close(fd)
    os.replace(tmp, FOLLOWUPS_FILE)
