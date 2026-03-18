"""Persist button inquiry prompts so agent buttons survive bot restarts."""

import json
import time
from typing import TypedDict
from uuid import uuid4

from ollim_bot.storage import STATE_DIR, atomic_write, safe_json_load


class _InquiryEntry(TypedDict):
    prompt: str
    ts: float


INQUIRIES_FILE = STATE_DIR / "inquiries.json"
MAX_AGE = 7 * 24 * 3600  # 7 days


def register(prompt: str) -> str:
    uid = uuid4().hex[:8]  # 8 hex chars: short enough for custom_id, collision-safe at this scale
    data = _read()
    data[uid] = {"prompt": prompt, "ts": time.time()}
    _write(data)
    return uid


def peek(uid: str) -> str | None:
    data = _read()
    entry = data.get(uid)
    return entry["prompt"] if entry else None


def pop(uid: str) -> str | None:
    """Returns None for both expired and never-registered IDs."""
    data = _read()
    entry = data.pop(uid, None)
    if entry is None:
        return None
    _write(data)
    return entry["prompt"]


def _read() -> dict[str, _InquiryEntry]:
    data = safe_json_load(INQUIRIES_FILE, {})
    cutoff = time.time() - MAX_AGE
    return {k: v for k, v in data.items() if v.get("ts", 0) > cutoff}


def _write(data: dict[str, _InquiryEntry]) -> None:
    atomic_write(INQUIRIES_FILE, json.dumps(data).encode())
