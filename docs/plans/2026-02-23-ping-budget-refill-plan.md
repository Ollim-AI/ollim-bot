# Ping Budget Refill Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the flat daily ping counter with a refill-on-read bucket and inject a forward schedule of upcoming bg tasks into the bg preamble.

**Architecture:** Rewrite `ping_budget.py` with lazy refill-on-read mechanics, add `_build_upcoming_schedule()` to `scheduler.py` that computes the dynamic `[now-15min, now+3h]` window, update `_build_bg_preamble()` to render the new budget + schedule, and update `prompts.py` stable text.

**Tech Stack:** Python dataclasses, APScheduler CronTrigger (for next-fire-time), existing YAML frontmatter routines/reminders.

**Principles:** @python-principles (frozen dataclasses, type safety, test behavior not implementation). @context-engineering-principles (separate stable from volatile, make intent explicit).

---

### Task 1: Rewrite `ping_budget.py` — BudgetState and refill logic

**Files:**
- Modify: `src/ollim_bot/ping_budget.py` (full rewrite)
- Test: `tests/test_ping_budget.py` (full rewrite)

**Step 1: Write the failing tests**

Replace `tests/test_ping_budget.py` entirely:

```python
"""Tests for ping_budget.py — refill-on-read ping budget."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from ollim_bot import ping_budget
from ollim_bot.ping_budget import BudgetState

TZ = ZoneInfo("America/Los_Angeles")


def test_load_returns_defaults_when_no_file(data_dir):
    state = ping_budget.load()

    assert state.capacity == 5
    assert state.available == 5.0
    assert state.refill_rate_minutes == 90
    assert state.critical_used == 0
    assert state.daily_used == 0


def test_save_and_load_roundtrip(data_dir):
    now = datetime.now(TZ)
    state = BudgetState(
        capacity=5,
        available=3.0,
        refill_rate_minutes=90,
        last_refill=now.isoformat(),
        critical_used=1,
        critical_reset_date=date.today().isoformat(),
        daily_used=2,
        daily_used_reset=date.today().isoformat(),
    )

    ping_budget.save(state)
    loaded = ping_budget.load()

    assert loaded.capacity == 5
    assert loaded.available >= 3.0  # may have tiny refill from elapsed
    assert loaded.critical_used == 1
    assert loaded.daily_used == 2


def test_load_refills_based_on_elapsed_time(data_dir):
    two_hours_ago = datetime.now(TZ) - timedelta(hours=2)
    state = BudgetState(
        capacity=5,
        available=1.0,
        refill_rate_minutes=60,
        last_refill=two_hours_ago.isoformat(),
        critical_used=0,
        critical_reset_date=date.today().isoformat(),
        daily_used=4,
        daily_used_reset=date.today().isoformat(),
    )
    ping_budget.save(state)

    loaded = ping_budget.load()

    assert loaded.available == 3.0  # 1.0 + 2h/60min = 3.0


def test_load_refill_caps_at_capacity(data_dir):
    long_ago = datetime.now(TZ) - timedelta(hours=24)
    state = BudgetState(
        capacity=5,
        available=0.0,
        refill_rate_minutes=60,
        last_refill=long_ago.isoformat(),
        critical_used=0,
        critical_reset_date=date.today().isoformat(),
        daily_used=10,
        daily_used_reset=date.today().isoformat(),
    )
    ping_budget.save(state)

    loaded = ping_budget.load()

    assert loaded.available == 5.0


def test_load_resets_daily_counters_on_stale_date(data_dir):
    now = datetime.now(TZ)
    state = BudgetState(
        capacity=5,
        available=2.0,
        refill_rate_minutes=90,
        last_refill=now.isoformat(),
        critical_used=3,
        critical_reset_date="2025-01-01",
        daily_used=8,
        daily_used_reset="2025-01-01",
    )
    ping_budget.save(state)

    loaded = ping_budget.load()

    assert loaded.critical_used == 0
    assert loaded.daily_used == 0
    assert loaded.critical_reset_date == date.today().isoformat()
    assert loaded.daily_used_reset == date.today().isoformat()


def test_load_migrates_old_format(data_dir):
    """Old format with daily_limit/used/last_reset gets migrated to fresh state."""
    import json

    old = {"daily_limit": 10, "used": 5, "critical_used": 1, "last_reset": "2026-02-23"}
    ping_budget.BUDGET_FILE.parent.mkdir(parents=True, exist_ok=True)
    ping_budget.BUDGET_FILE.write_text(json.dumps(old))

    loaded = ping_budget.load()

    assert loaded.capacity == 5
    assert loaded.available == 5.0
    assert loaded.refill_rate_minutes == 90


def test_try_use_decrements(data_dir):
    ping_budget.load()

    result = ping_budget.try_use()

    assert result is True
    state = ping_budget.load()
    assert state.available >= 3.0  # 5 - 1 = 4, plus tiny refill
    assert state.daily_used == 1


def test_try_use_returns_false_when_empty(data_dir):
    now = datetime.now(TZ)
    state = BudgetState(
        capacity=5,
        available=0.5,
        refill_rate_minutes=90,
        last_refill=now.isoformat(),
        critical_used=0,
        critical_reset_date=date.today().isoformat(),
        daily_used=5,
        daily_used_reset=date.today().isoformat(),
    )
    ping_budget.save(state)

    result = ping_budget.try_use()

    assert result is False


def test_try_use_succeeds_after_refill(data_dir):
    ninety_min_ago = datetime.now(TZ) - timedelta(minutes=90)
    state = BudgetState(
        capacity=5,
        available=0.0,
        refill_rate_minutes=90,
        last_refill=ninety_min_ago.isoformat(),
        critical_used=0,
        critical_reset_date=date.today().isoformat(),
        daily_used=5,
        daily_used_reset=date.today().isoformat(),
    )
    ping_budget.save(state)

    result = ping_budget.try_use()

    assert result is True  # refilled 1.0, then spent it


def test_record_critical_increments(data_dir):
    ping_budget.load()

    ping_budget.record_critical()

    state = ping_budget.load()
    assert state.critical_used == 1


def test_set_capacity_updates(data_dir):
    ping_budget.load()

    ping_budget.set_capacity(7)

    state = ping_budget.load()
    assert state.capacity == 7


def test_set_refill_rate_updates(data_dir):
    ping_budget.load()

    ping_budget.set_refill_rate(60)

    state = ping_budget.load()
    assert state.refill_rate_minutes == 60


def test_get_status_at_capacity(data_dir):
    ping_budget.load()

    status = ping_budget.get_status()

    assert "5/5 available" in status
    assert "refills 1 every 90 min" in status
    assert "next in" not in status  # at capacity, no refill line


def test_get_status_below_capacity(data_dir):
    now = datetime.now(TZ)
    state = BudgetState(
        capacity=5,
        available=3.0,
        refill_rate_minutes=90,
        last_refill=now.isoformat(),
        critical_used=0,
        critical_reset_date=date.today().isoformat(),
        daily_used=2,
        daily_used_reset=date.today().isoformat(),
    )
    ping_budget.save(state)

    status = ping_budget.get_status()

    assert "3/5 available" in status
    assert "next in" in status


def test_get_status_shows_daily_used(data_dir):
    now = datetime.now(TZ)
    state = BudgetState(
        capacity=5,
        available=5.0,
        refill_rate_minutes=90,
        last_refill=now.isoformat(),
        critical_used=1,
        critical_reset_date=date.today().isoformat(),
        daily_used=3,
        daily_used_reset=date.today().isoformat(),
    )
    ping_budget.save(state)

    status = ping_budget.get_status()

    assert "3 used today" in status
    assert "1 critical" in status
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ping_budget.py -v`
Expected: FAIL — `BudgetState` has wrong fields, missing functions.

