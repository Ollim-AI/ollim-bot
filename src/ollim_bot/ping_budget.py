"""Daily ping budget tracking — limits how many times the bot can ping the user."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from ollim_bot.storage import DATA_DIR, TZ

if TYPE_CHECKING:
    from ollim_bot.scheduling.reminders import Reminder
    from ollim_bot.scheduling.routines import Routine

BUDGET_FILE: Path = DATA_DIR / "ping_budget.json"
_DEFAULT_LIMIT = 10


@dataclass(frozen=True, slots=True)
class BudgetState:
    daily_limit: int
    used: int
    critical_used: int
    last_reset: str  # ISO date


def load() -> BudgetState:
    """Read budget from disk; auto-reset counters if date is stale; create defaults if missing."""
    today = date.today().isoformat()

    if not BUDGET_FILE.exists():
        state = BudgetState(
            daily_limit=_DEFAULT_LIMIT, used=0, critical_used=0, last_reset=today
        )
        save(state)
        return state

    data = json.loads(BUDGET_FILE.read_text())
    state = BudgetState(**data)

    if state.last_reset != today:
        state = replace(state, used=0, critical_used=0, last_reset=today)
        save(state)

    return state


def save(state: BudgetState) -> None:
    """Atomic write via tempfile + os.replace. No git commit — ephemeral state."""
    BUDGET_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=BUDGET_FILE.parent, suffix=".tmp")
    os.write(fd, json.dumps(asdict(state)).encode())
    os.close(fd)
    os.replace(tmp, BUDGET_FILE)


def try_use() -> bool:
    """Decrement remaining budget. Returns False if exhausted."""
    state = load()
    if state.used >= state.daily_limit:
        return False
    save(replace(state, used=state.used + 1))
    return True


def record_critical() -> None:
    """Increment critical_used counter (does not consume regular budget)."""
    state = load()
    save(replace(state, critical_used=state.critical_used + 1))


def get_status() -> str:
    """Formatted budget status string."""
    state = load()
    remaining = state.daily_limit - state.used
    parts = [f"{remaining}/{state.daily_limit} remaining today"]
    if state.used:
        parts.append(f"{state.used} used")
    if state.critical_used:
        parts.append(f"{state.critical_used} critical")
    return ", ".join(parts)


def set_limit(limit: int) -> None:
    """Update daily_limit, preserving other state."""
    state = load()
    save(replace(state, daily_limit=limit))


def remaining_today(
    reminders: list[Reminder],
    routines: list[Routine],
) -> tuple[int, int]:
    """Count bg reminders firing before midnight and bg routines (total count).

    Returns (bg_reminders_remaining, bg_routines_count).
    """
    now = datetime.now(TZ)
    midnight = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    bg_reminders = sum(
        1
        for r in reminders
        if r.background and now <= datetime.fromisoformat(r.run_at) < midnight
    )
    bg_routines = sum(1 for r in routines if r.background)

    return bg_reminders, bg_routines
