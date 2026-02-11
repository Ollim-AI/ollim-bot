"""Shared reminder data structures and JSONL file I/O.

The JSONL file is the source of truth -- reminders persist across restarts.
One-shot reminders store an absolute `run_at` so they survive restarts.
"""

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


@dataclass
class Wakeup:
    id: str
    message: str
    user_id: str = "owner"
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


def list_wakeups() -> list[Wakeup]:
    """Read all reminders."""
    if not WAKEUPS_FILE.exists():
        return []
    lines = WAKEUPS_FILE.read_text().splitlines()
    return [Wakeup(**json.loads(line)) for line in lines if line.strip()]


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
