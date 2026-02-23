"""Reminder data model and markdown persistence.

Reminders are one-shot time-based nudges. They support chaining via a state
machine: a reminder with max_chain > 0 can be followed up by the agent calling
the follow_up_chain MCP tool, which creates a new reminder at chain_depth + 1.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from ollim_bot.storage import DATA_DIR, TZ, read_md_dir, remove_md, write_md

REMINDERS_DIR = DATA_DIR / "reminders"


@dataclass(frozen=True, slots=True)
class Reminder:
    id: str
    message: str
    run_at: str  # ISO datetime
    background: bool = False
    chain_depth: int = 0
    max_chain: int = 0  # 0 = plain one-shot, N = allow N continuations
    chain_parent: str | None = None
    model: str | None = None
    thinking: bool = True
    isolated: bool = False
    description: str = ""
    update_main_session: str = "on_ping"
    allow_ping: bool = True
    allowed_tools: list[str] | None = None
    blocked_tools: list[str] | None = None

    def __post_init__(self) -> None:
        if self.allowed_tools is not None and self.blocked_tools is not None:
            raise ValueError("Cannot specify both allowed_tools and blocked_tools")

    @staticmethod
    def new(
        message: str,
        *,
        delay_minutes: int,
        background: bool = False,
        max_chain: int = 0,
        chain_depth: int = 0,
        chain_parent: str | None = None,
        model: str | None = None,
        thinking: bool = True,
        isolated: bool = False,
        description: str = "",
        update_main_session: str = "on_ping",
        allow_ping: bool = True,
        allowed_tools: list[str] | None = None,
        blocked_tools: list[str] | None = None,
    ) -> "Reminder":
        """Create a reminder, auto-setting chain_parent to own ID for chain roots."""
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
            chain_depth=chain_depth,
            max_chain=max_chain,
            chain_parent=chain_parent or (rid if max_chain > 0 else None),
            model=model,
            thinking=thinking,
            isolated=isolated,
            description=description,
            update_main_session=update_main_session,
            allow_ping=allow_ping,
            allowed_tools=allowed_tools,
            blocked_tools=blocked_tools,
        )


def append_reminder(reminder: Reminder) -> None:
    write_md(REMINDERS_DIR, reminder, f"add reminder {reminder.id}")


def list_reminders() -> list[Reminder]:
    return read_md_dir(REMINDERS_DIR, Reminder)


def remove_reminder(reminder_id: str) -> bool:
    return remove_md(REMINDERS_DIR, reminder_id, f"remove reminder {reminder_id}")
