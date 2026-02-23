# Ping Budget Refill Design

## Problem

The current ping budget is a flat daily counter (default 10) that resets at
midnight. Bot-debugger analysis showed budget hitting 0 by early evening,
blocking all health routines (wind-down, screens-off, bedtime coach, midnight
check) -- the routines that arguably matter most.

Two root causes:
1. **Evening starvation** -- daytime tasks consume the budget before
   high-priority evening health routines fire.
2. **Blunt instrument** -- a single daily number can't adapt to how the day
   unfolds.

## Design

### 1. Refill bucket (replaces flat counter)

Replace the daily counter with a refill-on-read bucket:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `capacity` | int | 5 | Max pings |
| `available` | float | 5.0 | Current available pings |
| `refill_rate_minutes` | int | 90 | Minutes per ping refill |
| `last_refill` | ISO datetime | now | Timestamp of last refill computation |
| `critical_used` | int | 0 | Daily critical count (resets at midnight) |
| `critical_reset_date` | ISO date | today | Date of last critical counter reset |
| `daily_used` | int | 0 | Total pings consumed today (observability) |
| `daily_used_reset` | ISO date | today | Date of last daily_used reset |

**Refill logic:** On every `load()`, compute elapsed since `last_refill`, add
`elapsed / refill_rate` pings (capped at `capacity`), update `last_refill`.
Lazy evaluation -- no background timer.

**Consumption:** `try_use()` refills first, checks `available >= 1.0`,
decrements by 1.

**Daily throughput:** Cap 5, refill 1/90min = ~16 max/day. Realistic: 10-14.

### 2. Forward schedule injection

Each bg fork's preamble includes upcoming bg tasks so the agent can make
informed budget allocation decisions.

**Window:** `[now - 15min, now + 3h]`, OR the next 3 forward tasks, whichever
covers more.

**Schedule line format:**
```
- 6:00 PM: Chore-time routine -- "Review open tasks and nudge on overdue items" (routines/chore-time.md)
- 6:30 PM: Chain reminder (2/4) -- "Check if Julius started the ML pipeli..." (reminders/ml-pipeline.md)
- 7:30 PM: Workout nudge (silent) -- "Check workout status" (routines/workout-nudge.md)
```

- Use `description` from YAML frontmatter when available
- Fall back to first ~60 chars of message body + `...` to indicate truncation
- Always append file path so agent can `Read` the full prompt if needed
- `allow_ping: false` tasks annotated `(silent)`
- Recently-fired tasks (within 15min) annotated `[just fired]`
- Currently-firing task annotated `[this task]`
- Min-3-tasks rule applies to forward portion only

**Refills-before-last:** `floor((last_task_time - now) / refill_rate_minutes)`.
Shown as `~N refills before last task.`

### 3. Revised preamble

Budget block changes from:
```
Ping budget: 6/10 used today (4 remaining).
Still to fire today: 2 bg reminders, 1 bg routine.
Send at most 1 ping or embed per bg session -- multiple routines share the daily budget.
If budget is 0, do not attempt to ping.
```

To:
```
Ping budget: 3/5 available (refills 1 every 90 min, next in 47 min).
Upcoming bg tasks (next 3h):
- 5:58 PM: Chore-time routine -- "Review open tasks and nudge on overdue" (routines/chore-time.md) [just fired]
- 6:00 PM: Chain reminder (2/4) -- "Check if Julius started the ML pipeli..." (reminders/ml-pipeline.md) [this task]
- 7:30 PM: Workout nudge (silent) -- "Check workout status" (routines/workout-nudge.md)
~1 refill before last task.
Send at most 1 ping or embed per bg session.
```

- Next refill time shown only when below capacity
- "If budget is 0, do not attempt to ping" removed (tool enforces; with refills,
  0 is temporary)
- "Still to fire today" replaced by detailed schedule
- Regret-based guidance and critical bypass lines unchanged

### 4. Interface changes

**`/ping-budget` slash command:**
- `/ping-budget` -- shows status + daily totals
- `/ping-budget 5` -- set capacity (keep current refill rate)
- `/ping-budget 5 60` -- set capacity and refill rate

**System prompt (`prompts.py`):** Update budget description to reference
refill-over-time mechanism and schedule visibility. Volatile specifics stay
in the preamble (separate stable from volatile).

### 5. Migration

`load()` detects old format (`daily_limit` key present, `capacity` absent),
creates fresh state with defaults. Ephemeral state -- losing a partial day's
count is fine.

### 6. Edge cases

- **Bot restart:** `last_refill` persisted, refills accumulate during downtime
  (capped at capacity).
- **Simultaneous bg forks:** Same race as current system (two forks read same
  `available`). Worst case: 1 extra ping. Not worth file locking.
- **Capacity change while depleted:** `available` stays at current value,
  refills toward new cap over time.
- **Dynamic window extension:** For min-3 forward tasks, iteratively call
  `CronTrigger.get_next_fire_time()` beyond 3h. Negligible cost.

## Files affected

| File | Change |
|------|--------|
| `ping_budget.py` | Rewrite: refill bucket state, refill-on-read logic |
| `scheduler.py` | New `_build_upcoming_schedule()`, updated `_build_bg_preamble()`, remove `_fires_before_midnight`/`_remaining_bg_routine_firings`/`_compute_remaining` |
| `prompts.py` | Update budget description in system prompt (~3 lines) |

No changes to: `agent_tools.py`, `forks.py`, `bot.py`, `routines.py`,
`reminders.py`.

## What's NOT changing

- `critical=True` bypass (still tracked separately)
- `allow_ping: false` enforcement (still in `agent_tools.py`)
- Per-session 1-ping cap (preamble text, not code-enforced)
- `require_report_hook` stop hook
- Busy state logic
