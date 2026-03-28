# ollim-bot
# Copyright (C) 2025-2026 Julius Frost
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
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
    return {k: v for k, v in data.items() if v["ts"] > cutoff}


def _write(data: dict[str, _InquiryEntry]) -> None:
    atomic_write(INQUIRIES_FILE, json.dumps(data).encode())
