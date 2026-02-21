# ollim-bot

ADHD-friendly Discord bot with proactive reminders, powered by Claude.

## Product philosophy
- **Productivity assistant first** — not a general-purpose autonomous agent. Every feature must serve ADHD-friendly task/time management.
- **Quality over breadth** — high-quality, well-tested features over shotgun coverage. Say no to features that don't earn their complexity.
- **Real-use grounded** — evaluate against actual daily use, not hypothetical scenarios. If a feature isn't used weekly, question whether it belongs.

These guide your own design proposals. When the user explicitly requests a feature, build it — don't gatekeep with philosophy.

## Architecture
- `bot.py` -- Discord interface (DMs, @mentions, slash commands, reaction ack, interrupt-on-new-message)
- `agent.py` -- Claude Agent SDK brain (persistent sessions, MCP tools, subagents, slash command routing)
- `main.py` -- CLI entry point and command router (`ollim-bot` dispatches to bot, routines, reminders, tasks, cal, gmail)
- `prompts.py` -- System prompts for agent and subagents (extracted from agent.py)
- `agent_tools.py` -- MCP tools: `discord_embed`, `ping_user`, `follow_up_chain`, `save_context`, `report_updates`, `enter_fork`, `exit_fork`
- `forks.py` -- Fork state (bg + interactive), pending updates I/O, `run_agent_background`, `send_agent_dm`
- `views.py` -- Persistent button handlers via `DynamicItem` (delegates to google/, forks, and streamer)
- `storage.py` -- Shared JSONL I/O, markdown I/O (`read_md_dir`/`write_md`/`remove_md`), and git auto-commit (`~/.ollim-bot/` data repo)
- `streamer.py` -- Streams agent responses to Discord (throttled edits, 2000-char overflow)
- `sessions.py` -- Persists Agent SDK session ID (plain string file) + session history JSONL log (lifecycle events)
- `permissions.py` -- Discord-based tool approval (canUseTool callback, reaction-based approval, session-allowed set)
- `formatting.py` -- Tool-label formatting helpers (shared by agent and permissions)
- `config.py` -- Env vars: `OLLIM_USER_NAME`, `OLLIM_BOT_NAME` (loaded from `.env` via dotenv)
- `embeds.py` -- Embed/button types, builders, maps, and `build_embed`/`build_view` (shared by agent_tools and views)
- `inquiries.py` -- Persists button inquiry prompts to `~/.ollim-bot/inquiries.json` (7-day TTL)
- `google/` -- Google API integration sub-package
  - `auth.py` -- Shared Google OAuth2 (Tasks + Calendar + Gmail)
  - `tasks.py` -- Google Tasks CLI + API helpers (`complete_task`, `delete_task`)
  - `calendar.py` -- Google Calendar CLI + API helpers (`delete_event`)
  - `gmail.py` -- Gmail CLI (`ollim-bot gmail`, read-only)
- `scheduling/` -- Routines, reminders, and APScheduler sub-package
  - `routines.py` -- Routine dataclass and markdown I/O (recurring crons, `routines/*.md`)
  - `reminders.py` -- Reminder dataclass and markdown I/O (one-shot + chainable, `reminders/*.md`)
  - `scheduler.py` -- Proactive scheduling via APScheduler (syncs routines + reminders every 10s)
  - `routine_cmd.py` -- Routines CLI (`ollim-bot routine`)
  - `reminder_cmd.py` -- Reminders CLI (`ollim-bot reminder`)

## Agent SDK config
- Auth: Claude Code OAuth (no API key needed)
- Single `ClaudeSDKClient` for persistent conversation with auto-compaction (single-user bot)
- No `setting_sources` -- all config is in code (no CLAUDE.md, skills, or settings.json loaded)
- `permission_mode="default"` -- SDK default; whitelisted tools auto-approved, others routed through `permissions.py`
- Subagents defined programmatically via `AgentDefinition`: gmail-reader, history-reviewer, responsiveness-reviewer
- Tool instructions (tasks, cal, routines, reminders, embeds) inlined in SYSTEM_PROMPT; history delegated to subagent
- `ResultMessage.result` is a fallback — don't double-count with `AssistantMessage` text blocks
- `include_partial_messages=True` -- enables `StreamEvent` for real-time streaming
- `StreamEvent` imported from `claude_agent_sdk.types` (not in `__init__.__all__`)
- Session ID persisted to `~/.ollim-bot/sessions.json` (plain string, not JSON); `resume=session_id` on reconnect
- `_drop_client()`: set `_client = None` first, then interrupt + disconnect; suppresses `CLIConnectionError` on interrupt (subprocess may have exited)
- `swap_client(client, session_id)`: promotes forked client to main (avoids reconnect); drops old client
- Race guard: `save_session_id` skipped if `self._client is not client` (client was dropped mid-stream by `/clear` or `/model`)

