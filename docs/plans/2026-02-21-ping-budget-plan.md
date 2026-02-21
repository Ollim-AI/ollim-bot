# Ping Budget Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Limit proactive (bg fork) pings per day with agent-classified critical bypass, configurable via `/ping-budget`.

**Architecture:** New `ping_budget.py` domain module owns state (JSON file) and budget logic. `agent_tools.py` checks budget before sending bg pings. `scheduler.py` injects budget status + remaining bg task count into BG_PREAMBLE at job-fire time. `/ping-budget` slash command in `bot.py` for view/set.

**Tech Stack:** Python dataclasses, JSON file I/O, APScheduler job introspection, discord.py slash commands.

---

### Task 1: `ping_budget.py` — data model and persistence

**Files:**
- Create: `src/ollim_bot/ping_budget.py`
- Test: `tests/test_ping_budget.py`

**Step 1: Write the failing tests**

In `tests/test_ping_budget.py`:

```python
"""Tests for ping_budget.py — budget state, try_use, critical tracking, reset."""

from datetime import date

from ollim_bot.ping_budget import BudgetState, load, save, try_use, record_critical, set_limit


def test_load_returns_defaults_when_no_file(data_dir):
    state = load()

    assert state.daily_limit == 10
    assert state.used == 0
    assert state.critical_used == 0
    assert state.last_reset == date.today().isoformat()


def test_save_and_load_roundtrip(data_dir):
    state = BudgetState(daily_limit=5, used=2, critical_used=1, last_reset="2026-02-21")
    save(state)

    loaded = load()

    assert loaded == state


def test_load_resets_on_stale_date(data_dir):
    state = BudgetState(daily_limit=8, used=6, critical_used=2, last_reset="2026-01-01")
    save(state)

    loaded = load()

    assert loaded.used == 0
    assert loaded.critical_used == 0
    assert loaded.daily_limit == 8
    assert loaded.last_reset == date.today().isoformat()


def test_try_use_decrements(data_dir):
    state = BudgetState(daily_limit=3, used=0, critical_used=0, last_reset=date.today().isoformat())
    save(state)

    result = try_use()

    assert result is True
    assert load().used == 1


def test_try_use_returns_false_when_exhausted(data_dir):
    state = BudgetState(daily_limit=2, used=2, critical_used=0, last_reset=date.today().isoformat())
    save(state)

    result = try_use()

    assert result is False
    assert load().used == 2


def test_record_critical_increments(data_dir):
    state = BudgetState(daily_limit=2, used=2, critical_used=0, last_reset=date.today().isoformat())
    save(state)

    record_critical()

    assert load().critical_used == 1
    assert load().used == 2


def test_set_limit_updates_and_persists(data_dir):
    state = BudgetState(daily_limit=10, used=3, critical_used=1, last_reset=date.today().isoformat())
    save(state)

    set_limit(5)

    assert load().daily_limit == 5
    assert load().used == 3
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ping_budget.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ollim_bot.ping_budget'`

**Step 3: Write the implementation**

In `src/ollim_bot/ping_budget.py`:

```python
"""Daily ping budget for background fork notifications."""

import json
import os
import tempfile
from dataclasses import dataclass, asdict
from datetime import date
from pathlib import Path

from ollim_bot.storage import DATA_DIR

BUDGET_FILE = DATA_DIR / "ping_budget.json"
_DEFAULT_LIMIT = 10


@dataclass(frozen=True, slots=True)
class BudgetState:
    daily_limit: int
    used: int
    critical_used: int
    last_reset: str  # ISO date


def load() -> BudgetState:
    """Load budget state, auto-resetting if the date has changed."""
    if not BUDGET_FILE.exists():
        state = BudgetState(
            daily_limit=_DEFAULT_LIMIT,
            used=0,
            critical_used=0,
            last_reset=date.today().isoformat(),
        )
        save(state)
        return state

    with BUDGET_FILE.open() as f:
        data = json.load(f)

    state = BudgetState(**data)
    if state.last_reset != date.today().isoformat():
        state = BudgetState(
            daily_limit=state.daily_limit,
            used=0,
            critical_used=0,
            last_reset=date.today().isoformat(),
        )
        save(state)
    return state


def save(state: BudgetState) -> None:
    """Atomic write (tempfile + rename), no git commit."""
    BUDGET_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=BUDGET_FILE.parent, suffix=".tmp")
    os.write(fd, json.dumps(asdict(state)).encode())
    os.close(fd)
    os.replace(tmp, BUDGET_FILE)


def try_use() -> bool:
    """Decrement budget if remaining > 0. Returns False if exhausted."""
    state = load()
    remaining = state.daily_limit - state.used
    if remaining <= 0:
        return False
    save(BudgetState(
        daily_limit=state.daily_limit,
        used=state.used + 1,
        critical_used=state.critical_used,
        last_reset=state.last_reset,
    ))
    return True


def record_critical() -> None:
    """Track a critical ping (no cap enforced)."""
    state = load()
    save(BudgetState(
        daily_limit=state.daily_limit,
        used=state.used,
        critical_used=state.critical_used + 1,
        last_reset=state.last_reset,
    ))


def get_status() -> str:
    """Formatted budget status for prompt injection or slash command."""
    state = load()
    remaining = state.daily_limit - state.used
    parts = [f"{remaining}/{state.daily_limit} remaining today"]
    if state.used > 0:
        parts.append(f"{state.used} used")
    if state.critical_used > 0:
        parts.append(f"{state.critical_used} critical")
    return ", ".join(parts)


def set_limit(limit: int) -> None:
    """Update daily limit (persists immediately)."""
    state = load()
    save(BudgetState(
        daily_limit=limit,
        used=state.used,
        critical_used=state.critical_used,
        last_reset=state.last_reset,
    ))
```

