---
name: google-tasks
description: Manage Google Tasks. Use to add, list, complete, update, or delete tasks. Always check existing tasks before adding duplicates.
allowed-tools: Bash(ollim-bot tasks:*)
---

# Google Tasks

Manage tasks via `ollim-bot tasks`.

## Commands

| Command | Description |
|---------|-------------|
| `ollim-bot tasks list` | List incomplete tasks |
| `ollim-bot tasks list --all` | Include completed tasks |
| `ollim-bot tasks add "<title>" [--due YYYY-MM-DD] [--notes "<text>"]` | Add a task |
| `ollim-bot tasks done <id>` | Mark task as done |
| `ollim-bot tasks delete <id>` | Delete a task |
| `ollim-bot tasks update <id> [--title "<text>"] [--due YYYY-MM-DD] [--notes "<text>"]` | Update a task |

## Guidelines

- Always `list` before adding to avoid duplicates
- Use `--due` for tasks with deadlines
- Use `--notes` for context the future-you will need
- Task IDs are returned by `list` and `add` -- use them for done/delete/update
- When Julius mentions a task, add it immediately so it doesn't get lost
- When a task is done, mark it complete (don't delete -- completed tasks are useful history)