## Discord slash commands
- `/clear` -- reset conversation (drop client + delete session ID)
- `/compact [instructions]` -- compress context via SDK's native `/compact`
- `/cost` -- show token usage via SDK's native `/cost`
- `/model <opus|sonnet|haiku>` -- switch model (update options + drop client, next message reconnects)
- `/fork [topic]` -- start interactive forked conversation
- `/interrupt` -- stop current response (fire-and-forget, no lock, silent)
- `/permissions <dontAsk|default|acceptEdits|bypassPermissions>` -- switch permission mode (fork-scoped); `dontAsk` is the default
- `Agent.slash()` -- generic method routing SDK slash commands, captures SystemMessage + AssistantMessage + ResultMessage
- `Agent.set_model()` -- uses `dataclasses.replace()` on shared options + updates live client
- `Agent.set_permission_mode()` -- fork-scoped: only updates active client (differs from `/model`)
- Synced via `bot.tree.sync()` in `on_ready`

## Discord embeds & buttons
- `discord_embed` MCP tool via `create_sdk_mcp_server` — Claude controls when to send embeds
- Channel reference stored in module-level `_channel` (agent_tools.py), set before each stream_chat()
- Button actions encoded in `custom_id`: `act:<action>:<data>` pattern
- Direct actions (task_done, task_del, event_del): call google/ API helpers directly, ephemeral response
- Agent inquiry (agent:<uuid>): stored prompts, route back through agent via views.py
- Fork actions (fork_save, fork_report, fork_exit): exit interactive fork with chosen strategy
- `DynamicItem[Button]` for persistent buttons across restarts
- Inquiry prompts persisted to `~/.ollim-bot/inquiries.json` (survive restarts, 7-day TTL)

## Session history
- `~/.ollim-bot/session_history.jsonl` -- append-only log of session lifecycle events
- Events: `created`, `compacted`, `swapped`, `cleared`, `interactive_fork`, `bg_fork`
- `save_session_id()` auto-detects `created` (no prior ID) and `compacted` (ID changed)
- `_swap_in_progress` flag prevents `save_session_id()` from logging `compacted` during `swap_client()`
- Fork session IDs captured from first `StreamEvent` (interactive) or `ResultMessage` (bg)
- Uses `storage.append_jsonl()` for writes (git auto-commit)

## Permissions
- Default mode is `dontAsk`: non-whitelisted tools silently denied, no Discord prompt
- `dontAsk` is our layer (`_dont_ask` flag in permissions.py); SDK stays at `default`
- Other modes (`default`, `acceptEdits`, `bypassPermissions`) clear `_dont_ask` and pass through to SDK
- Approval flow (when `dontAsk` is off): send message with tool label, add reactions (approve/deny/always), await Future (60s timeout, auto-deny)
- `canUseTool` callback: bg forks → immediate deny; `dontAsk` → silent deny (unless session-allowed); else → Discord approval
- `_session_allowed` set: shared across main + interactive forks, reset on `/clear`
- Permission mode is fork-scoped (only affects active client); `/model` is shared (affects both)
- `cancel_pending()` called on interrupt, fork exit, and `/clear`
- Channel sync invariant: every path into `stream_chat` must call BOTH `agent_tools.set_channel` AND `permissions.set_channel`
- 6 entry points: `_dispatch` (bot.py), `_check_fork_transitions` (bot.py), `slash_fork` (bot.py), `send_agent_dm` (forks.py), button handlers (views.py), `_check_fork_idle` (scheduler.py)

## Google integration
- OAuth credentials: `~/.ollim-bot/credentials.json` (from Google Cloud Console)
- Token: `~/.ollim-bot/token.json` (auto-generated on first auth)
- Gmail is read-only (`gmail.readonly` scope), accessed via the gmail-reader subagent
- Add new Google services: add scope to `google/auth.py`, create `google/*.py`, add commands to SYSTEM_PROMPT

## Routines & reminders
- Routines (recurring crons): `~/.ollim-bot/routines/<slug>.md` (YAML frontmatter + markdown body)
- Reminders (one-shot, chainable): `~/.ollim-bot/reminders/<slug>.md` (YAML frontmatter + markdown body)
- Each item is a separate .md file; filenames are human-readable slugs; `id` in YAML is authoritative
- Agent has Glob/Read/Write/Edit access to `reminders/**` and `routines/**` -- creates and manages files directly (no CLI)
- `~/.ollim-bot/` is a git repo; `storage.py` auto-commits on every add/remove
- Scheduler polls both directories every 10s, registers/removes APScheduler jobs
- Scheduler and streamer receive `owner: discord.User` (resolved once in bot.py `on_ready`)
- Cron day-of-week: standard cron (0=Sun) converted to APScheduler names via `_convert_dow()`
- CLI (`ollim-bot routine|reminder`) still works for human use and subagents
- Prompt tags: `[routine:ID]`, `[routine-bg:ID]`, `[reminder:ID]`, `[reminder-bg:ID]`
- Background mode: runs on forked session; text output discarded, agent uses `ping_user`/`discord_embed` to alert
- Forked sessions: `run_agent_background` creates disposable forked client (`fork_session=True`)
  - Always discarded — `save_context` blocked in bg forks (only available in interactive forks)
  - `report_updates(message)` MCP tool: persists summary to `~/.ollim-bot/pending_updates.json`
  - Not called: fork silently discarded, zero context bloat
  - Pending updates prepended to all interactions: main sessions pop (read + clear), forks peek (read-only)
