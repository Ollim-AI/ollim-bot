"""Reminder data model and JSONL persistence.

Reminders are one-shot time-based nudges. They support chaining via a state
machine: a reminder with max_chain > 0 can be followed up by the agent calling
the follow_up_chain MCP tool, which creates a new reminder at chain_depth + 1.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from ollim_bot.storage import DATA_DIR, TZ, append_jsonl, read_jsonl, remove_jsonl

REMINDERS_FILE = DATA_DIR / "reminders.jsonl"


@dataclass(frozen=True, slots=True)
class Reminder:
    id: str
    message: str
    run_at: str  # ISO datetime
    background: bool = False
    skip_if_busy: bool = True
    chain_depth: int = 0
    max_chain: int = 0  # 0 = plain one-shot, N = allow N continuations
    chain_parent: str | None = None

    @staticmethod
    def new(
        message: str,
        *,
        delay_minutes: int,
        background: bool = False,
        skip_if_busy: bool = True,
        max_chain: int = 0,
        chain_depth: int = 0,
        chain_parent: str | None = None,
    ) -> "Reminder":
        run_at = (datetime.now(TZ) + timedelta(minutes=delay_minutes)).isoformat()
        rid = uuid4().hex[:8]
        assert chain_depth <= max_chain, (
            f"chain_depth ({chain_depth}) > max_chain ({max_chain})"
        )
        return Reminder(
            id=rid,
            message=message,
            run_at=run_at,
            background=background,
            skip_if_busy=skip_if_busy,
            chain_depth=chain_depth,
            max_chain=max_chain,
            chain_parent=chain_parent or (rid if max_chain > 0 else None),
        )


def append_reminder(reminder: Reminder) -> None:
    append_jsonl(REMINDERS_FILE, reminder, f"add reminder {reminder.id}")


def list_reminders() -> list[Reminder]:
    return read_jsonl(REMINDERS_FILE, Reminder)


def remove_reminder(reminder_id: str) -> bool:
    return remove_jsonl(
        REMINDERS_FILE, reminder_id, Reminder, f"remove reminder {reminder_id}"
    )
