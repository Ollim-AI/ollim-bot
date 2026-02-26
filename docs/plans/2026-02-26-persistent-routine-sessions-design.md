# Persistent Routine Sessions

## Problem

Background routines (trading research, threshold monitoring) fire as one-shot
sessions — each fire starts fresh with no memory of previous runs. Tasks that
need to track trends, accumulate observations, or detect threshold crossings
over time can't do so because context is discarded after every fire.

## Solution

Routines can opt into a persistent session that survives across fires. The
routine builds its own standalone context over time, separate from the main
conversation. The agent controls compaction via a new MCP tool, guided by
instructions in the routine prompt.

## YAML Interface

One new frontmatter field:

| Field     | Type         | Default | Description                        |
|-----------|--------------|---------|------------------------------------|
| `session` | `str \| None` | `None`  | Session mode: `persistent` (bg only) |

Validation:
- `session: persistent` requires `background: true`
- `session: persistent` and `isolated: true` are mutually exclusive

Compaction guidance goes in the routine body (the prompt), not in frontmatter.

Example:

```yaml
---
id: a1b2c3d4
cron: "0 9 * * 1-5"
description: Daily market analysis
background: true
session: persistent
update_main_session: on_ping
---
Check current market conditions and update your running analysis.

When context gets large, compact and preserve: current positions,
price levels, trend observations. Discard detailed per-fire analysis.
```

## Session Persistence

**Storage:** `~/.ollim-bot/state/routine_sessions/<routine-id>` — plain string
file per routine (same format as main session file).

**Lifecycle:**
1. **First fire:** No session file. Create fresh client (standalone, no
   conversation history). Save returned session ID to file.
2. **Subsequent fires:** Session file exists. Resume with `resume=<session_id>`
   (no `fork_session` — continuing, not branching). Update file if ID changed.
3. **Routine deleted:** Clean up session file when `sync_all` detects removal.

**Client creation:** `Agent.create_persistent_client(session_id, *, model,
thinking, allowed_tools, disallowed_tools)` — resumes if session ID provided,
fresh otherwise. Model/thinking overrides work the same as isolated mode.

**Session history:** New event type `"persistent_bg"` via `log_session_event`.

## Compact Tool

**New MCP tool: `compact_session(instructions: str)`**

- Available only in persistent routine sessions (returns error otherwise)
- Agent decides when to call it, guided by compaction instructions in its prompt

**Implementation:**
1. New contextvar `_client_var` in `forks.py` — active client reference, set
   before `run_on_client`, cleared in `finally`
2. Tool reads client from contextvar, calls `client.query("/compact " + instructions)`,
   drains response
3. Captures new session ID, updates routine's session file
4. Returns compact result text to agent

**Scope guard:** Contextvar `_persistent_routine_id_var` identifies which
persistent routine is running. Compact tool checks this — returns error if not
set. Also used to locate the correct session file.

**Prompt awareness:** Bg preamble includes when persistent:
```
SESSION: Persistent — your context carries across fires.
You have a `compact_session` tool to compress context when it grows large.
```

## Concurrency

**Same routine firing twice:** Prevented by `_active_persistent: set[str]` in
`forks.py`. Before client creation, check if routine ID is in the set — if so,
log warning and skip. Added/removed in try/finally.

**Different persistent routines concurrent:** Safe — contextvars isolate each
task's `_client_var` and `_persistent_routine_id_var`, each writes to its own
session file.

## Integration with `run_agent_background`

Changes slot into the existing flow:

**`scheduler.py` `_fire()`:** Load session ID from routine's session file if
`session: persistent`, pass to `run_agent_background` with routine ID.

**`run_agent_background`:** New parameters `persistent_session_id` and
`persistent_routine_id`. Set contextvars, check skip guard, create client via
`create_persistent_client`, save session ID after execution.

**Session ID on compact:** `compact_session` tool updates session file
immediately (ID changes on compact). Post-`run_on_client` also saves as
fallback for SDK auto-compaction.

**Cleanup:** `sync_all` removes session file when routine is deleted.

## Modified Files

- `scheduling/routines.py` — `session` field + validation
- `scheduling/scheduler.py` — load persistent session ID, pass to bg fork, cleanup
- `forks.py` — `_client_var`, `_persistent_routine_id_var`, `_active_persistent`, skip guard, session file I/O
- `agent.py` — `create_persistent_client` method
- `agent_tools.py` — `compact_session` MCP tool
- `scheduling/preamble.py` — persistent session awareness in bg preamble

## Not in Scope

- Session staleness / TTL
- Custom compaction strategies beyond agent-driven