**Step 3: Write the implementation**

Replace `src/ollim_bot/ping_budget.py`:

```python
"""Ping budget — refill-on-read bucket that limits bg fork pings."""

from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from pathlib import Path

from ollim_bot.storage import DATA_DIR, TZ

BUDGET_FILE: Path = DATA_DIR / "ping_budget.json"
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

    # Migrate old format (daily_limit/used/last_reset)
    if "daily_limit" in data and "capacity" not in data:
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
        minutes_to_next = math.ceil(
            (1.0 - (state.available - int(state.available))) * state.refill_rate_minutes
        )
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
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ping_budget.py -v`
Expected: All PASS.

**Step 5: Commit**

```bash
git add src/ollim_bot/ping_budget.py tests/test_ping_budget.py
git commit -m "feat: replace flat ping counter with refill-on-read bucket"
```

---

### Task 2: Add `_build_upcoming_schedule()` to scheduler.py

**Files:**
- Modify: `src/ollim_bot/scheduling/scheduler.py:92-245` (replace `_fires_before_midnight`, `_remaining_bg_routine_firings`, `_compute_remaining` with `_build_upcoming_schedule`)
- Test: `tests/test_scheduler_prompts.py` (add schedule tests, update budget tests)

**Step 1: Write the failing tests**

Add to `tests/test_scheduler_prompts.py`:

