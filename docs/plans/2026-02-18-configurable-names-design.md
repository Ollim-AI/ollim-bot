# Configurable User & Bot Names

## Goal

Replace all hardcoded "Julius" (user name) and "ollim-bot" (bot display name) references with configurable environment variables, so any user can run the bot with their own name.

## Configuration

- **Source**: Environment variables loaded via `python-dotenv` (already a dependency)
- **Variables**: `OLLIM_USER_NAME`, `OLLIM_BOT_NAME`
- **Defaults**: None — fail fast on startup if either is missing
- **Out of scope**: Package name (`ollim_bot`), CLI entry point (`ollim-bot`), data directory (`~/.ollim-bot/`), import paths

## Design

### New: `src/ollim_bot/config.py`

Module-level config that reads env vars at import time:

- Calls `load_dotenv()` at module level (idempotent with `main.py`'s explicit call)
- Reads `OLLIM_USER_NAME` and `OLLIM_BOT_NAME` from `os.environ`
- Raises `SystemExit` with a clear error if either is missing
- Exports `USER_NAME: str` and `BOT_NAME: str`

### Modified: `src/ollim_bot/prompts.py`

All prompt constants become f-strings using `config.USER_NAME`. ~25 occurrences across:

- `SYSTEM_PROMPT` — user name in personality, task handling, scheduling, fork, and tool descriptions
- `HISTORY_REVIEWER_PROMPT` — user name in role description and flagging criteria
- `GMAIL_READER_PROMPT` — user name in triage rules and output format
- `RESPONSIVENESS_REVIEWER_PROMPT` — user name in analysis descriptions

CLI command references (`ollim-bot tasks list`, etc.) stay hardcoded — they're the actual binary name.

### Modified: Other files

| File | Line | Change |
|------|------|--------|
| `bot.py:247` | Greeting message | Use `USER_NAME` and `BOT_NAME` |
| `bot.py:218` | Console log | Use `BOT_NAME` |
| `scheduler.py:285` | Fork idle prompt | Use `USER_NAME` |
| `views.py:149` | Fork report system message | Use `USER_NAME` |
| `agent_tools.py:114` | ping_user tool description | Use `USER_NAME` |

### New: `.env.example`

```
DISCORD_TOKEN=
OLLIM_USER_NAME=
OLLIM_BOT_NAME=
```

### Testing

- New test: verify `SystemExit` raised when env vars are missing
- `conftest.py`: set `OLLIM_USER_NAME` and `OLLIM_BOT_NAME` so existing tests pass
