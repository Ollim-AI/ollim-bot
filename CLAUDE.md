# ollim-bot

ADHD-friendly Discord bot with proactive reminders, powered by Claude.

## Architecture
- `bot.py` -- Discord interface (DMs, @mentions, slash commands, reaction ack, interrupt-on-new-message)
- `agent.py` -- Claude Agent SDK brain (persistent sessions, MCP tools, subagents, slash command routing)
- `prompts.py` -- System prompts for agent and subagents (extracted from agent.py)
- `discord_tools.py` -- MCP tools: `discord_embed`, `ping_user`, `follow_up_chain`, `save_context`, `report_updates`
- `views.py` -- Persistent button handlers via `DynamicItem` (delegates to google/ and streamer)
- `storage.py` -- Shared JSONL I/O with git auto-commit (`~/.ollim-bot/` data repo)
- `streamer.py` -- Streams agent responses to Discord (throttled edits, 2000-char overflow, `dispatch_agent_response`)
- `sessions.py` -- Persists Agent SDK session ID (plain string file) for conversation resumption across restarts
- `embeds.py` -- Embed/button types, builders, maps, and `build_embed`/`build_view` (shared by discord_tools and views)
- `inquiries.py` -- Persists button inquiry prompts to `~/.ollim-bot/inquiries.json` (7-day TTL)
- `google/` -- Google API integration sub-package
  - `auth.py` -- Shared Google OAuth2 (Tasks + Calendar + Gmail)
  - `tasks.py` -- Google Tasks CLI + API helpers (`complete_task`, `delete_task`)
  - `calendar.py` -- Google Calendar CLI + API helpers (`delete_event`)
  - `gmail.py` -- Gmail CLI (`ollim-bot gmail`, read-only)
- `scheduling/` -- Routines, reminders, and APScheduler sub-package
  - `routines.py` -- Routine dataclass and JSONL I/O (recurring crons, `routines.jsonl`)
  - `reminders.py` -- Reminder dataclass and JSONL I/O (one-shot + chainable, `reminders.jsonl`)
  - `scheduler.py` -- Proactive scheduling via APScheduler (syncs routines + reminders every 10s)
  - `routine_cmd.py` -- Routines CLI (`ollim-bot routine`)
  - `reminder_cmd.py` -- Reminders CLI (`ollim-bot reminder`)

## Agent SDK config
- Auth: Claude Code OAuth (no API key needed)
- Single `ClaudeSDKClient` for persistent conversation with auto-compaction (single-user bot)
- No `setting_sources` -- all config is in code (no CLAUDE.md, skills, or settings.json loaded)
- `permission_mode="default"` -- SDK default; tools gated by `allowed_tools`
- Subagents defined programmatically via `AgentDefinition`: gmail-reader, history-reviewer, responsiveness-reviewer
- Tool instructions (tasks, cal, routines, reminders, embeds) inlined in SYSTEM_PROMPT; history delegated to subagent
- `ResultMessage.result` is a fallback — don't double-count with `AssistantMessage` text blocks
- `include_partial_messages=True` -- enables `StreamEvent` for real-time streaming
- `StreamEvent` imported from `claude_agent_sdk.types` (not in `__init__.__all__`)
- Session ID persisted to `~/.ollim-bot/sessions.json` (plain string, not JSON); `resume=session_id` on reconnect
- `_drop_client()`: set `_client = None` first, then interrupt + disconnect; suppresses `CLIConnectionError` on interrupt (subprocess may have exited)
- `swap_client(client, session_id)`: promotes forked client to main (avoids reconnect); drops old client
- Race guard: `save_session_id` skipped if `self._client is not client` (client was dropped mid-stream by `/clear` or `/model`)

## Discord slash commands
- `/clear` -- reset conversation (drop client + delete session ID)
- `/compact [instructions]` -- compress context via SDK's native `/compact`
- `/cost` -- show token usage via SDK's native `/cost`
- `/model <opus|sonnet|haiku>` -- switch model (update options + drop client, next message reconnects)
- `Agent.slash()` -- generic method routing SDK slash commands, captures SystemMessage + AssistantMessage + ResultMessage
- `Agent.set_model()` -- uses `dataclasses.replace()` on shared options + updates live client
- Synced via `bot.tree.sync()` in `on_ready`

## Discord embeds & buttons
- `discord_embed` MCP tool via `create_sdk_mcp_server` — Claude controls when to send embeds
- Channel reference stored in module-level `_channel` (discord_tools.py), set before each stream_chat()
- Button actions encoded in `custom_id`: `act:<action>:<data>` pattern
- Direct actions (task_done, task_del, event_del): call google/ API helpers directly, ephemeral response
- Agent inquiry (agent:<uuid>): stored prompts, route back through `dispatch_agent_response()`
- `dispatch_agent_response()` in streamer.py: set_channel → typing → stream (used by bot.py and views.py)
- `DynamicItem[Button]` for persistent buttons across restarts
- Inquiry prompts persisted to `~/.ollim-bot/inquiries.json` (survive restarts, 7-day TTL)

## Google integration
- OAuth credentials: `~/.ollim-bot/credentials.json` (from Google Cloud Console)
- Token: `~/.ollim-bot/token.json` (auto-generated on first auth)
- Gmail is read-only (`gmail.readonly` scope), accessed via the gmail-reader subagent
- Add new Google services: add scope to `google/auth.py`, create `google/*.py`, add commands to SYSTEM_PROMPT

## Routines & reminders
- Routines (recurring crons): `~/.ollim-bot/routines.jsonl`
- Reminders (one-shot, chainable): `~/.ollim-bot/reminders.jsonl`
- `~/.ollim-bot/` is a git repo; `storage.py` auto-commits on every add/remove
- Scheduler polls both files every 10s, registers/removes APScheduler jobs
- Scheduler and streamer receive `owner: discord.User` (resolved once in bot.py `on_ready`)
- Cron day-of-week: standard cron (0=Sun) converted to APScheduler names via `_convert_dow()`
- Routines managed by Julius via `ollim-bot routine add|list|cancel`
- Reminders created by user or bot via `ollim-bot reminder add|list|cancel`
- Prompt tags: `[routine:ID]`, `[routine-bg:ID]`, `[reminder:ID]`, `[reminder-bg:ID]`
- Background mode: runs on forked session; text output discarded, agent uses `ping_user`/`discord_embed` to alert
- Forked sessions: `run_agent_background` creates disposable forked client (`fork_session=True`)
  - `save_context` MCP tool: promotes fork via `swap_client` (fork client replaces main, no reconnect needed)
  - `report_updates(message)` MCP tool: discards fork, persists summary to `~/.ollim-bot/pending_updates.json`
  - Neither called: fork silently discarded, zero context bloat
  - Pending updates injected into next main-session message via `_prepend_context()` in agent.py
- Chain reminders: `--max-chain N` enables follow-up chain; agent calls `follow_up_chain` MCP tool
- Chain state: scheduler injects chain context into prompt; silence = chain ends

## Dev commands
```bash
uv sync                    # Install deps
uv run ollim-bot           # Run the bot
```

## Principles
Read the python-principles skill.

## Plan mode
Before proposing the plan (ExitPlanMode), load the `python-principles` skill and re-review the plan to ensure it introduces no new violations.