```python
from ollim_bot.scheduling.scheduler import ScheduleEntry, _build_upcoming_schedule


def test_schedule_includes_bg_routines(monkeypatch):
    fixed_now = datetime.now(TZ).replace(hour=10, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(
        "ollim_bot.scheduling.scheduler.datetime",
        type(
            "dt",
            (datetime,),
            {"now": staticmethod(lambda tz=None: fixed_now)},
        ),
    )
    routines = [
        Routine(id="r1", message="Check tasks", cron="0 12 * * *", background=True,
                description="Midday task review"),
    ]

    entries = _build_upcoming_schedule(routines, [], current_id="other")

    assert len(entries) == 1
    assert entries[0].id == "r1"
    assert entries[0].description == "Midday task review"
    assert entries[0].tag is None  # neither [just fired] nor [this task]


def test_schedule_includes_bg_reminders(monkeypatch):
    fixed_now = datetime.now(TZ).replace(hour=10, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(
        "ollim_bot.scheduling.scheduler.datetime",
        type(
            "dt",
            (datetime,),
            {"now": staticmethod(lambda tz=None: fixed_now)},
        ),
    )
    later = fixed_now + timedelta(hours=1)
    reminders = [
        Reminder(id="rem1", message="Check if Julius started the pipeline",
                 run_at=later.isoformat(), background=True,
                 description="ML pipeline check"),
    ]

    entries = _build_upcoming_schedule([], reminders, current_id="other")

    assert len(entries) == 1
    assert entries[0].id == "rem1"


def test_schedule_excludes_foreground(monkeypatch):
    fixed_now = datetime.now(TZ).replace(hour=10, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(
        "ollim_bot.scheduling.scheduler.datetime",
        type(
            "dt",
            (datetime,),
            {"now": staticmethod(lambda tz=None: fixed_now)},
        ),
    )
    routines = [
        Routine(id="fg", message="Foreground", cron="0 12 * * *", background=False),
    ]

    entries = _build_upcoming_schedule(routines, [], current_id="other")

    assert len(entries) == 0


def test_schedule_marks_current_task(monkeypatch):
    fixed_now = datetime.now(TZ).replace(hour=10, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(
        "ollim_bot.scheduling.scheduler.datetime",
        type(
            "dt",
            (datetime,),
            {"now": staticmethod(lambda tz=None: fixed_now)},
        ),
    )
    routines = [
        Routine(id="r1", message="Task A", cron="0 12 * * *", background=True),
    ]

    entries = _build_upcoming_schedule(routines, [], current_id="r1")

    assert entries[0].tag == "this task"


def test_schedule_marks_recently_fired(monkeypatch):
    fixed_now = datetime.now(TZ).replace(hour=10, minute=15, second=0, microsecond=0)
    monkeypatch.setattr(
        "ollim_bot.scheduling.scheduler.datetime",
        type(
            "dt",
            (datetime,),
            {"now": staticmethod(lambda tz=None: fixed_now)},
        ),
    )
    routines = [
        # Fires at 10:00, which is 15 min ago (within grace window)
        Routine(id="r1", message="Task A", cron="0 10 * * *", background=True),
    ]

    entries = _build_upcoming_schedule(routines, [], current_id="other")

    assert len(entries) == 1
    assert entries[0].tag == "just fired"


def test_schedule_annotates_silent(monkeypatch):
    fixed_now = datetime.now(TZ).replace(hour=10, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(
        "ollim_bot.scheduling.scheduler.datetime",
        type(
            "dt",
            (datetime,),
            {"now": staticmethod(lambda tz=None: fixed_now)},
        ),
    )
    routines = [
        Routine(id="r1", message="Silent", cron="0 12 * * *",
                background=True, allow_ping=False),
    ]

    entries = _build_upcoming_schedule(routines, [], current_id="other")

    assert entries[0].silent is True


def test_schedule_dynamic_extends_to_min_3(monkeypatch):
    fixed_now = datetime.now(TZ).replace(hour=10, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(
        "ollim_bot.scheduling.scheduler.datetime",
        type(
            "dt",
            (datetime,),
            {"now": staticmethod(lambda tz=None: fixed_now)},
        ),
    )
    routines = [
        # Only 1 within 3h, but 3 total today
        Routine(id="r1", message="A", cron="0 12 * * *", background=True),
        Routine(id="r2", message="B", cron="0 16 * * *", background=True),
        Routine(id="r3", message="C", cron="0 20 * * *", background=True),
    ]

    entries = _build_upcoming_schedule(routines, [], current_id="other")

    assert len(entries) >= 3  # extends beyond 3h to show at least 3


def test_schedule_uses_description_over_truncated_message(monkeypatch):
    fixed_now = datetime.now(TZ).replace(hour=10, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(
        "ollim_bot.scheduling.scheduler.datetime",
        type(
            "dt",
            (datetime,),
            {"now": staticmethod(lambda tz=None: fixed_now)},
        ),
    )
    routines = [
        Routine(id="r1", message="A" * 200, cron="0 12 * * *",
                background=True, description="Short summary"),
    ]

    entries = _build_upcoming_schedule(routines, [], current_id="other")

    assert entries[0].description == "Short summary"


def test_schedule_truncates_long_message_without_description(monkeypatch):
    fixed_now = datetime.now(TZ).replace(hour=10, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(
        "ollim_bot.scheduling.scheduler.datetime",
        type(
            "dt",
            (datetime,),
            {"now": staticmethod(lambda tz=None: fixed_now)},
        ),
    )
    long_msg = "A" * 200
    routines = [
        Routine(id="r1", message=long_msg, cron="0 12 * * *", background=True),
    ]

    entries = _build_upcoming_schedule(routines, [], current_id="other")

    assert len(entries[0].description) <= 63  # 60 chars + "..."
    assert entries[0].description.endswith("...")


def test_schedule_includes_chain_info(monkeypatch):
    fixed_now = datetime.now(TZ).replace(hour=10, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(
        "ollim_bot.scheduling.scheduler.datetime",
        type(
            "dt",
            (datetime,),
            {"now": staticmethod(lambda tz=None: fixed_now)},
        ),
    )
    later = fixed_now + timedelta(hours=1)
    reminders = [
        Reminder(id="rem1", message="Check pipeline",
                 run_at=later.isoformat(), background=True,
                 chain_depth=1, max_chain=3),
    ]

    entries = _build_upcoming_schedule([], reminders, current_id="other")

    assert "chain 2/4" in entries[0].label.lower() or "2/4" in entries[0].label
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_scheduler_prompts.py::test_schedule_includes_bg_routines -v`
Expected: FAIL — `ScheduleEntry` and `_build_upcoming_schedule` don't exist.

