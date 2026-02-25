# Feature Brainstorm

Ideas sourced from [OpenClaw docs](https://docs.openclaw.ai/) and conversation.

## Confirmed Interest

### Session Memory Snapshots
Auto-save a session summary on `/clear` and compaction to enhance
claude-history with searchable summaries.

- Hook into `/clear` flow and compaction (`compact_boundary` SystemMessage)
- Agent summarizes the conversation (or extract post-hoc from JSONL)
- Save summary to `~/.ollim-bot/memory/` (or alongside existing session JSONL)
- Summaries become searchable via `claude-history` -- guide transcript deep-dives
- Different from Persistent Context File: snapshots are per-session
  historical records, context file is living agent memory

Open questions:
- Format: standalone summary file per session, or append to a rolling memory log?
- Should the agent write the summary (costs a turn) or extract it post-hoc from JSONL?
- How does this surface to the agent? System prompt injection? MCP tool to search?

### ~~Isolated Routine Mode~~ ✓ Implemented
`isolated: true` in routine/reminder YAML frontmatter. Creates standalone throwaway
client with no conversation history. Combined with per-job model overrides.

### ~~Per-Job Model Overrides~~ ✓ Implemented
`model: "haiku"` in routine/reminder YAML frontmatter. Background jobs only —
isolated mode is where model overrides clearly pay off (no cache miss on forked context).

### ~~Webhook Endpoints (External Triggers)~~ ✅ Implemented
See `webhook.py` and `docs/plans/2026-02-22-webhook-endpoints-design.md`.

### ~~Per-Job Tool Restrictions~~ ✓ Implemented
Routines/reminders configure which MCP tools are available.

- `allowed_tools` / `disallowed_tools` in routine/reminder YAML frontmatter
- Restricts what the agent can do during that job
- Uses SDK tool format directly (`Bash(ollim-bot gmail *)`, `mcp__discord__*`, etc.)
- Broader use: email triage only gets gmail + tasks tools, not calendar or forks

Design:
- `allowed_tools: [a, b]` -- allowlist is source of truth (explicit, safe)
- `disallowed_tools: [x, y]` -- denylist shorthand, subtracts from default set
- Orthogonal to `allow_ping` / `update_main_session` (those have their own rich behavior)

### ~~Session ID History (JSONL)~~ ✓ Implemented
Save main session IDs to a JSONL log for claude-history lookup efficiency.

- Currently session ID is a plain string file (`~/.ollim-bot/sessions.json`)
- Only stores the current session -- previous IDs lost on `/clear`
- JSONL log of `{session_id, started_at, ended_at}` lets claude-history
  jump straight to relevant transcripts without scanning all sessions
- Pairs well with session memory snapshots -- summary + session ID together

### ~~Default-Deny Permission Mode (`dontAsk`)~~ ✓ Implemented
`dontAsk` is the default permission mode. Non-whitelisted tools silently denied.
Switch via `/permissions` slash command.

### Persistent Context File
Agent maintains a living context file (`~/.ollim-bot/context.md`) that
survives compaction and `/clear`. Compaction-proof memory for preferences,
patterns, and critical facts.

- Agent reads on reconnect (system prompt or `_prepend_context` injection)
- Agent writes/updates as it learns things worth remembering
- Needs brainstorming on: what triggers a write? how to prevent bloat?
  what's the right granularity? how does the agent decide what's "worth
  remembering" vs transient conversation?
- Subsumes "Default Compaction Instructions" — if critical context is
  externalized, compaction loss matters less
- Related to Session Memory Snapshots (different scope: snapshots are
  per-session summaries for claude-history, this is living context)

### ~~Enforce 1-Ping-Per-Session Architecturally~~ ✓ Implemented
Mutable-container contextvar (`_bg_ping_count`) in `forks.py`. Checked in
`_check_bg_budget()` before busy/budget checks. `critical=True` bypasses.

## Backlog

### ~~Owner Identity Guard~~ ✓ Implemented
Module-level `_owner_id` set in `on_ready`. Guards on `on_message`,
`on_raw_reaction_add`, and all slash commands via `@app_commands.check`.

### External Content Sanitization
Tag external content (emails, calendar events, web pages) as untrusted in agent context.

- Emails, calendar events, and web content are injected as raw text
- A malicious email body could contain instruction-shaped text
- gmail-reader subagent is a partial barrier but summaries flow back as plain text
- `report_updates` is a second-hop injection path (bg fork reads malicious content, queues adversarial summary)
- Options: content tagging/fencing, length caps, instruction stripping

### Irreversible Action Confirmation
Add confirmation step before destructive actions.

- Task/event deletion via buttons executes immediately with no "are you sure?"
- System prompt says "don't delete tasks" but that's a soft preference
- Agent can also call `ollim-bot tasks delete` and `ollim-bot cal delete` directly
- Options: Discord confirmation modal, two-step button flow, agent-level instruction to always confirm

### ~~Background Fork Timeouts~~ ✓ Implemented
`BG_FORK_TIMEOUT = 1800` (30 min) wraps `run_agent_background()`. On timeout:
client disconnected, user notified via DM. Google API / subprocess timeouts
remain as separate backlog items.

### ~~Silent Button Handler Failures~~ ✓ Implemented
`HttpError` try/except on `_handle_task_done`, `_handle_task_delete`,
`_handle_event_delete` in `views.py`. Ephemeral error response on failure.

### Agent Uncertainty Instructions
Add system prompt guidance for what to do when uncertain.

- No instruction to ask before acting on ambiguous information
- No instruction to push back on counterproductive requests
- No guidance on confirming irreversible actions
- May be addressed as part of a broader system prompt refactor (user-configurable prompts)

### ~~Align `allow_ping: false` with Tool Visibility~~ ✓ Implemented
`_hide_ping_tools()` helper in `scheduler.py`. When `allow_ping` is false,
adds ping tools to `disallowed_tools` (or filters from `allowed_tools`).

### ~~Bot Presence Always Offline~~ ✓ Implemented
`activity=discord.Activity(type=ActivityType.watching, name="your DMs")`
in `create_bot()`. Also enforced DM-only via `allowed_installs` and
`allowed_contexts` on the command tree.

### ~~Separate Agent Workspace from Code-Only State~~ ✓ Implemented
Code-only infrastructure files (sessions, ping budget, credentials, PID)
moved to `~/.ollim-bot/state/`. Agent workspace root now only contains
agent-managed directories (`routines/`, `reminders/`, `webhooks/`) and
spec symlinks. `storage.STATE_DIR` is the single source of truth for all
state file paths — no more hardcoded `Path.home()` across modules.

## Under Consideration

### Stop Re-Prepending Stale Updates in Interactive Forks
`_prepend_context(clear=False)` peeks without consuming -- correct for not
stealing updates from the main session, but a 5-exchange fork wastes tokens
showing the same `RECENT BACKGROUND UPDATES` block 5 times (~100-200
tokens per redundant prepend, scaling with fork length and update count).

Fix: add `_fork_updates_offset` module-level global in `forks.py`
(consistent with existing fork state pattern: `_in_interactive_fork`,
`_fork_exit_action`, etc.):

- Set to `len(peek_pending_updates())` in `enter_interactive_fork()`
- Slice `updates[offset:]` in `_prepend_context()` when `clear=False`
- Reset to 0 in `exit_interactive_fork()`
- First exchange shows all pre-existing updates; subsequent exchanges
  only show NEW updates from concurrent bg forks
- Safe because agent lock serializes all main/fork exchanges
- `save_context` clearing the file is a non-issue (fork gets promoted)
- ~10-15 lines across `forks.py` + `agent.py`

## Rejected / Already Covered

### Heartbeat
Already covered by routines. A single routine with a batched prompt is equivalent.

### Multi-Agent Routing
Overkill for single-user bot. Subagents already cover specialized delegation.

### Hook System (Event-Driven Plugins)
Interesting but premature abstraction. Current codebase is small enough
that direct code changes are faster than designing a plugin system.

### Model Failover Chain
Rare in practice -- Opus overload/rate-limit failures are uncommon.
Not worth the complexity right now.

### Cron Stagger
Claude API handles parallel agents fine -- no hardware bottleneck to stagger around.

### Command Logger / Audit Trail
Already covered by Claude SDK's standard JSONL logging. claude-history reads it.

### Voice Note Transcription
OS-level voice-to-text (phone keyboard, Windows, macOS) already covers this.

### Gmail Push (Pub/Sub)
Requires Google Cloud Pub/Sub setup + webhook endpoint. Only valuable
after webhook endpoints exist. Can revisit then.

### Reply-to-Fork Staleness Signal
Could add age indicator when resuming old bg fork sessions. Not needed —
user only replies to recent fork messages.

### Presence / Availability Tracking
Track user idle/away state to skip non-critical pings during AFK hours.
Not needed — routines are scheduled during waking hours, busy flag covers
mid-conversation. Bot presence bug is fixed (see Backlog).
