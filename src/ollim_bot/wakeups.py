"""Shared wakeup data structures and JSONL file I/O."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

WAKEUPS_FILE = Path.home() / ".ollim-bot" / "wakeups.jsonl"


@dataclass
class Wakeup:
    id: str
    message: str
    user_id: str = "owner"
    delay_minutes: int | None = None
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
        return Wakeup(
            id=uuid4().hex[:8],
            message=message,
            delay_minutes=delay_minutes,
            cron=cron,
            interval_minutes=interval_minutes,
        )


def append_wakeup(wakeup: Wakeup) -> None:
    """Append a wakeup entry to the JSONL file."""
    WAKEUPS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with WAKEUPS_FILE.open("a") as f:
        f.write(json.dumps(asdict(wakeup)) + "\n")


def list_wakeups() -> list[Wakeup]:
    """Read all wakeups without draining."""
    if not WAKEUPS_FILE.exists():
        return []
    lines = WAKEUPS_FILE.read_text().splitlines()
    return [Wakeup(**json.loads(line)) for line in lines if line.strip()]


def drain_wakeups() -> list[Wakeup]:
    """Read all wakeups and truncate the file."""
    if not WAKEUPS_FILE.exists():
        return []
    lines = WAKEUPS_FILE.read_text().splitlines()
    WAKEUPS_FILE.write_text("")
    return [Wakeup(**json.loads(line)) for line in lines if line.strip()]


def remove_wakeup(wakeup_id: str) -> bool:
    """Remove a wakeup by ID. Returns True if found."""
    wakeups = list_wakeups()
    filtered = [w for w in wakeups if w.id != wakeup_id]
    if len(filtered) == len(wakeups):
        return False
    WAKEUPS_FILE.write_text(
        "".join(json.dumps(asdict(w)) + "\n" for w in filtered)
    )
    return True
