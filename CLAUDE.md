# ollim-bot

ADHD-friendly Discord bot with proactive reminders, powered by Claude.

## Architecture
- `bot.py` -- Discord interface (responds to DMs and @mentions, guards duplicate on_ready)
- `agent.py` -- Claude Agent SDK brain (persistent per-user sessions, all tool/subagent config in code)
- `scheduler.py` -- Proactive reminders via APScheduler (seeds defaults into wakeups.jsonl, syncs every 10s)
- `google_auth.py` -- Shared Google OAuth2 (Tasks + Calendar + Gmail)
- `tasks_cmd.py` -- Google Tasks CLI (`ollim-bot tasks`)
- `calendar_cmd.py` -- Google Calendar CLI (`ollim-bot cal`)
- `gmail_cmd.py` -- Gmail CLI (`ollim-bot gmail`, read-only)

## Agent SDK config
- Auth: Claude Code OAuth (no API key needed)
- `ClaudeSDKClient` per user for persistent conversation with auto-compaction
- No `setting_sources` -- all config is in code (no CLAUDE.md, skills, or settings.json loaded)
- `permission_mode="dontAsk"` -- headless, auto-approves tools in `allowed_tools`
- gmail-reader subagent defined programmatically via `AgentDefinition`
- Tool instructions (tasks, cal, schedule, history) inlined in SYSTEM_PROMPT
- `ResultMessage.result` is a fallback — don't double-count with `AssistantMessage` text blocks

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
