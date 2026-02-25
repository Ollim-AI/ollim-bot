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

### Enforce 1-Ping-Per-Session Architecturally
"At most 1 ping or embed per bg session" is currently a prompt instruction.
Enforce it in code so the model can't accidentally send 2.

- Track per-session ping count in a contextvar (like `_bg_output_flag`)
- Block second `ping_user`/`discord_embed` with error: "Already sent 1
  ping this session. Use report_updates for additional findings."
- Removes reliance on prompt compliance for a behavioral constraint

## Backlog

### Owner Identity Guard
Verify `interaction.user` / `message.author` is the bot owner before processing.

- Currently safe: bot is private, invite-link controlled
- Needed before making the project public
- Check `app_info.owner` against sender in `on_message`, slash commands, reaction handlers, button handlers
- Without this, any Discord user who can DM or mention the bot gets full access

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

### Silent Button Handler Failures
Surface errors when Google API calls fail in button handlers.

- discord.py silently swallows unhandled exceptions in view callbacks
- User clicks "delete," gets no response, action didn't happen
- Failed one-shot reminders are also lost (no retry, no alert)
- Options: try/except with ephemeral error response, retry queue

### Agent Uncertainty Instructions
Add system prompt guidance for what to do when uncertain.

- No instruction to ask before acting on ambiguous information
- No instruction to push back on counterproductive requests
- No guidance on confirming irreversible actions
- May be addressed as part of a broader system prompt refactor (user-configurable prompts)

### Align `allow_ping: false` with Tool Visibility
When `allow_ping: false`, preamble says tools are "not available" but they
remain in the MCP tool list. Model could waste a call testing the constraint.

- In scheduler.py, add `mcp__discord__ping_user` and
  `mcp__discord__discord_embed` to `disallowed_tools` when `allow_ping`
  is false, so SDK hides them entirely
- No current routines use `allow_ping: false` — implement when needed

### Bot Presence Always Offline
Bot shows as offline in Discord even when running.

- Likely needs explicit presence/activity setting in `on_ready`
- `discord.Activity` or `discord.CustomActivity` to show status

## Under Consideration

### Stop Re-Prepending Stale Updates in Interactive Forks
`_prepend_context(clear=False)` peeks without consuming -- correct for not
stealing updates from the main session, but a 5-exchange fork wastes tokens
showing the same `RECENT BACKGROUND UPDATES` block 5 times.

- Track update count at fork entry time on the Agent instance
- Only prepend updates with index >= that count on subsequent exchanges
- Targeted change in `agent.py:_prepend_context()`

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
mid-conversation. Bot presence (always offline) is a separate bug, tracked
in Backlog.