**Step 3: Write the implementation**

In `src/ollim_bot/scheduling/scheduler.py`, replace lines 92-245 (the `_fires_before_midnight`, `_remaining_bg_routine_firings`, `_build_bg_preamble`, `_compute_remaining` functions) with:

```python
@dataclass(frozen=True, slots=True)
class ScheduleEntry:
    """One upcoming bg task in the forward schedule."""
    id: str
    fire_time: datetime
    label: str  # e.g. "Chore-time routine" or "Chain reminder (2/4)"
    description: str  # from YAML description or truncated message
    file_path: str  # relative path for agent to Read
    silent: bool = False  # allow_ping=False
    tag: str | None = None  # "this task", "just fired", or None


_GRACE_MINUTES = 15
_BASE_WINDOW_HOURS = 3
_MIN_FORWARD = 3
_MAX_WINDOW_HOURS = 12
_TRUNCATE_LEN = 60


def _routine_next_fire(routine: Routine, after: datetime) -> datetime | None:
    """Get next fire time for a routine after a given datetime."""
    parts = routine.cron.split()
    trigger = CronTrigger(
        minute=parts[0],
        hour=parts[1],
        day=parts[2],
        month=parts[3],
        day_of_week=_convert_dow(parts[4]),
    )
    return trigger.get_next_fire_time(None, after)


def _routine_prev_fire(routine: Routine, now: datetime) -> datetime | None:
    """Get most recent fire time for a routine within the grace window."""
    grace_start = now - timedelta(minutes=_GRACE_MINUTES)
    # Check if routine fires between grace_start and now
    nxt = _routine_next_fire(routine, grace_start)
    if nxt is not None and nxt <= now:
        return nxt
    return None


def _entry_description(item: Routine | Reminder) -> str:
    """Use YAML description if available, else truncate message."""
    if item.description:
        return item.description
    msg = item.message.replace("\n", " ").strip()
    if len(msg) <= _TRUNCATE_LEN:
        return msg
    return msg[:_TRUNCATE_LEN] + "..."


def _entry_label(item: Routine | Reminder) -> str:
    """Build the label prefix (e.g. 'Chore-time routine' or 'Chain reminder (2/4)')."""
    if isinstance(item, Routine):
        return item.description or "Routine"
    # Reminder
    if item.max_chain > 0:
        check = item.chain_depth + 1
        total = item.max_chain + 1
        return f"Chain reminder ({check}/{total})"
    return "Reminder"


def _entry_file_path(item: Routine | Reminder) -> str:
    """Relative file path for the agent to Read."""
    if isinstance(item, Routine):
        return f"routines/{item.id}.md"
    return f"reminders/{item.id}.md"


def _build_upcoming_schedule(
    routines: list[Routine],
    reminders: list[Reminder],
    *,
    current_id: str,
) -> list[ScheduleEntry]:
    """Build the forward schedule for the bg preamble."""
    now = datetime.now(TZ)
    base_cutoff = now + timedelta(hours=_BASE_WINDOW_HOURS)
    max_cutoff = now + timedelta(hours=_MAX_WINDOW_HOURS)
    grace_start = now - timedelta(minutes=_GRACE_MINUTES)

    candidates: list[tuple[datetime, Routine | Reminder]] = []

    for r in routines:
        if not r.background:
            continue
        # Recently fired (within grace window)
        prev = _routine_prev_fire(r, now)
        if prev is not None:
            candidates.append((prev, r))
        # Next fire up to max_cutoff
        nxt = _routine_next_fire(r, now)
        if nxt is not None and nxt <= max_cutoff:
            candidates.append((nxt, r))

    for rem in reminders:
        if not rem.background:
            continue
        fire = datetime.fromisoformat(rem.run_at)
        if grace_start <= fire <= max_cutoff:
            candidates.append((fire, rem))

    # Sort by fire time
    candidates.sort(key=lambda x: x[0])

    # Apply dynamic window: all within base_cutoff, extend for min forward count
    forward = [(t, item) for t, item in candidates if t > now]
    recent = [(t, item) for t, item in candidates if t <= now]

    if len(forward) < _MIN_FORWARD:
        selected_forward = forward  # take all we have
    else:
        # Take all within base_cutoff
        in_window = [(t, item) for t, item in forward if t <= base_cutoff]
        if len(in_window) >= _MIN_FORWARD:
            selected_forward = in_window
        else:
            # Extend to get at least MIN_FORWARD
            selected_forward = forward[:_MIN_FORWARD]

    selected = recent + selected_forward

    entries: list[ScheduleEntry] = []
    for fire_time, item in selected:
        if fire_time <= now and item.id != current_id:
            tag = "just fired"
        elif item.id == current_id:
            tag = "this task"
        else:
            tag = None
        entries.append(ScheduleEntry(
            id=item.id,
            fire_time=fire_time,
            label=_entry_label(item),
            description=_entry_description(item),
            file_path=_entry_file_path(item),
            silent=not item.allow_ping,
            tag=tag,
        ))

    return entries
```