**Step 4: Update `conftest.py` to redirect `BUDGET_FILE`**

In `tests/conftest.py`, add to the `data_dir` fixture:

```python
import ollim_bot.ping_budget as ping_budget_mod
monkeypatch.setattr(ping_budget_mod, "BUDGET_FILE", tmp_path / "ping_budget.json")
```

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_ping_budget.py -v`
Expected: all 7 tests PASS

**Step 6: Commit**

```bash
git add src/ollim_bot/ping_budget.py tests/test_ping_budget.py tests/conftest.py
git commit -m "feat: add ping_budget module with daily budget state and persistence"
```

---

### Task 2: `get_status` formatting and `remaining_today` helper

**Files:**
- Modify: `src/ollim_bot/ping_budget.py`
- Test: `tests/test_ping_budget.py` (append)

**Step 1: Write the failing tests**

Append to `tests/test_ping_budget.py`:

```python
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ollim_bot.ping_budget import get_status, remaining_today
from ollim_bot.scheduling.reminders import Reminder
from ollim_bot.scheduling.routines import Routine

TZ = ZoneInfo("America/Los_Angeles")


def test_get_status_fresh(data_dir):
    status = get_status()

    assert "10/10 remaining today" in status


def test_get_status_after_use(data_dir):
    state = BudgetState(daily_limit=10, used=3, critical_used=1, last_reset=date.today().isoformat())
    save(state)

    status = get_status()

    assert "7/10 remaining today" in status
    assert "3 used" in status
    assert "1 critical" in status


def test_remaining_today_counts_bg_only(data_dir):
    now = datetime.now(TZ)
    later = now + timedelta(hours=2)
    tomorrow = now + timedelta(days=1)

    reminders = [
        Reminder(id="r1", message="bg today", run_at=later.isoformat(), background=True),
        Reminder(id="r2", message="fg today", run_at=later.isoformat(), background=False),
        Reminder(id="r3", message="bg tomorrow", run_at=tomorrow.isoformat(), background=True),
    ]
    routines = [
        Routine(id="t1", message="bg routine", cron="0 * * * *", background=True),
        Routine(id="t2", message="fg routine", cron="0 * * * *", background=False),
    ]

    bg_reminders, bg_routines = remaining_today(reminders, routines)

    assert bg_reminders == 1  # only r1
    assert bg_routines == 1   # only t1 (count of bg routines, not firings)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ping_budget.py::test_remaining_today_counts_bg_only -v`
Expected: FAIL — `cannot import name 'remaining_today'`

**Step 3: Write the implementation**

Add to `src/ollim_bot/ping_budget.py`:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

_TZ = ZoneInfo("America/Los_Angeles")


def remaining_today(
    reminders: list,
    routines: list,
) -> tuple[int, int]:
    """Count bg reminders firing before midnight and bg routines (total count).

    Returns (bg_reminders_remaining, bg_routines_count).
    Routines are recurring so we return the count of bg routines, not firings.
    """
    now = datetime.now(_TZ)
    midnight = now.replace(hour=23, minute=59, second=59)

    bg_reminders = sum(
        1 for r in reminders
        if r.background and datetime.fromisoformat(r.run_at) <= midnight
    )
    bg_routines = sum(1 for r in routines if r.background)
    return bg_reminders, bg_routines
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ping_budget.py -v`
Expected: all 10 tests PASS

**Step 5: Commit**

```bash
git add src/ollim_bot/ping_budget.py tests/test_ping_budget.py
git commit -m "feat: add get_status formatting and remaining_today helper"
```

---

### Task 3: Enforce budget in `agent_tools.py`

**Files:**
- Modify: `src/ollim_bot/agent_tools.py:100-192` (discord_embed + ping_user tools)
- Test: `tests/test_agent_tools.py` (append)

**Step 1: Write the failing tests**

Append to `tests/test_agent_tools.py`:

```python
from ollim_bot import ping_budget


