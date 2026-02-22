"""Routine data model and markdown persistence.

Routines are recurring cron-scheduled prompts that define the daily/weekly rhythm.
Always cron-based, persist indefinitely, user-managed.
"""

from dataclasses import dataclass
from uuid import uuid4

from ollim_bot.storage import DATA_DIR, read_md_dir, remove_md, write_md

ROUTINES_DIR = DATA_DIR / "routines"


@dataclass(frozen=True, slots=True)
class Routine:
    id: str
    message: str
    cron: str
    background: bool = False
    skip_if_busy: bool = True
    model: str | None = None
    isolated: bool = False
    description: str = ""

    @staticmethod
    def new(
        message: str,
        *,
        cron: str,
        background: bool = False,
        skip_if_busy: bool = True,
        model: str | None = None,
        isolated: bool = False,
        description: str = "",
    ) -> "Routine":
        return Routine(
            id=uuid4().hex[:8],
            message=message,
            cron=cron,
            background=background,
            skip_if_busy=skip_if_busy,
            model=model,
            isolated=isolated,
            description=description,
        )


def append_routine(routine: Routine) -> None:
    write_md(ROUTINES_DIR, routine, f"add routine {routine.id}")


def list_routines() -> list[Routine]:
    return read_md_dir(ROUTINES_DIR, Routine)


def remove_routine(routine_id: str) -> bool:
    return remove_md(ROUTINES_DIR, routine_id, f"remove routine {routine_id}")