Also add to the top imports:

```python
from dataclasses import dataclass
from ollim_bot.scheduling.reminders import REMINDERS_DIR
from ollim_bot.scheduling.routines import ROUTINES_DIR
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_scheduler_prompts.py -k "schedule" -v`
Expected: All new schedule tests PASS.

**Step 5: Commit**

```bash
git add src/ollim_bot/scheduling/scheduler.py tests/test_scheduler_prompts.py
git commit -m "feat: add forward schedule builder for bg preamble"
```

---

### Task 3: Update `_build_bg_preamble()` and prompt builders

**Files:**
- Modify: `src/ollim_bot/scheduling/scheduler.py:119-260` (rewrite `_build_bg_preamble`, update `_build_routine_prompt`, `_build_reminder_prompt`)
- Modify: `tests/test_scheduler_prompts.py` (update existing budget/preamble tests)

**Step 1: Update the existing preamble tests**

Update existing tests in `tests/test_scheduler_prompts.py` that reference old budget format. Key changes:
- `test_bg_routine_prompt_includes_budget`: assert `"available"` instead of `"remaining today"`
- `test_bg_reminder_prompt_includes_budget`: same
- `test_bg_preamble_zero_budget_says_do_not_ping`: remove this test (no longer applicable — budget refills)
- `test_bg_preamble_shows_remaining_tasks`: replace with schedule-based assertion
- Add: `test_bg_preamble_includes_schedule` — verify schedule lines appear in preamble
- Add: `test_bg_preamble_shows_refills_before_last` — verify the `~N refills` line

