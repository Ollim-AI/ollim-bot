# ollim-bot

ADHD-friendly Discord bot with proactive reminders, powered by Claude.

## Architecture
- `bot.py` -- Discord interface (responds to DMs and @mentions, guards duplicate on_ready)
- `agent.py` -- Claude Agent SDK brain (persistent per-user sessions via ClaudeSDKClient)
- `scheduler.py` -- Proactive reminders via APScheduler (morning standup, evening review, focus check-ins)
- `tasks.py` -- Google Tasks API integration (TODO)

## Agent SDK config
- Auth: Claude Code OAuth (no API key needed)
- `ClaudeSDKClient` per user for persistent conversation with auto-compaction
- `setting_sources=["user"]` to load skills from `~/.claude/skills/`
- Skills grant their own tool permissions via SKILL.md frontmatter (e.g. `Bash(claude-history:*)`)
- `ResultMessage.result` is a fallback — don't double-count with `AssistantMessage` text blocks

## Dev commands
```bash
uv sync                    # Install deps
uv run ollim-bot           # Run the bot
```

## Principles
- Keep it simple. No over-engineering.
- If a file exceeds 200 lines, it's too complex. Split it.
- No sprint docs, no ADRs, no elaborate process. Just build.
