---
name: google-calendar
description: Read and create Google Calendar events. Use to check today's schedule, see upcoming events, or create time blocks.
allowed-tools: Bash(ollim-bot cal:*)
---

# Google Calendar

Manage calendar via `ollim-bot cal`.

## Commands

| Command | Description |
|---------|-------------|
| `ollim-bot cal today` | Show today's events |
| `ollim-bot cal upcoming [--days N]` | Show next N days (default 7) |
| `ollim-bot cal add "<summary>" --start "YYYY-MM-DDTHH:MM" --end "YYYY-MM-DDTHH:MM" [--description "<text>"]` | Create event |
| `ollim-bot cal delete <id>` | Delete an event |

## Guidelines

- Check `today` at the start of conversations to give context-aware advice
- Times are in America/Los_Angeles (PT)
- For focus blocks, create calendar events (e.g. "Deep work: Fix login bug" 2-4pm)
- Start and end are required for `add` -- always include both
- Event IDs are shown in `today` and `upcoming` output
- When scheduling reminders, cross-reference the calendar to avoid conflicts