- Bg forks run without `agent.lock()` — channel, chain context, and in_fork state scoped via `contextvars`
- Chain reminders: `max_chain: N` in YAML frontmatter enables follow-up chain; agent calls `follow_up_chain` MCP tool
- Chain state: scheduler injects chain context into prompt; silence = chain ends

## Interactive forks
- `/fork [topic]` or `enter_fork(topic?, idle_timeout=10)` MCP tool starts interactive fork
- Forks branch from main session (never nested); bg forks can run in parallel
- Three exit strategies via MCP tools or buttons:
  - `save_context`: promote fork to main session (interactive forks only, via `swap_client`)
  - `report_updates(message)`: queue summary, discard fork
  - `exit_fork`: clean discard, return to main session
- Fork state in `forks.py`: `_in_interactive_fork`, `_fork_exit_action`, `_fork_last_activity`, `_fork_prompted_at`
- Agent routing: `stream_chat`/`chat` route to `_fork_client` when active; `_prepend_context(clear=False)` for forks
- Post-stream transitions: `_check_fork_transitions()` in bot.py checks `enter_fork_requested()` and `pop_exit_action()`
- Idle timeout: scheduler checks every 60s; prompts agent after `idle_timeout` minutes; escalates to "you MUST exit" after another timeout (agent always decides exit strategy)
- Embed with buttons sent on fork entry (`_send_fork_enter`); exit embed sent on fork end (`_fork_exit_embed`)
- Button handlers in views.py: `fork_save`, `fork_report`, `fork_exit`

## Dev commands
```bash
uv sync                    # Install deps
uv run ollim-bot           # Run the bot
uv run pytest              # Run tests
```

Required env vars (set in `.env`): `DISCORD_TOKEN`, `OLLIM_USER_NAME`, `OLLIM_BOT_NAME`

## Principles

Read the `python-principles` skill when writing, reviewing, or refactoring Python code.

When rules conflict, follow this priority:
1. User's explicit request (they asked for it — build it)
2. Hard invariants (channel-sync, no circular deps — violation = runtime bug)
3. Code health rules below (violation = tech debt)
4. Product philosophy (guides your own proposals, not veto power over the user)

## Code health rules

**Hard invariants** (violation = bugs):
- **Channel-sync invariant** — every path into `stream_chat` must call BOTH `agent_tools.set_channel` AND `permissions.set_channel`. Check `_dispatch`, `_check_fork_transitions`, `slash_fork`, `send_agent_dm`, button handlers, and `_check_fork_idle`. Adding a new entry point without both calls is a runtime bug.

**Design rules** (violation = tech debt):
- **No utils/helpers/common files** — every function belongs in a domain module. If it belongs nowhere, you're missing a domain concept.
- **No catch-all directories** — name for what it does (`google/`, `scheduling/`), not what it is (`infra/`, `shared/`).
- **Max ~400 lines per file** — when approaching this, split by responsibility, because large files accumulate unrelated concerns that make changes risky. Check `wc -l` rather than relying on memorized counts.
- **No duplicate logic across modules** — if 2 modules implement the same pattern, note it. If 3 do, extract it. Extraction without adoption is worse than duplication, because it creates the illusion of shared code while each caller reinvents its own version.
- **One logging system** — `logging.getLogger(__name__)` for library code, `print()` only in CLI commands (`main.py`, `*_cmd.py`), because mixed systems make centralized log routing impossible and `print()` in library code pollutes test output.

## Plan mode
Before proposing the plan (ExitPlanMode), load the `python-principles` skill and re-review the plan to ensure it introduces no new violations.

## Useful skills
- `/design-principles` -- architecture decisions, boundary design, coupling analysis
- `/python-principles` -- Python code quality (also loaded in plan mode)
- `/improve-prompt` -- audit and improve agent prompts, system prompts, skill definitions
- `/learn-skill` -- capture a workflow into a reusable SKILL.md
- `/mermaid` -- generate architecture/flow diagrams as PNG
- `/claude-history` -- investigate past Claude Code sessions for decisions and context
