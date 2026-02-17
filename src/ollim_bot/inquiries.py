"""Persist button inquiry prompts so agent buttons survive bot restarts."""

import json
import os
import tempfile
import time
from pathlib import Path
from typing import TypedDict
from uuid import uuid4


class _InquiryEntry(TypedDict):
    prompt: str
    ts: float


INQUIRIES_FILE = Path.home() / ".ollim-bot" / "inquiries.json"
MAX_AGE = 7 * 24 * 3600  # 7 days


def register(prompt: str) -> str:
    """IDs are 8 hex chars; short enough for custom_id but collision risk is negligible at this scale."""
    uid = uuid4().hex[:8]
    data = _read()
    data[uid] = {"prompt": prompt, "ts": time.time()}
    _write(data)
    return uid


def pop(uid: str) -> str | None:
    """Returns None for both expired and never-registered IDs."""
    data = _read()
    entry = data.pop(uid, None)
    if entry is None:
        return None
    _write(data)
    return entry["prompt"]


def _read() -> dict[str, _InquiryEntry]:
    if not INQUIRIES_FILE.exists():
        return {}
    data = json.loads(INQUIRIES_FILE.read_text())
    cutoff = time.time() - MAX_AGE
    return {k: v for k, v in data.items() if v.get("ts", 0) > cutoff}


def _write(data: dict[str, _InquiryEntry]) -> None:
    INQUIRIES_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=INQUIRIES_FILE.parent, suffix=".tmp")
    os.write(fd, json.dumps(data).encode())
    os.close(fd)
    os.replace(tmp, INQUIRIES_FILE)