# --- ping budget enforcement ---


def test_ping_user_blocked_when_budget_exhausted(data_dir):
    from datetime import date

    ch = InMemoryChannel()
    set_fork_channel(ch)
    set_in_fork(True)
    ping_budget.save(ping_budget.BudgetState(
        daily_limit=2, used=2, critical_used=0, last_reset=date.today().isoformat(),
    ))

    result = _run(_ping({"message": "hello"}))

    assert "Budget exhausted" in result["content"][0]["text"]
    assert len(ch.messages) == 0
    set_in_fork(False)


def test_ping_user_critical_bypasses_budget(data_dir):
    from datetime import date

    ch = InMemoryChannel()
    set_fork_channel(ch)
    set_in_fork(True)
    ping_budget.save(ping_budget.BudgetState(
        daily_limit=2, used=2, critical_used=0, last_reset=date.today().isoformat(),
    ))

    result = _run(_ping({"message": "urgent!", "critical": True}))

    assert result["content"][0]["text"] == "Message sent."
    assert ping_budget.load().critical_used == 1
    set_in_fork(False)


def test_embed_blocked_when_budget_exhausted_in_bg(data_dir):
    from datetime import date

    ch = InMemoryChannel()
    set_fork_channel(ch)
    set_in_fork(True)
    ping_budget.save(ping_budget.BudgetState(
        daily_limit=1, used=1, critical_used=0, last_reset=date.today().isoformat(),
    ))

    result = _run(_embed({"title": "Tasks"}))

    assert "Budget exhausted" in result["content"][0]["text"]
    assert len(ch.messages) == 0
    set_in_fork(False)


def test_embed_not_blocked_on_main_session(data_dir):
    from datetime import date

    ch = InMemoryChannel()
    set_fork_channel(None)
    set_channel(ch)
    set_in_fork(False)
    set_interactive_fork(False)
    ping_budget.save(ping_budget.BudgetState(
        daily_limit=1, used=1, critical_used=0, last_reset=date.today().isoformat(),
    ))

    result = _run(_embed({"title": "Tasks"}))

    assert result["content"][0]["text"] == "Embed sent."
    assert len(ch.messages) == 1
    set_channel(None)


def test_ping_user_decrements_budget(data_dir):
    from datetime import date

    ch = InMemoryChannel()
    set_fork_channel(ch)
    set_in_fork(True)
    ping_budget.save(ping_budget.BudgetState(
        daily_limit=5, used=0, critical_used=0, last_reset=date.today().isoformat(),
    ))

    _run(_ping({"message": "test"}))

    assert ping_budget.load().used == 1
    set_in_fork(False)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_agent_tools.py::test_ping_user_blocked_when_budget_exhausted -v`
Expected: FAIL — ping goes through (no budget check yet)

**Step 3: Implement the budget check**

Modify `src/ollim_bot/agent_tools.py`:

1. Add import at top:
```python
from ollim_bot import ping_budget
```

2. Add `critical` to `ping_user` tool schema properties:
```python
"critical": {
    "type": "boolean",
    "description": "Set true only for genuinely urgent/time-sensitive items",
},
```

3. Add budget check in `ping_user` handler, after the `_source() != "bg"` check and before the channel check:
```python
critical = args.get("critical", False)
if not critical and not ping_budget.try_use():
    return {
        "content": [
            {
                "type": "text",
                "text": "Budget exhausted (0 remaining). Use critical=True "
                "only for genuinely urgent items.",
            }
        ]
    }
if critical:
    ping_budget.record_critical()
