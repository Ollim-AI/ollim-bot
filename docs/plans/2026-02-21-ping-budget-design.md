# Ping Budget Design

## Problem

The agent can send unlimited proactive pings (via bg fork routines/reminders) throughout the day. There's no mechanism to cap notification frequency, leading to potential ping fatigue. The agent also has no awareness of how many bg tasks remain today, so it can't plan strategically.

## Decisions

- **Scope**: proactive only — bg fork `ping_user` and `discord_embed` calls count. Main session and interactive fork embeds are user-requested and never count.
- **Critical bypass**: agent self-classifies via `critical=True` parameter on `ping_user`/`discord_embed`. No hard cap on critical pings, but tracked for visibility.
- **Over budget**: silent drop. Tool returns an error to the agent; user is not notified. Agent can still use `report_updates` to queue a summary.
- **Default**: 10 pings/day, resets at midnight.
- **Agent awareness**: budget status + remaining bg tasks injected into `BG_PREAMBLE` at job-fire time.
- **Enforcement**: hard — tool-level check in `agent_tools.py`, not prompt-only.

## Data Model

`~/.ollim-bot/ping_budget.json` (no git auto-commit — ephemeral state):

```json
{
  "daily_limit": 10,
  "used": 3,
  "critical_used": 1,
  "last_reset": "2026-02-21"
}
```

- `daily_limit`: configurable via `/ping-budget`, default 10
- `used`: non-critical proactive pings today
- `critical_used`: critical pings today (tracked, not capped)
- `last_reset`: ISO date; if stale, reset counters to 0

## New Module: `ping_budget.py`

Domain module (top-level, not in scheduling/) with:

- `BudgetState` frozen dataclass
- `load() -> BudgetState` — read JSON, auto-reset if date changed
- `save(state: BudgetState)` — atomic write (tempfile + os.replace, no git)
- `try_use() -> bool` — check remaining > 0, decrement `used`, save; returns False if exhausted
- `record_critical()` — increment `critical_used`, save
- `get_status() -> str` — formatted string for prompt injection
- `set_limit(n: int)` — update `daily_limit`, save

## Enforcement Point

In `agent_tools.py`, both `ping_user` and `discord_embed` gain:

1. A new optional `critical: bool` parameter (default False)
2. A budget check **only when `_source() == "bg"`**:

```python
if _source() == "bg":
    critical = args.get("critical", False)
    if not critical and not ping_budget.try_use():
        return error("Budget exhausted (0 remaining). Use critical=True only for genuinely urgent items.")
    if critical:
        ping_budget.record_critical()
```

Main session and interactive fork calls skip the check entirely.

## BG_PREAMBLE Injection

At job-fire time in `scheduler.py`, the preamble includes:

```
Ping budget: 7/10 remaining today (3 used, 1 critical bypass).
Remaining today: ~4 bg routines, 2 bg reminders before midnight.
Plan pings carefully -- you may not need to ping for every task.
Use report_updates for non-urgent summaries.
Set critical=True only for time-sensitive items (event in <30min, urgent message).
```

**Computing "remaining today":**

- **Bg reminders**: count reminders where `run_at` is between now and midnight and `background=True` (from data files)
- **Bg routines**: query APScheduler `get_jobs()` for remaining bg routine firings before midnight

Computed fresh at each job invocation so the count is always current.

## Slash Command: `/ping-budget`

```python
@bot.tree.command(name="ping-budget", description="View or set daily ping budget")
@discord.app_commands.describe(limit="New daily limit (omit to view current)")
async def slash_ping_budget(interaction: discord.Interaction, limit: int | None = None):
    if limit is not None:
        ping_budget.set_limit(limit)
        await interaction.response.send_message(f"Ping budget set to {limit}/day.")
    else:
        status = ping_budget.get_status()
        await interaction.response.send_message(status)
```

## What This Does NOT Do

- No per-tool breakdown (ping_user vs discord_embed share one pool)
- No hourly sub-limits
- No queuing of over-budget pings
- No hard cap on critical pings (trust the agent, track for audit)
- No git history for budget state (too noisy)
