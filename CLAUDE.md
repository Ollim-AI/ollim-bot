# ollim-bot

ADHD-friendly Discord bot with proactive reminders, powered by Claude.

## Architecture
- `bot.py` -- Discord interface (responds to DMs and @mentions)
- `agent.py` -- Claude-powered brain (conversation + tool use)
- `tasks.py` -- Google Tasks API integration (TODO)
- `scheduler.py` -- Proactive reminders via APScheduler (TODO)

## Dev commands
```bash
uv sync                    # Install deps
uv run ollim-bot           # Run the bot
```

## Principles
- Keep it simple. No over-engineering.
- If a file exceeds 200 lines, it's too complex. Split it.
- No sprint docs, no ADRs, no elaborate process. Just build.
