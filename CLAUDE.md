# ollim-bot

ADHD-friendly Discord bot with proactive reminders, powered by Claude.

## Architecture
- `bot.py` -- Discord interface (DMs, @mentions, slash commands, reaction ack, interrupt-on-new-message)
- `agent.py` -- Claude Agent SDK brain (persistent sessions, MCP tools, subagents, slash command routing)
- `prompts.py` -- System prompts for agent and subagents (extracted from agent.py)
- `discord_tools.py` -- `discord_embed` MCP tool (Claude sends rich embeds + buttons via tool use)
- `views.py` -- Button handlers via `DynamicItem` (task_done, task_del, event_del, agent followup)
- `scheduler.py` -- Proactive reminders via APScheduler (seeds defaults into wakeups.jsonl, syncs every 10s)
- `google_auth.py` -- Shared Google OAuth2 (Tasks + Calendar + Gmail)
- `tasks_cmd.py` -- Google Tasks CLI (`ollim-bot tasks`)
- `calendar_cmd.py` -- Google Calendar CLI (`ollim-bot cal`)
- `gmail_cmd.py` -- Gmail CLI (`ollim-bot gmail`, read-only)
- `streamer.py` -- Streams agent responses to Discord (throttled edits, 2000-char overflow)
- `sessions.py` -- Persists Agent SDK session IDs for conversation resumption across restarts

## Agent SDK config
- Auth: Claude Code OAuth (no API key needed)
- `ClaudeSDKClient` per user for persistent conversation with auto-compaction
- No `setting_sources` -- all config is in code (no CLAUDE.md, skills, or settings.json loaded)
- `permission_mode="dontAsk"` -- headless, auto-approves tools in `allowed_tools`
- Subagents defined programmatically via `AgentDefinition`: gmail-reader, history-reviewer
- Tool instructions (tasks, cal, schedule, embeds) inlined in SYSTEM_PROMPT; history delegated to subagent
- `ResultMessage.result` is a fallback — don't double-count with `AssistantMessage` text blocks
- `include_partial_messages=True` -- enables `StreamEvent` for real-time streaming
- `StreamEvent` imported from `claude_agent_sdk.types` (not in `__init__.__all__`)
- Session IDs persisted to `~/.ollim-bot/sessions.json`; `resume=session_id` on reconnect
- `_drop_client()`: interrupt + drop reference, skip `disconnect()` (anyio cross-task limitation)
- Race guard: `save_session_id` skipped if client was popped mid-stream by `/clear` or `/model`

## Discord slash commands
- `/clear` -- reset conversation (drop client + delete session ID)
- `/compact [instructions]` -- compress context via SDK's native `/compact`
- `/cost` -- show token usage via SDK's native `/cost`
- `/model <opus|sonnet|haiku>` -- switch model (update options + drop client, next message reconnects)
- `Agent.slash()` -- generic method routing SDK slash commands, captures SystemMessage + AssistantMessage + ResultMessage
- `Agent.set_model()` -- uses `dataclasses.replace()` on shared options (single-user assumption)
- Synced via `bot.tree.sync()` in `on_ready`

## Discord embeds & buttons
- `discord_embed` MCP tool via `create_sdk_mcp_server` — Claude controls when to send embeds
- Channel reference stored in module-level `_channel` (discord_tools.py), set before each stream_chat()
- Button actions encoded in `custom_id`: `act:<action>:<data>` pattern
- Direct actions (task_done, task_del, event_del): call Google API directly, ephemeral response
- Agent followup (agent:<uuid>): stored prompts, route back through agent.stream_chat()
- `DynamicItem[Button]` for persistent buttons across restarts
- Followup prompts expire on restart (ephemeral "expired" message)

## Google integration
- OAuth credentials: `~/.ollim-bot/credentials.json` (from Google Cloud Console)
- Token: `~/.ollim-bot/token.json` (auto-generated on first auth)
- Gmail is read-only (`gmail.readonly` scope), accessed via the gmail-reader subagent
- Add new Google services: add scope to `google_auth.py`, create `*_cmd.py`, add commands to SYSTEM_PROMPT

## Dev commands
```bash
uv sync                    # Install deps
uv run ollim-bot           # Run the bot
```

## Principles
- Keep it simple. No over-engineering.
- If a file exceeds 200 lines, it's too complex. Split it.
- No sprint docs, no ADRs, no elaborate process. Just build.
