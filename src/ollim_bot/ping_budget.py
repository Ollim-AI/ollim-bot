"""Ping budget — refill-on-read bucket that limits bg fork pings."""

from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from pathlib import Path

from ollim_bot.storage import STATE_DIR, TZ

BUDGET_FILE: Path = STATE_DIR / "ping_budget.json"
_DEFAULT_CAPACITY = 5
_DEFAULT_REFILL_RATE = 90  # minutes per ping


@dataclass(frozen=True, slots=True)
class BudgetState:
    capacity: int
    available: float
    refill_rate_minutes: int
    last_refill: str  # ISO datetime
    critical_used: int
    critical_reset_date: str  # ISO date
    daily_used: int
    daily_used_reset: str  # ISO date


def _refill(state: BudgetState) -> BudgetState:
    """Compute accumulated refills since last_refill, cap at capacity."""
    now = datetime.now(TZ)
    last = datetime.fromisoformat(state.last_refill)
    elapsed_minutes = (now - last).total_seconds() / 60
    gained = elapsed_minutes / state.refill_rate_minutes
    new_available = min(state.available + gained, float(state.capacity))
    return replace(state, available=new_available, last_refill=now.isoformat())


def _reset_daily(state: BudgetState) -> BudgetState:
    """Reset daily counters if date is stale."""
    today = date.today().isoformat()
    if state.critical_reset_date != today:
        state = replace(state, critical_used=0, critical_reset_date=today)
    if state.daily_used_reset != today:
        state = replace(state, daily_used=0, daily_used_reset=today)
    return state


def load() -> BudgetState:
    """Read budget from disk; refill based on elapsed time; create defaults if missing."""
    now = datetime.now(TZ)
    today = date.today().isoformat()

    if not BUDGET_FILE.exists():
        state = BudgetState(
            capacity=_DEFAULT_CAPACITY,
            available=float(_DEFAULT_CAPACITY),
            refill_rate_minutes=_DEFAULT_REFILL_RATE,
            last_refill=now.isoformat(),
            critical_used=0,
            critical_reset_date=today,
            daily_used=0,
            daily_used_reset=today,
        )
        save(state)
        return state

    data = json.loads(BUDGET_FILE.read_text())

    state = BudgetState(**data)
    state = _refill(state)
    state = _reset_daily(state)
    save(state)
    return state


def save(state: BudgetState) -> None:
    """Atomic write via tempfile + os.replace. No git commit — ephemeral state."""
    BUDGET_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=BUDGET_FILE.parent, suffix=".tmp")
    try:
        os.write(fd, json.dumps(asdict(state)).encode())
    finally:
        os.close(fd)
    os.replace(tmp, BUDGET_FILE)


def try_use() -> bool:
    """Consume 1 ping if available. Returns False if insufficient."""
    state = load()
    if state.available < 1.0:
        return False
    save(replace(state, available=state.available - 1.0, daily_used=state.daily_used + 1))
    return True


def record_critical() -> None:
    """Increment critical_used counter (does not consume regular budget)."""
    state = load()
    save(replace(state, critical_used=state.critical_used + 1))


def get_status() -> str:
    """Formatted budget status for preamble injection."""
    state = load()
    avail = int(state.available)
    base = f"{avail}/{state.capacity} available (refills 1 every {state.refill_rate_minutes} min"
    if state.available < state.capacity:
        minutes_to_next = math.ceil((1.0 - (state.available - int(state.available))) * state.refill_rate_minutes)
        if state.available == int(state.available):
            minutes_to_next = state.refill_rate_minutes
        base += f", next in {minutes_to_next} min"
    base += ")"
    return base


def get_full_status() -> str:
    """Extended status for /ping-budget command (includes daily totals)."""
    state = load()
    status = get_status()
    parts = [status]
    if state.daily_used:
        parts.append(f"{state.daily_used} used today")
    if state.critical_used:
        parts.append(f"{state.critical_used} critical")
    return ", ".join(parts) if len(parts) > 1 else status


def set_capacity(capacity: int) -> None:
    """Update capacity, preserving other state."""
    state = load()
    save(replace(state, capacity=capacity))


def set_refill_rate(minutes: int) -> None:
    """Update refill rate, preserving other state."""
    state = load()
    save(replace(state, refill_rate_minutes=minutes))


def minutes_to_next_refill() -> int | None:
    """Minutes until next ping refill, or None if at capacity."""
    state = load()
    if state.available >= state.capacity:
        return None
    fractional = state.available - int(state.available)
    return math.ceil((1.0 - fractional) * state.refill_rate_minutes)
