"""Routine data model and JSONL persistence.

Routines are recurring cron-scheduled prompts that define the daily/weekly rhythm.
Always cron-based, persist indefinitely, user-managed.
"""

from dataclasses import dataclass
from uuid import uuid4

from ollim_bot.storage import DATA_DIR, append_jsonl, read_jsonl, remove_jsonl

ROUTINES_FILE = DATA_DIR / "routines.jsonl"


@dataclass(frozen=True, slots=True)
class Routine:
    id: str
    message: str
    cron: str
    background: bool = False
    skip_if_busy: bool = True

    @staticmethod
    def new(
        message: str,
        *,
        cron: str,
        background: bool = False,
        skip_if_busy: bool = True,
    ) -> "Routine":
        return Routine(
            id=uuid4().hex[:8],
            message=message,
            cron=cron,
            background=background,
            skip_if_busy=skip_if_busy,
        )


def append_routine(routine: Routine) -> None:
    append_jsonl(ROUTINES_FILE, routine, f"add routine {routine.id}")


def list_routines() -> list[Routine]:
    return read_jsonl(ROUTINES_FILE, Routine)


def remove_routine(routine_id: str) -> bool:
    return remove_jsonl(
        ROUTINES_FILE, routine_id, Routine, f"remove routine {routine_id}"
    )
