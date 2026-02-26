# ollim-bot

ADHD-friendly Discord bot with proactive reminders, powered by the Claude
Agent SDK. ollim-bot lives in your DMs, reaches out on schedule, and
maintains persistent context across conversations.

Single-user by design — built to serve one human deeply. Others fork the repo
and make it their own.

**[Documentation](https://docs.ollim.ai/)** |
**[Quickstart](https://docs.ollim.ai/getting-started/quickstart)** |
**[Design Philosophy](https://docs.ollim.ai/getting-started/design-philosophy)**

## Features

- **Persistent conversations** — context carries across sessions with
  automatic compaction. The agent remembers what's going on.
- **Routines & reminders** — recurring crons and one-shot chainable reminders
  that run as background forks with a configurable ping budget.
- **Conversation forks** — branch into interactive or background forks. Save
  context back, report a summary, or discard entirely.
- **Google integration** — Tasks, Calendar, and Gmail (read-only) via shared
  OAuth. Manage tasks and events from Discord.
- **Webhooks** — HTTP endpoints for external triggers with JSON Schema
  validation and Haiku screening.
- **Slash commands** — model switching, context management, forking,
  permissions, and ping budget control.

## Quickstart

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/Ollim-AI/ollim-bot.git
cd ollim-bot
uv sync
uv tool install claude-history@git+https://github.com/Ollim-AI/claude-history.git
```

The last command installs
[claude-history](https://github.com/Ollim-AI/claude-history) globally — a CLI
tool the bot's subagents use to review conversation history.

Create a `.env` file:

```bash
DISCORD_TOKEN=your-discord-bot-token
OLLIM_USER_NAME=YourName
OLLIM_BOT_NAME=Ollim
```

Run:

```bash
uv run ollim-bot
```

See the [setup guide](https://docs.ollim.ai/getting-started/setup) for
Discord bot creation, Google OAuth, and webhook configuration.

## Development

```bash
uv sync               # Install dependencies
uv run ollim-bot      # Run the bot
uv run pytest         # Run tests
uv run ruff check     # Lint
uv run ruff format    # Format
```

See [development guide](https://docs.ollim.ai/development/guide) and
[architecture overview](https://docs.ollim.ai/architecture/overview).

## License

[GPL-3.0](LICENSE.md)