**Step 2: Run tests to verify failures**

Run: `uv run pytest tests/test_scheduler_prompts.py -v`
Expected: Old budget-format tests fail.

**Step 3: Rewrite `_build_bg_preamble` and update callers**

New signature:

```python
def _build_bg_preamble(
    schedule: list[ScheduleEntry],
    *,
    busy: bool = False,
    bg_config: BgForkConfig | None = None,
) -> str:
```

Replace the budget section with:

```python
    if config.allow_ping:
        budget_status = ping_budget.get_status()
        # Schedule
        if schedule:
            # Determine window label
            last_forward = [e for e in schedule if e.tag != "just fired"]
            if last_forward:
                hours = (last_forward[-1].fire_time - now).total_seconds() / 3600
                window_label = f"next {max(1, round(hours))}h"
            else:
                window_label = "recent"
            schedule_lines = [f"Upcoming bg tasks ({window_label}):"]
            for entry in schedule:
                time_str = entry.fire_time.strftime("%-I:%M %p")
                silent = " (silent)" if entry.silent else ""
                tag = f" [{entry.tag}]" if entry.tag else ""
                schedule_lines.append(
                    f'- {time_str}: {entry.label}{silent} — '
                    f'"{entry.description}" ({entry.file_path}){tag}'
                )
            # Refills before last forward task
            if last_forward:
                minutes_to_last = (last_forward[-1].fire_time - now).total_seconds() / 60
                refill_rate = ping_budget.load().refill_rate_minutes
                refills = int(minutes_to_last / refill_rate)
                if refills > 0:
                    schedule_lines.append(f"~{refills} refill{'s' if refills != 1 else ''} before last task.")
            schedule_section = "\n".join(schedule_lines) + "\n"
        else:
            schedule_section = "No more bg tasks today.\n"

        # ... regret line and critical line unchanged ...

        budget_section = (
            f"Ping budget: {budget_status}.\n"
            f"{schedule_section}"
            f"Send at most 1 ping or embed per bg session.\n"
            f"{regret_line}"
            f"critical=True bypasses the budget — reserve for things the user would be devastated to miss.\n\n"
        )
```

Update `_build_routine_prompt` and `_build_reminder_prompt` to build schedule and pass it:

```python
def _build_routine_prompt(
    routine: Routine,
    *,
    reminders: list[Reminder],
    routines: list[Routine],
    busy: bool = False,
    bg_config: BgForkConfig | None = None,
) -> str:
    if routine.background:
        schedule = _build_upcoming_schedule(routines, reminders, current_id=routine.id)
        preamble = _build_bg_preamble(schedule, busy=busy, bg_config=bg_config)
        return f"[routine-bg:{routine.id}] {preamble}{routine.message}"
    return f"[routine:{routine.id}] {routine.message}"
```

Same pattern for `_build_reminder_prompt`.

**Step 4: Run all scheduler prompt tests**

Run: `uv run pytest tests/test_scheduler_prompts.py -v`
Expected: All PASS.

**Step 5: Commit**

```bash
git add src/ollim_bot/scheduling/scheduler.py tests/test_scheduler_prompts.py
git commit -m "feat: inject forward schedule into bg preamble"
```

---

### Task 4: Update system prompt and `/ping-budget` command

**Files:**
- Modify: `src/ollim_bot/prompts.py:238-244` (budget description in SYSTEM_PROMPT)
- Modify: `src/ollim_bot/bot.py:368-378` (slash command handler)

**Step 1: Update the system prompt**

In `src/ollim_bot/prompts.py`, replace lines 238-244:

```python
You have a ping budget that refills over time (shown in the bg preamble \
when it fires). Each `ping_user` or `discord_embed` call costs 1 ping — \
send at most 1 per bg session. The preamble shows your current budget, \
upcoming tasks, and refill timing. Use the schedule to decide whether \
this task deserves a ping or whether a higher-priority task fires soon.
```

**Step 2: Update `/ping-budget` slash command**

