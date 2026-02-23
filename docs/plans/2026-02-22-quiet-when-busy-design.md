# Quiet When Busy: Replace skip_if_busy with busy-aware bg forks

## Problem

`skip_if_busy: true` (the default) silently drops bg forks when the user is
mid-conversation. The fork never runs, never gathers information, and leaves no
trace. This wastes the opportunity — the agent should still do its work (check
email, review tasks, etc.) and surface findings via `report_updates` so they
appear next time the user messages.

## Design

### Remove `skip_if_busy`

Delete the field from:
- `Routine` and `Reminder` dataclasses + `from_frontmatter()` parsers
- CLI arg parsers (`routine_cmd.py`, `reminder_cmd.py`)
- `run_agent_background()` signature and early-return check
- SYSTEM_PROMPT documentation table
- All tests

The "quiet when busy" behavior is always-on for all bg forks. No per-item
opt-out needed.

### Busy-aware preamble

`run_agent_background()` checks `agent.lock().locked()` before launching the
fork. If locked, it passes `busy=True` to the preamble builder.

`_build_bg_preamble()` gains a `busy` parameter. When true, it appends:

> User is mid-conversation. Do NOT use `ping_user` or `discord_embed` unless
> `critical=True`. Use `report_updates` for all findings — they'll appear in
> the main session when the conversation ends.

This is volatile context (per-invocation state), not stable config.

### Soft-block non-critical pings when busy

New contextvar `_busy` in `forks.py`:
- `set_busy(val: bool)` / `is_busy() -> bool`
- Set by `run_agent_background()` when `agent.lock().locked()`

In `agent_tools.py`, `ping_user` and `discord_embed`:
- If `is_busy()` and not `critical=True` → return error:
  "User is mid-conversation. Use `report_updates` instead, or set
  `critical=True` for time-sensitive alerts."
- `critical=True` always goes through, even when busy

This is a safety net — the preamble instructs, the tool enforces.

### No other changes

- `report_updates` works exactly as today (appends to `pending_updates.json`)
- `_prepend_context` injects updates on next main-session message (already works)
- Ping budget still applies independently (busy-block runs before budget check)

## Context engineering notes

- **Right information, right time**: Agent runs, gathers info, surfaces it when
  user is ready — not during active conversation
- **Make intent explicit**: Preamble tells the agent exactly what "busy" means
  and what to do
- **Tools as context channels**: `report_updates` is the bridge; tool
  enforcement ensures it's the only output channel when busy (except critical)
- **No contradictions**: Preamble says "don't ping", tool enforces — consistent
  signal
- **Stable/volatile separated**: Busy state is per-invocation (contextvar), not
  persistent config

## Migration

Existing routine/reminder `.md` files with `skip_if_busy` in YAML frontmatter:
the parsers should silently ignore unknown fields (PyYAML default). No migration
needed — the field becomes a no-op.
