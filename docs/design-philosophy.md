# Design Philosophy

Why ollim-bot is built the way it is — the decisions behind the frameworks,
patterns, and architecture.

## Why ollim-bot exists

Existing productivity tools fall into two traps. Traditional tools (Todoist,
Notion, Apple Reminders) are passive — they store your tasks but never push
back. You have to remember to check them, which is the exact problem they're
supposed to solve. For someone with ADHD, a tool that waits to be opened is a
tool that doesn't get used.

AI agent tools have a different problem. They try to do too much — spray
features and hope something sticks. Or they lock you into complex workflow
patterns with poor observability, where understanding what the agent is doing
feels like learning a new language. Templates and rigid workflows give you
structure without context, which produces generic results.

ollim-bot exists because a useful assistant needs to be proactive, deeply
contextual, and simple enough that using it doesn't become another task. It's a
personal productivity assistant, not an autonomous agent platform.

## Context is the product

The core belief behind this project: a useful assistant is only as useful as how
well it understands you in your current moment. That's what builds trust.
Autonomy, features, integrations — they're all secondary. Their ceiling can only
be as high as the agent's contextual understanding.

This shapes every design decision. Persistent sessions over stateless calls. A
single long-running conversation over disconnected threads. Background tasks
that fork from the main context rather than starting fresh. The agent earns
autonomy by knowing what's going on, not by being given permissions.

## Meet the user where they are

Yet another app is bad design for agents. Productivity needs the context of
where you already are, not more isolation. Discord is already open all day —
phone and desktop — so the bot meets you there instead of demanding you open
something new. Cross-device notifications come free without building a mobile
app.

The same logic applies to integrations. Google Tasks, Calendar, and Gmail are
the existing ecosystem — integrate with what's already in use rather than
migrating to something new. Google Tasks is intentionally simple, which matches
the ADHD-friendly philosophy: Notion-level complexity is the enemy, not the
goal. New integrations can expand over time, but only when the complexity is
justified.

## The agent model

The Claude Agent SDK is essentially a wrapper around Claude Code. It's the best
framework for turning a user prompt into real action — existing tools plus bash
make it extremely versatile, and file-based workflows keep things simple. No DSL
to learn, no workflow engine to configure — just code as tools (MCP or CLI-based
bash).

This matters because framework lock-in is one of the traps this project avoids.
Other agent frameworks impose complex workflow patterns, abstract away the agent
loop behind proprietary concepts, and make debugging feel like spelunking. The
Agent SDK is a thin layer: it handles the agent loop, persistent sessions,
compaction, and streaming, but everything else is just Python and bash. What the
agent does is visible, debuggable, and changeable without learning a
framework-specific language.

## Proactive by default

Most AI assistants are reactive — they wait for you to start a conversation. For
ADHD, that's the wrong model. Forgetting to check is the problem, so the bot
needs to come to you, not wait for you to come to it.

Scheduled routines and reminders create ambient awareness. Regular check-ins
build shared context over time — the bot knows what's going on because it's been
keeping up, not because you remembered to tell it. This bridges attention gaps:
when something falls through the cracks between active sessions, a scheduled
nudge catches it.

A good assistant doesn't wait to be asked. It surfaces relevant information at
the right time. That's the core ADHD value proposition — not more features, but
fewer things forgotten.

## Anti-slop

Slop is what happens when you give up agency to AI. Bad output and dangerous
decisions are the same failure — both come from nobody maintaining quality
control. An agent that submits code nobody reviewed, sends messages nobody
approved, or makes decisions nobody understood isn't a productivity tool. It's a
liability. Using AI where human judgment belongs is the root cause of slop, not
AI itself.

We fight this by investing in context engineering. Agentic capabilities improve
fast, and context quality has to keep pace — that's the work other projects
skip. We review every prompt, routine, and background task for whether it
produces reliable output, so the human can focus on high-signal decisions
instead of monitoring for stupid mistakes. The bot earns autonomy through
engineering discipline, not by being left unsupervised.

The bot's output follows the same standard. If it has enough context to be
specific, generic advice is a failure. If it has nothing useful to say, silence
is correct. A response that any stateless chatbot could have produced is slop —
cut it.

## Conversation management

DM-based chat makes context management complicated. You need to balance
remembering context from an endlessly scrolling conversation while keeping
updates contained so context doesn't get sidetracked. The fork model solves
this.

The main session is the persistent conversation — the core assistant
relationship. It stays focused on what matters. Interactive forks let you
brainstorm, research, or go on tangents without the penalty of losing the core
assistant to context pollution. Background forks let routine tasks (email triage,
task reviews) run grounded in the latest conversation while keeping only short
summary updates.

Selective persistence is key: after a fork, you choose what comes back. Save the
full context, report a summary, or discard entirely. This gives you control over
what sticks in the main conversation without having to manage it manually.

## Files as shared language

Markdown is the common language between human and agent. Both can read and write
it natively — no ORM, no SQL, no adapter layer. Routines and reminders are
markdown files with YAML frontmatter: open one in any editor and you see exactly
what it does. The agent creates them the same way you would.

JSONL is for data consumed only by code — session logs, pending updates, inquiry
state. It's append-friendly and machine-readable, but not something you'd edit
by hand.

Git tracking on the data directory means every change is versioned, diffable,
and recoverable. No database migrations, no schema management, no server to run.
The storage model is as simple as the tools that operate on it.

## Single-user, on purpose

This system is built to serve one human. Adding more users to interface with
would confuse the project goals — the entire value comes from deep personal
context, and multi-user dilutes that.

Single-user is also a simplicity constraint. No auth system, no tenant
isolation, no concurrent session management, no per-user config. Every design
decision gets simpler when there's exactly one person to serve.

Others can clone the project and modify it for themselves. The architecture is
transparent enough to fork and adapt. But the design assumes one user, and that
assumption runs deep — it's a feature, not a limitation.
