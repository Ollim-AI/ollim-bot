# ollim-bot

ADHD-friendly Discord bot with proactive reminders, powered by Claude.

## Architecture
- `bot.py` -- Discord interface (responds to DMs and @mentions, guards duplicate on_ready)
- `agent.py` -- Claude Agent SDK brain (persistent per-user sessions via ClaudeSDKClient)
- `scheduler.py` -- Proactive reminders via APScheduler (morning standup, evening review, focus check-ins)
- `google_auth.py` -- Shared Google OAuth2 (Tasks + Calendar, extensible for new services)
- `tasks_cmd.py` -- Google Tasks CLI (`ollim-bot tasks`)
- `calendar_cmd.py` -- Google Calendar CLI (`ollim-bot cal`)
- `.claude/skills/` -- Project-level skills (google-tasks, google-calendar)

## Agent SDK config
- Auth: Claude Code OAuth (no API key needed)
- `ClaudeSDKClient` per user for persistent conversation with auto-compaction
- `setting_sources=["user", "project"]` to load skills from `~/.claude/skills/` and `.claude/skills/`
- Skills grant their own tool permissions via SKILL.md frontmatter (e.g. `Bash(ollim-bot tasks:*)`)
- `ResultMessage.result` is a fallback — don't double-count with `AssistantMessage` text blocks

## Google integration
- OAuth credentials: `~/.ollim-bot/credentials.json` (from Google Cloud Console)
- Token: `~/.ollim-bot/token.json` (auto-generated on first auth)
- Add new Google services: add scope to `google_auth.py`, create `*_cmd.py`, add skill

## Dev commands
```bash
uv sync                    # Install deps
uv run ollim-bot           # Run the bot
```

## Principles
- Keep it simple. No over-engineering.
- If a file exceeds 200 lines, it's too complex. Split it.
- No sprint docs, no ADRs, no elaborate process. Just build.
