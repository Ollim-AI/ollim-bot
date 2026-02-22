# Feature Brainstorm

Ideas sourced from [OpenClaw docs](https://docs.openclaw.ai/) and conversation.

## Confirmed Interest

### Session Memory Snapshots
On `/clear`, auto-save a session summary before wiping context.

- Hook into `/clear` flow
- Agent summarizes the conversation (or we use claude-history to pull it)
- Save summary to `~/.ollim-bot/memory/` (or alongside existing session JSONL)
- Summaries become searchable via `claude-history` -- guide transcript deep-dives
- Respects existing Claude SDK session history (JSONL already logged)
- Agent gets awareness of past session topics without loading full transcripts

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

### Webhook Endpoints (External Triggers)
HTTP endpoints that trigger agent turns from external services.

- Small HTTP server (FastAPI/aiohttp) alongside Discord bot
- `POST /hook/wake` -- inject message into main session
- `POST /hook/agent` -- isolated agent turn with optional Discord delivery
- Enables: GitHub notifications, CI/CD results, home automation, IFTTT/Zapier
- Currently only cron and Discord messages can wake the agent
- Key use case: phone notification relay -- forward phone notifications to ollim,
  agent decides to dismiss or act (update tasks/calendar)

### Per-Job Tool Restrictions
Routines/reminders configure which MCP tools are available.

- `allowed_tools` in routine/reminder YAML frontmatter
- Restricts what the agent can do during that job
- `silent: true` shorthand -- blocks `ping_user` and `discord_embed`,
  agent can only use `report_updates` to queue findings for later
- Broader use: email triage only gets gmail + tasks tools, not calendar or forks
- Similar to Claude Code skill `allowed_tools` concept

Design:
- `allowed_tools: [a, b]` -- allowlist is source of truth (explicit, safe)
- `blocked_tools: [x, y]` -- denylist shorthand, subtracts from allowed (or from all if allowed omitted)
- `silent: true` -- sugar for `blocked_tools: [ping_user, discord_embed]`

### Session ID History (JSONL)
Save main session IDs to a JSONL log for claude-history lookup efficiency.

- Currently session ID is a plain string file (`~/.ollim-bot/sessions.json`)
- Only stores the current session -- previous IDs lost on `/clear`
- JSONL log of `{session_id, started_at, ended_at}` lets claude-history
  jump straight to relevant transcripts without scanning all sessions
- Pairs well with session memory snapshots -- summary + session ID together

### ~~Default-Deny Permission Mode (`dontAsk`)~~ ✓ Implemented
`dontAsk` is the default permission mode. Non-whitelisted tools silently denied.
Switch via `/permissions` slash command.

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

### Background Fork Timeouts
Add execution timeouts to `run_agent_background()` and related calls.

- Currently awaits SDK call indefinitely if it hangs
- Google API calls in button handlers and CLI have no timeout
- `subprocess.run` in `storage.py` has no timeout
- A hung bg fork holds resources forever with no cancellation

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

## Under Consideration

### Memory Flush Before Compaction
When auto-compaction triggers, agent gets a silent turn to save important
info to disk before older messages get summarized away.

- Prevents information loss during compaction
- Currently `/compact` just summarizes -- no pre-save step
- Needs technical investigation: what's actually feasible with the SDK's
  compaction flow? Can we hook into it or does it happen server-side?

Key question: what would be useful to save that auto-summarization wouldn't
preserve? Compaction already keeps a summary. Candidates:
- Exact task IDs / event IDs mentioned (summaries tend to lose specifics)
- User preferences expressed in conversation ("I prefer morning reminders")
- Commitments / promises ("I told X I'd do Y by Friday")
- Emotional context (was the user frustrated? celebrating?)
- Are any of these actually lost in practice?

### Presence / Availability Tracking
Track whether user is active, idle, or away based on last interaction time.
More granular than `skip_if_busy` (only checks mid-conversation).

- Could inform scheduling: don't ping if idle 3+ hours (asleep/AFK)
- Could adjust reminder urgency based on availability
- Discord already has presence (online/idle/dnd/offline) -- could read that

Needs real use cases to justify:
- What would the bot do differently if it knew the user was idle vs active?
- Is Discord's built-in presence status sufficient?
- Does this overlap with `silent: true` and `skip_if_busy`?

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