In `src/ollim_bot/bot.py`, update the handler to support capacity + refill_rate:

```python
    @bot.tree.command(name="ping-budget", description="View or set ping budget")
    @discord.app_commands.describe(
        capacity="Max pings (omit to view current)",
        refill_rate="Minutes per refill (default 90)",
    )
    async def slash_ping_budget(
        interaction: discord.Interaction,
        capacity: int | None = None,
        refill_rate: int | None = None,
    ):
        if capacity is not None:
            ping_budget.set_capacity(capacity)
        if refill_rate is not None:
            ping_budget.set_refill_rate(refill_rate)
        if capacity is not None or refill_rate is not None:
            status = ping_budget.get_status()
            await interaction.response.send_message(f"ping budget updated: {status}.")
        else:
            status = ping_budget.get_full_status()
            await interaction.response.send_message(f"ping budget: {status}.")
```

**Step 3: Verify no import errors**

Run: `uv run python -c "from ollim_bot.prompts import SYSTEM_PROMPT; print('OK')"`
Expected: `OK`

**Step 4: Run full test suite**

Run: `uv run pytest -v`
Expected: All PASS. Some existing tests may need minor updates if they asserted on old `get_status()` format or old preamble text — fix any that fail.

**Step 5: Commit**

```bash
git add src/ollim_bot/prompts.py src/ollim_bot/bot.py
git commit -m "feat: update system prompt and /ping-budget for refill bucket"
```

---

### Task 5: Remove dead code and update CLAUDE.md

**Files:**
- Modify: `src/ollim_bot/ping_budget.py` (remove `remaining_bg_reminders` if still present)
- Modify: `src/ollim_bot/scheduling/scheduler.py` (remove dead functions: `_fires_before_midnight`, `_remaining_bg_routine_firings`, `_compute_remaining`)
- Modify: `CLAUDE.md` (update ping budget section)

**Step 1: Remove dead functions**

Delete `_fires_before_midnight`, `_remaining_bg_routine_firings`, `_compute_remaining` from `scheduler.py` if not already removed in Task 3. Delete `remaining_bg_reminders` from `ping_budget.py`. Remove their imports from `test_scheduler_prompts.py` and `test_ping_budget.py`.

**Step 2: Update CLAUDE.md**

Replace the `## Ping budget` section with:

```markdown
## Ping budget
- `~/.ollim-bot/ping_budget.json` — ephemeral state (no git commit)
- Refill-on-read bucket: capacity (default 5), refills 1 per 90 min, capped at capacity
- Lazy refill: `load()` computes accumulated pings from elapsed time since `last_refill`
- Daily counters (`daily_used`, `critical_used`) reset at midnight
- Scope: bg forks only — main session and interactive fork embeds are user-requested, never counted
- Enforcement: `agent_tools.py` checks budget before `ping_user`/`discord_embed` in bg forks
- Critical bypass: `critical=True` parameter on both tools; tracked but not capped
- Over budget: tool returns error to agent, user not notified
- Forward schedule: bg preamble shows upcoming bg tasks with times, descriptions, and file paths
- Schedule window: `[now-15min, now+3h]` or next 3 forward tasks, whichever covers more
- Agent awareness: budget status + schedule + refill timing injected into BG_PREAMBLE at job-fire time
- `/ping-budget [capacity] [refill_rate]` — view or configure
```

**Step 3: Run full test suite**

Run: `uv run pytest -v`
Expected: All PASS, no import errors from removed functions.

**Step 4: Commit**

```bash
git add src/ollim_bot/ping_budget.py src/ollim_bot/scheduling/scheduler.py tests/ CLAUDE.md
git commit -m "chore: remove dead budget code, update CLAUDE.md"
```

---

### Task 6: Final verification

**Step 1: Run the full test suite one more time**

Run: `uv run pytest -v`
Expected: All PASS.

**Step 2: Verify type checking**

Run: `uv run python -c "from ollim_bot.scheduling.scheduler import _build_bg_preamble, _build_upcoming_schedule, ScheduleEntry; print('imports OK')"`

**Step 3: Verify no circular imports**

Run: `uv run python -c "import ollim_bot.bot; print('OK')"`

**Step 4: Check file sizes**

Run: `wc -l src/ollim_bot/ping_budget.py src/ollim_bot/scheduling/scheduler.py`
Expected: Both under ~400 lines. If `scheduler.py` exceeds, the schedule builder can be extracted to a separate module in a follow-up.
