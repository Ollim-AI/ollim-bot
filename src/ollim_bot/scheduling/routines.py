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
    model: str | None = None
    thinking: bool = True
    isolated: bool = False
    description: str = ""
    update_main_session: str = "on_ping"
    allow_ping: bool = True
    allowed_tools: list[str] | None = None
    disallowed_tools: list[str] | None = None
    session: str | None = None

    def __post_init__(self) -> None:
        if self.allowed_tools is not None and self.disallowed_tools is not None:
            raise ValueError("Cannot specify both allowed_tools and disallowed_tools")
        if self.session is not None:
            if self.session != "persistent":
                raise ValueError(f"Invalid session mode: {self.session!r} (must be 'persistent')")
            if not self.background:
                raise ValueError("session: persistent requires background: true")
            if self.isolated:
                raise ValueError("session: persistent and isolated: true are mutually exclusive")

    @staticmethod
    def new(
        message: str,
        *,
        cron: str,
        background: bool = False,
        model: str | None = None,
        thinking: bool = True,
        isolated: bool = False,
        description: str = "",
        update_main_session: str = "on_ping",
        allow_ping: bool = True,
        allowed_tools: list[str] | None = None,
        disallowed_tools: list[str] | None = None,
        session: str | None = None,
    ) -> "Routine":
        return Routine(
            id=uuid4().hex[:8],
            message=message,
            cron=cron,
            background=background,
            model=model,
            thinking=thinking,
            isolated=isolated,
            description=description,
            update_main_session=update_main_session,
            allow_ping=allow_ping,
            allowed_tools=allowed_tools,
            disallowed_tools=disallowed_tools,
            session=session,
        )


def append_routine(routine: Routine) -> None:
    write_md(ROUTINES_DIR, routine, f"add routine {routine.id}")


def list_routines() -> list[Routine]:
    return read_md_dir(ROUTINES_DIR, Routine)


def remove_routine(routine_id: str) -> bool:
    return remove_md(ROUTINES_DIR, routine_id, f"remove routine {routine_id}")
