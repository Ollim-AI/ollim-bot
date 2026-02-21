"""Daily ping budget tracking — limits how many times the bot can ping the user."""

import json
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from datetime import date
from pathlib import Path

from ollim_bot.storage import DATA_DIR

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