```

4. Add `critical` to `discord_embed` tool schema properties (same as ping_user).

5. Add budget check in `discord_embed` handler, after the channel check:
```python
if _source() == "bg":
    critical = args.get("critical", False)
    if not critical and not ping_budget.try_use():
        return {
            "content": [
                {
                    "type": "text",
                    "text": "Budget exhausted (0 remaining). Use critical=True "
                    "only for genuinely urgent items.",
                }
            ]
        }
    if critical:
        ping_budget.record_critical()
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_agent_tools.py -v`
Expected: all tests PASS (both new and existing)

**Step 5: Commit**

```bash
git add src/ollim_bot/agent_tools.py tests/test_agent_tools.py
git commit -m "feat: enforce ping budget in bg fork ping_user and discord_embed"
```

---

### Task 4: Inject budget status into BG_PREAMBLE

**Files:**
- Modify: `src/ollim_bot/scheduling/scheduler.py:50-58,101-104,107-138,141-176,179-230`
- Test: `tests/test_scheduler_prompts.py` (append)

**Step 1: Write the failing tests**

Append to `tests/test_scheduler_prompts.py`:

```python
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from ollim_bot import ping_budget
from ollim_bot.scheduling.scheduler import _build_routine_prompt, _build_reminder_prompt

TZ = ZoneInfo("America/Los_Angeles")


def test_bg_routine_prompt_includes_budget(data_dir):
    ping_budget.save(ping_budget.BudgetState(
        daily_limit=10, used=3, critical_used=1, last_reset=date.today().isoformat(),
    ))
    routine = Routine(id="abc", message="Check tasks", cron="0 8 * * *", background=True)

    prompt = _build_routine_prompt(routine, reminders=[], routines=[routine])

    assert "7/10 remaining today" in prompt
    assert "1 bg routine" in prompt


def test_bg_reminder_prompt_includes_budget(data_dir):
    now = datetime.now(TZ)
    ping_budget.save(ping_budget.BudgetState(
        daily_limit=10, used=5, critical_used=0, last_reset=date.today().isoformat(),
    ))
    reminder = Reminder(
        id="r1", message="Check email", run_at=now.isoformat(), background=True,
    )

    prompt = _build_reminder_prompt(reminder, reminders=[reminder], routines=[])

    assert "5/10 remaining today" in prompt


def test_fg_routine_prompt_unchanged(data_dir):
    routine = Routine(id="abc", message="Morning briefing", cron="0 8 * * *")

    prompt = _build_routine_prompt(routine, reminders=[], routines=[])

    assert prompt == "[routine:abc] Morning briefing"
    assert "budget" not in prompt.lower()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_scheduler_prompts.py::test_bg_routine_prompt_includes_budget -v`
Expected: FAIL — `_build_routine_prompt() got unexpected keyword argument 'reminders'`

**Step 3: Implement preamble injection**

Modify `src/ollim_bot/scheduling/scheduler.py`:

1. Add imports:
```python
from ollim_bot import ping_budget
from ollim_bot.scheduling.reminders import Reminder
```
(Note: `Reminder` is already imported — just need `ping_budget`.)

2. Add a `_build_bg_preamble` function that builds the dynamic preamble:

```python
def _build_bg_preamble(
    reminders: list[Reminder], routines: list[Routine]
) -> str:
    """Build BG_PREAMBLE with budget status and remaining task count."""
    bg_reminders, bg_routines = ping_budget.remaining_today(reminders, routines)
    budget_status = ping_budget.get_status()

    remaining_parts: list[str] = []
    if bg_reminders > 0:
        remaining_parts.append(f"{bg_reminders} bg reminder{'s' if bg_reminders != 1 else ''}")
    if bg_routines > 0:
        remaining_parts.append(f"{bg_routines} bg routine{'s' if bg_routines != 1 else ''}")
    remaining_line = (
        f"Remaining today: {', '.join(remaining_parts)} before budget reset.\n"
        if remaining_parts
        else ""
    )

    return (
        f"{_BG_PREAMBLE}"
        f"Ping budget: {budget_status}.\n"
        f"{remaining_line}"
        "Plan pings carefully -- you may not need to ping for every task. "
        "Use report_updates for non-urgent summaries. "
        "Set critical=True only for time-sensitive items (event in <30min, urgent message).\n\n"
    )
```

3. Update `_build_routine_prompt` signature and body:

```python
def _build_routine_prompt(
    routine: Routine,
    *,
    reminders: list[Reminder],
    routines: list[Routine],
) -> str:
    if routine.background:
        preamble = _build_bg_preamble(reminders, routines)
        return f"[routine-bg:{routine.id}] {preamble}{routine.message}"
    return f"[routine:{routine.id}] {routine.message}"
```

4. Update `_build_reminder_prompt` signature similarly:

```python
def _build_reminder_prompt(
    reminder: Reminder,
    *,
    reminders: list[Reminder],
    routines: list[Routine],
) -> str:
    # ... same body but replace _BG_PREAMBLE usage with _build_bg_preamble(reminders, routines)
