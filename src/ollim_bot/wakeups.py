"""Shared reminder data structures and JSONL file I/O.

The JSONL file is the source of truth -- reminders persist across restarts.
One-shot reminders store an absolute `run_at` so they survive restarts.
"""

import dataclasses
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Los_Angeles")

WAKEUPS_FILE = Path.home() / ".ollim-bot" / "wakeups.jsonl"


_WAKEUP_FIELDS: set[str] | None = None


@dataclass
class Wakeup:
    id: str
    message: str
    run_at: str | None = None  # ISO datetime for one-shot
    cron: str | None = None
    interval_minutes: int | None = None

    @staticmethod
    def new(
        message: str,
        *,
        delay_minutes: int | None = None,
        cron: str | None = None,
        interval_minutes: int | None = None,
    ) -> "Wakeup":
        run_at = None
        if delay_minutes is not None:
            run_at = (datetime.now(TZ) + timedelta(minutes=delay_minutes)).isoformat()
        return Wakeup(
            id=uuid4().hex[:8],
            message=message,
            run_at=run_at,
            cron=cron,
            interval_minutes=interval_minutes,
        )


def append_wakeup(wakeup: Wakeup) -> None:
    """Append a reminder to the JSONL file."""
    WAKEUPS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with WAKEUPS_FILE.open("a") as f:
        f.write(json.dumps(asdict(wakeup)) + "\n")


def _wakeup_fields() -> set[str]:
    global _WAKEUP_FIELDS
    if _WAKEUP_FIELDS is None:
        _WAKEUP_FIELDS = {f.name for f in dataclasses.fields(Wakeup)}
    return _WAKEUP_FIELDS


def list_wakeups() -> list[Wakeup]:
    """Read all reminders. Skips corrupt lines."""
    if not WAKEUPS_FILE.exists():
        return []
    fields = _wakeup_fields()
    result: list[Wakeup] = []
    for line in WAKEUPS_FILE.read_text().splitlines():
        stripped = line.strip()
        if not stripped or not stripped.startswith("{"):
            continue
        data = json.loads(stripped)
        result.append(Wakeup(**{k: v for k, v in data.items() if k in fields}))
    return result


def remove_wakeup(wakeup_id: str) -> bool:
    """Remove a reminder by ID. Returns True if found.

    Uses atomic write (temp file + rename) to avoid data loss
    if a concurrent subprocess appends while we rewrite.
    """
    wakeups = list_wakeups()
    filtered = [w for w in wakeups if w.id != wakeup_id]
    if len(filtered) == len(wakeups):
        return False
    content = "".join(json.dumps(asdict(w)) + "\n" for w in filtered)
    fd, tmp = tempfile.mkstemp(dir=WAKEUPS_FILE.parent, suffix=".tmp")
    os.write(fd, content.encode())
    os.close(fd)
    os.replace(tmp, WAKEUPS_FILE)
    return True
