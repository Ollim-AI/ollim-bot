# Design Philosophy

Why ollim-bot exists, why it's built the way it is, and why not something else.

## Why build this?

Existing productivity tools (Todoist, Notion, Things) are passive -- they store tasks and wait for you to check them. For ADHD, that's the failure mode: out of sight, out of mind. ollim-bot is an active companion that knows your context, reaches out proactively, and meets you where you already are (Discord on your phone).

It's not a general-purpose AI agent. It's a single-user productivity assistant that happens to be powered by one.

## Why not existing tools?

**Why not a Todoist/Notion bot?** Those tools are the storage layer, not the intelligence. Bolting an AI onto Todoist gives you a chatbot that can add tasks -- not one that remembers you said "I'll do that after lunch" three hours ago and follows up.

**Why not an existing AI assistant bot?** General-purpose Discord bots (ChatGPT bots, etc.) are stateless and multi-tenant. They don't know your calendar, your task list, or that you've been putting off that email since Tuesday. ollim-bot is a single persistent conversation with full context.

**Why not just use Claude directly?** Claude doesn't have your Google Tasks, your calendar, your reminders. It can't ping you at 9am or notice you went quiet. ollim-bot wraps Claude with the integrations and proactivity that make it a productivity tool instead of a chat window.

## Key decisions

### Discord as the interface

Discord is already open all day. DMs are a natural conversational interface. Rich embeds and buttons give structured interactions (task cards with "done" buttons, calendar events with "delete"). Mobile push notifications are free. No custom app to build and maintain.

### Claude Agent SDK as the brain

The bot needs persistent multi-turn conversation, tool use, and the ability to reason about ambiguous requests ("move that meeting to after my dentist appointment"). The Agent SDK provides all of this with session persistence, MCP tools, and subagents. Claude Code OAuth means no API key management.

The alternative was raw API calls with manual context management. The SDK handles compaction, tool routing, and session resumption -- infrastructure that would otherwise be half the codebase.

### Single-user architecture

ollim-bot is a personal tool, not a platform. Single-user means:
- One persistent conversation (no session multiplexing)
- Direct file I/O for state (no database)
- No auth layer beyond Discord's invite system
- The agent's system prompt can be deeply personalized

Multi-tenancy would 10x the complexity for zero benefit. If someone else wants this, they fork it and run their own instance.

### Forking model for parallel work

The main conversation is sacred -- it's the persistent thread of daily interaction. But background tasks (routine check-ins, reminder follow-ups) and deep dives (planning a trip, debugging a schedule conflict) shouldn't pollute it.

Forks solve this: background forks run silently and report back via `pending_updates`. Interactive forks branch off for focused work and can either save context back to main or discard cleanly. The main session stays coherent either way.

### Markdown files over a database

Routines and reminders are YAML-frontmatter markdown files in `~/.ollim-bot/`. This means:
- **Human-readable** -- you can `cat` a reminder to see what it does
- **Git-trackable** -- every change is auto-committed, full history for free
- **Agent-editable** -- Claude can read/write/edit files directly via MCP, no ORM or API layer needed
- **Portable** -- the entire bot state is one directory you can copy

A database would add a dependency, require migrations, and force every agent interaction through an API. Files are the right tool at this scale.

### Google Tasks/Calendar as the source of truth

Tasks and calendar events live in Google, not in the bot. The bot reads and writes to Google's APIs. This means:
- Mobile access through Google's own apps (no custom mobile client)
- No sync conflicts -- Google is the single source of truth
- Existing data stays where it is

The bot is a better *interface* to your existing tools, not a replacement for them.

### APScheduler for proactive behavior

Routines (recurring crons) and reminders (one-shot triggers) run via APScheduler, in-process. The scheduler polls markdown files every 10 seconds and syncs jobs. No external scheduler service, no message queue, no cron daemon.

The alternative was system-level cron or a separate scheduler service. In-process means the scheduler shares the event loop with Discord and the agent -- it can fire a background fork directly without IPC.

### MCP tools for agent-initiated actions

The agent decides when to ping the user, send embeds, fork conversations, and chain reminders. These aren't user commands -- they're agent capabilities exposed as MCP tools. This keeps the agent in control of its own proactive behavior rather than being a passive command executor.

### Contextvars for fork isolation

Background forks run concurrently with the main session. Rather than locking or class hierarchies, fork-scoped state (channel, chain context, in-fork flag) uses Python's `contextvars`. Each background fork gets its own context automatically via `asyncio.create_task`, no explicit passing needed.

## What this is not

- **Not a framework** -- it's one bot for one person. No plugin system, no extensibility API, no multi-bot orchestration.
- **Not a general-purpose agent** -- every feature serves ADHD-friendly task/time management. If it doesn't help with productivity, it doesn't belong.
- **Not a demo** -- it runs daily. Features are evaluated against real use, not hypothetical scenarios.