```

In the body, replace `parts.append(_BG_PREAMBLE.rstrip())` with `parts.append(_build_bg_preamble(reminders, routines).rstrip())`.

5. Update callers in `_register_routine` and `_register_reminder` — these build the prompt at registration time, but we need the prompt to be dynamic (computed at fire time). Move prompt building into the `_fire`/`fire_oneshot` closures:

In `_register_routine`, change:
```python
# Before (prompt built at registration):
prompt = _build_routine_prompt(routine)
async def _fire() -> None:
    ...

# After (prompt built at fire time):
async def _fire() -> None:
    prompt = _build_routine_prompt(
        routine,
        reminders=list_reminders(),
        routines=list_routines(),
    )
    ...
```

Same for `_register_reminder` — move `prompt = _build_reminder_prompt(reminder)` into the `fire_oneshot` closure body (before the `try` block), and pass the new args.

6. Update existing tests in `test_scheduler_prompts.py` to pass the new required kwargs:

All existing calls to `_build_routine_prompt(routine)` become `_build_routine_prompt(routine, reminders=[], routines=[])`.
All existing calls to `_build_reminder_prompt(reminder)` become `_build_reminder_prompt(reminder, reminders=[], routines=[])`.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_scheduler_prompts.py -v`
Expected: all tests PASS

**Step 5: Run the full test suite**

Run: `uv run pytest -v`
Expected: all tests PASS

**Step 6: Commit**

```bash
git add src/ollim_bot/scheduling/scheduler.py tests/test_scheduler_prompts.py
git commit -m "feat: inject ping budget status and remaining task count into BG_PREAMBLE"
```

---

### Task 5: `/ping-budget` slash command

**Files:**
- Modify: `src/ollim_bot/bot.py:302-323` (after `/permissions`, before `return bot`)

**Step 1: Add the slash command**

In `src/ollim_bot/bot.py`, add import:
```python
from ollim_bot import ping_budget
```

Add the slash command before `return bot` (around line 324):

```python
@bot.tree.command(name="ping-budget", description="View or set daily ping budget")
@discord.app_commands.describe(limit="New daily limit (omit to view current)")
async def slash_ping_budget(
    interaction: discord.Interaction, limit: int | None = None
):
    if limit is not None:
        ping_budget.set_limit(limit)
        await interaction.response.send_message(
            f"ping budget set to {limit}/day."
        )
    else:
        status = ping_budget.get_status()
        await interaction.response.send_message(f"ping budget: {status}.")
```

**Step 2: Run the full test suite**

Run: `uv run pytest -v`
Expected: all tests PASS (no new tests needed — slash commands are tested via integration)

**Step 3: Commit**

```bash
git add src/ollim_bot/bot.py
git commit -m "feat: add /ping-budget slash command to view and set daily limit"
```

---

### Task 6: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Add ping budget to architecture list**

After the `inquiries.py` line, add:
```
- `ping_budget.py` -- Daily ping budget for bg fork notifications (state, enforcement, status formatting)
```

**Step 2: Add ping budget section**

After the "## Discord embeds & buttons" section, add:

```markdown
## Ping budget
- `~/.ollim-bot/ping_budget.json` — ephemeral state (no git commit): `daily_limit`, `used`, `critical_used`, `last_reset`
- Default 10/day, resets at midnight; configurable via `/ping-budget [limit]`
- Scope: bg forks only — main session and interactive fork embeds are user-requested, never counted
- Enforcement: `agent_tools.py` checks budget before `ping_user`/`discord_embed` in bg forks
- Critical bypass: `critical=True` parameter on both tools; tracked but not capped
- Over budget: silent drop — tool returns error to agent, user not notified
- Agent awareness: budget status + remaining bg tasks injected into BG_PREAMBLE at job-fire time
- `remaining_today(reminders, routines)` counts bg reminders before midnight + bg routine count
```

**Step 3: Add `/ping-budget` to slash commands list**

In the Discord slash commands section, add:
```
- `/ping-budget [limit]` -- view or set daily ping budget (bg fork pings only)
```

**Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add ping budget to CLAUDE.md architecture and slash commands"
```

---

### Task 7: Final verification

**Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: all tests PASS

**Step 2: Check file line counts**

Run: `wc -l src/ollim_bot/ping_budget.py src/ollim_bot/agent_tools.py src/ollim_bot/scheduling/scheduler.py`
Expected: all under 400 lines

**Step 3: Verify no circular imports**

Run: `uv run python -c "import ollim_bot.ping_budget; import ollim_bot.agent_tools; import ollim_bot.scheduling.scheduler; print('OK')"`
Expected: `OK`
