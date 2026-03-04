# ollim-bot

ADHD-friendly Discord bot with proactive reminders, powered by Claude.

## Product philosophy

See `docs/design-philosophy.md` for the full rationale. Core beliefs, in priority order:

1. **Context quality is the product** — wrong information is worse than missing; prefer asking over assuming.
2. **Proactive over reactive** — the bot reaches out; features that wait to be invoked solve nothing.
3. **Meet the user where they are** — integrate with existing tools, don't add new surfaces.
4. **Files as shared language** — markdown for human+agent data, JSONL for code-only. No databases.
5. **Single-user by design** — serve one human deeply. Others fork the repo.

Quality over breadth, real-use grounded. These guide your own proposals — when the user explicitly requests a feature, build it.

## Directory layout

Two separate trees — never mix them:

| Path | Purpose | Git repo? |
|------|---------|-----------|
| This repo | Source code | yes |
| `~/.ollim-bot/` (`DATA_DIR`) | Agent working data (routines, reminders, webhooks, state) | yes (auto-committed) |

`DATA_DIR` subdivisions:
- `routines/`, `reminders/`, `webhooks/`, `skills/` — agent-managed markdown files
- `state/` (`STATE_DIR`) — code-only infrastructure (sessions, ping budget, inquiries, tokens)

Never write working data into the source repo or source code into `~/.ollim-bot/`.

## Architecture
- `bot.py` -- Discord interface (DMs, @mentions, slash commands, reaction ack, interrupt-on-new-message)
- `agent.py` -- Claude Agent SDK brain (persistent sessions, MCP tools, subagents, slash command routing)
- `agent_streaming.py` -- `stream_response()` free function: streaming loop, auto-compaction retry, fallback tiers, fork interrupt (tested independently)
- `agent_context.py` -- Message context helpers: `timestamp`, `prepend_context`, `format_compact_stats`, `thinking()`, `ModelName`
- `main.py` -- CLI entry point and command router (`ollim-bot` dispatches to bot, routines, reminders, tasks, cal, gmail)
- `auth.py` -- Claude CLI auth via bundled Agent SDK CLI (`is_authenticated`, `start_login`, `ollim-bot auth` subcommands)
- `prompts.py` -- System prompt for the main agent and fork prompt helpers
- `subagents.py` -- Bundled agent installation (`install_agents`) and tool-set extraction (`load_agent_tool_sets`) for policy validation; specs in `subagents/*.md`
- `agent_tools.py` -- MCP tools: `discord_embed`, `ping_user`, `follow_up_chain`, `save_context`, `report_updates`, `enter_fork`, `exit_fork`
- `hooks.py` -- Agent SDK hooks: `auto_commit_hook` (PostToolUse — auto-commits .md file changes in DATA_DIR)
- `channel.py` -- DM channel reference, set once at startup (`init_channel`/`get_channel`)
- `webhook.py` -- Webhook HTTP server for external triggers (aiohttp, auth, validation, Haiku screening, dispatch)
- `fork_state.py` -- Pure fork state: enums (`ForkExitAction`), dataclasses (`BgForkConfig`), contextvars, accessors (zero internal imports — leaf dependency)
- `forks.py` -- Fork I/O: pending updates, `run_agent_background`, `send_agent_dm` (state moved to `fork_state.py`)
- `views.py` -- Persistent button handlers via `DynamicItem` (delegates to google/, forks, and streamer)
- `storage.py` -- Shared JSONL I/O, markdown I/O (`read_md_dir`/`write_md`/`remove_md`), git auto-commit, and path constants (`DATA_DIR` for agent workspace, `STATE_DIR` for code-only infrastructure in `~/.ollim-bot/state/`)
- `streamer.py` -- Streams agent responses to Discord (throttled edits, 2000-char overflow, tool label rendering with denial strikethrough)
- `sessions.py` -- Persists Agent SDK session ID (plain string file) + session history JSONL log (lifecycle events)
- `permissions.py` -- Discord-based tool approval (canUseTool callback, reaction-based approval, session-allowed set)
- `formatting.py` -- Tool-label formatting helpers (shared by agent and permissions)
- `config.py` -- Env vars: `OLLIM_USER_NAME`, `OLLIM_BOT_NAME` (loaded from `.env` via dotenv)
- `embeds.py` -- Embed/button types, builders, maps, and `build_embed`/`build_view` (shared by agent_tools and views)
- `inquiries.py` -- Persists button inquiry prompts to `~/.ollim-bot/state/inquiries.json` (7-day TTL)
- `ping_budget.py` -- Refill-on-read ping budget for bg fork notifications (state, enforcement, status formatting)
- `runtime_config.py` -- Persistent runtime configuration (`~/.ollim-bot/state/config.json`): model/thinking per context, timeouts, permission mode
- `skills.py` -- Skill data model and directory-based persistence (`skills/*/SKILL.md`), skill index builder for system prompt
- `updater.py` -- Git-based auto-update: fetch, compare, pull (`--ff-only`), `uv sync`, restart via `os.execv`
- `google/` -- Google API integration sub-package
  - `auth.py` -- Shared Google OAuth2 (Tasks + Calendar + Gmail)
  - `tasks.py` -- Google Tasks CLI + API helpers (`complete_task`, `delete_task`)
  - `calendar.py` -- Google Calendar CLI + API helpers (`delete_event`)
  - `gmail.py` -- Gmail CLI (`ollim-bot gmail`, read-only)
- `scheduling/` -- Routines, reminders, and APScheduler sub-package
  - `routines.py` -- Routine dataclass and markdown I/O (recurring crons, `routines/*.md`)
  - `reminders.py` -- Reminder dataclass and markdown I/O (one-shot + chainable, `reminders/*.md`)
  - `preamble.py` -- Bg preamble and forward schedule builder for bg fork prompts
  - `scheduler.py` -- Proactive scheduling via APScheduler (syncs routines + reminders every 10s)
  - `routine_cmd.py` -- Routines CLI (`ollim-bot routine`)
  - `reminder_cmd.py` -- Reminders CLI (`ollim-bot reminder`)

## Agent SDK config
- Auth: Claude Code OAuth (no API key needed)
- Single `ClaudeSDKClient` for persistent conversation with auto-compaction
- `setting_sources=["project"]` — SDK loads agents and skills from `.claude/` (relative to `cwd=DATA_DIR`)
- Two MCP servers: `discord` (agent_tools.py — 7 tools) and `docs` (remote, `docs.ollim.ai/mcp`)
- Subagents: bundled specs in `src/ollim_bot/subagents/*.md`, installed to `~/.ollim-bot/.claude/agents/` at init (skip existing)
- `ResultMessage.result` is a fallback — don't double-count with `AssistantMessage` text blocks

### SDK behavioral gotchas
- Auto-compaction: CLI sends `compact_boundary` + `ResultMessage` then **waits for a new `query()`** — it does NOT auto-continue. Code must re-send the message.
- `_compacting` flag: set during post-compaction re-send; `bot.py` skips interrupt when True (interrupt during compaction kills the response)
- `_drop_client()`: set `_client = None` first, then interrupt + disconnect; suppresses `CLIConnectionError` (subprocess may have exited)
- `swap_client(client, session_id)`: promotes forked client to main (avoids reconnect); drops old client
- Race guard: `save_session_id` skipped if `self._client is not client` (dropped mid-stream by `/clear` or `/model`)
- `_swap_in_progress` flag prevents `save_session_id()` from logging `compacted` during `swap_client()`
- `StreamEvent` imported from `claude_agent_sdk.types` (not in `__init__.__all__`)
- `ThinkingConfig` imported from `claude_agent_sdk.types` — TypedDicts: `{"type": "enabled", "budget_tokens": N}`, `{"type": "disabled"}`, `{"type": "adaptive"}`
- `thinking: ThinkingConfig` preferred over deprecated `max_thinking_tokens`; `thinking(enabled, budget)` helper in `agent_context.py`

## Discord slash commands
- `/clear` -- reset conversation (drop client + delete session ID)
- `/compact [instructions]` -- compress context via SDK's native `/compact`
- `/cost` -- show token usage via SDK's native `/cost`
- `/model <opus|sonnet|haiku>` -- switch model (drop client, next message reconnects)
- `/thinking <on|off>` -- toggle extended thinking (drop client, next message reconnects)
- `/fork [topic]` -- start interactive forked conversation
- `/interrupt` -- stop current response (fire-and-forget, no lock, silent)
- `/permissions <dontAsk|default|acceptEdits|bypassPermissions>` -- switch permission mode (fork-scoped)
- `/ping-budget [capacity] [refill_rate]` -- view or configure ping budget
- `/config [key] [value]` -- view or set persistent runtime config
- `/update` -- check for updates and apply immediately (ignores hour window)
- `/restart` -- restart the bot process immediately
- Synced via `bot.tree.sync()` in `on_ready`

## Discord embeds & buttons
- `discord_embed` MCP tool — Claude controls when to send embeds
- Button actions encoded in `custom_id`: `act:<action>:<data>` pattern
- `DynamicItem[Button]` for persistent buttons across restarts
- Inquiry prompts persisted to `~/.ollim-bot/state/inquiries.json` (survive restarts, 7-day TTL)

## Permissions
- Default mode is `dontAsk`: non-whitelisted tools denied with strikethrough, no Discord prompt
- `dontAsk` is our layer (`_dont_ask` flag in permissions.py); SDK stays at `default`
- Permission mode is fork-scoped (only affects active client); `/model` is shared
- `_session_allowed` set: shared across main + interactive forks, reset on `/clear`

## Ping budget
See `SearchOllimBot` for full mechanics. Key rules:
- Scope: bg forks only — main session and interactive fork pings are never counted
- `critical=True` bypasses budget but is tracked
- Quiet when busy: `_busy` contextvar set when `agent.lock()` held; non-critical pings return errors

## Routines & reminders
Format spec: `docs/routine-reminder-spec.md`. Key implementation details:
- Files: `~/.ollim-bot/routines/<slug>.md` and `reminders/<slug>.md` (YAML frontmatter + markdown)
- Agent manages files directly (Glob/Read/Write/Edit) — no CLI required
- Scheduler polls both directories every 10s, registers/removes APScheduler jobs
- Background forks: `run_agent_background` creates disposable forked client (`fork_session=True`)
  - `save_context` blocked in bg forks (only available in interactive forks)
  - `report_updates(message)` persists summary; pending updates prepended to all interactions (main pops, forks peek)
  - Tool restrictions: `allowed-tools` in YAML overrides SDK `allowed_tools`; no declaration → `MINIMAL_BG_TOOLS`
  - SDK enforcement via `apply_tool_restrictions()` in `tool_policy.py`
- Quiet when busy: bg forks always run; non-critical `ping_user`/`discord_embed` return errors when `agent.lock()` held. `critical=True` bypasses.
- Bg forks run without `agent.lock()` — channel, chain context, in_fork, busy state, and bg_fork_config scoped via `contextvars`

## Interactive forks
- `/fork [topic]` or `enter_fork(topic?, idle_timeout=10)` MCP tool; forks branch from main session (never nested)
- Three exit strategies: `report_updates(message)` (default), `exit_fork` (clean discard), `save_context` (promote to main via `swap_client`)
- Idle timeout: scheduler checks every 60s; prompts agent, then escalates
- Reply-to-fork: replying to a bg fork message resumes that fork's session (7-day TTL in `fork_messages.json`)

## Webhooks
Spec format: `docs/webhook-spec.md`. Dispatch via `run_agent_background` (same bg fork path as scheduler).

## Skills
Spec format: `docs/skill-spec.md`. SDK discovers via `~/.ollim-bot/.claude/skills/` symlink. Per-job injection via `build_skills_section()`.

## Google integration
- OAuth credentials: `~/.ollim-bot/state/credentials.json` (from Google Cloud Console)
- Token: `~/.ollim-bot/state/token.json` (auto-generated on first auth)
- Gmail is read-only (`gmail.readonly` scope), accessed via the gmail-reader subagent
- Add new Google services: add scope to `google/auth.py`, create `google/*.py`, add commands to SYSTEM_PROMPT

## Dev commands
```bash
uv sync                    # Install deps
uv tool install --editable . # Install/update global `ollim-bot` + `claude-history` commands (editable = picks up uv sync changes)
uv run ollim-bot           # Run the bot
uv run pytest              # Run tests
uv run ruff check          # Lint
uv run ruff format         # Format
uv run ty check            # Type check
```

Pre-commit hooks (ruff lint, ruff format, ty) run automatically on commit.

Required env vars (set in `.env`): `DISCORD_TOKEN`, `OLLIM_USER_NAME`, `OLLIM_BOT_NAME`

Optional env vars:
- `OLLIM_TIMEZONE` — IANA timezone (default: auto-detected from system)
- `WEBHOOK_PORT` — enable webhook server (e.g. `8420`)
- `WEBHOOK_SECRET` — required if `WEBHOOK_PORT` is set

## Auto-update
- Config: `auto_update` (bool, default off), `auto_update_interval` (int minutes, default 60), `auto_update_hour` (int 0-23, default 6)
- Scheduler polls every 5 min; actual check respects `auto_update_interval`; apply gated on `auto_update_hour` match
- Flow: `git fetch` → compare HEAD vs tracking branch → wait for hour window → `git pull --ff-only` → `uv sync` → DM owner → `os.execv`
- `/update` bypasses the hour gate and applies immediately; `/restart` restarts without updating
- Safety: deferred when `agent.lock()` held; `--ff-only` rejects diverged branches
- `os.execv` replaces process in-place (same PID); PID file deleted before exec (atexit doesn't fire)
- Logs `restarting` event to `session_history.jsonl` before restart

## Principles

Read the `python-principles` skill when writing, reviewing, or refactoring Python code.
Read the `ux-principles` skill when designing user-facing features, notifications, or bot responses.
Read the `design-principles` skill when planning architecture or reviewing design decisions.

When rules conflict, follow this priority:
1. User's explicit request (they asked for it — build it)
2. Code health rules below (violation = tech debt)
3. Product philosophy (guides your own proposals, not veto power over the user)

## Code health rules
- **No utils/helpers/common files** — every function belongs in a domain module. If it belongs nowhere, you're missing a domain concept.
- **No catch-all directories** — name for what it does (`google/`, `scheduling/`), not what it is (`infra/`, `shared/`).
- **Max ~400 lines per file** — when approaching this, split by responsibility, because large files accumulate unrelated concerns that make changes risky. Check `wc -l` rather than relying on memorized counts.
- **No duplicate logic across modules** — if 2 modules implement the same pattern, note it. If 3 do, extract it. Extraction without adoption is worse than duplication, because it creates the illusion of shared code while each caller reinvents its own version.
- **One logging system** — `logging.getLogger(__name__)` for library code, `print()` only in CLI commands (`main.py`, `*_cmd.py`), because mixed systems make centralized log routing impossible and `print()` in library code pollutes test output.

## Plan mode
Before proposing the plan (ExitPlanMode), load the `python-principles` skill and re-review the plan to ensure it introduces no new violations. For feature plans, consider loading `feature-development` for the phased approach.

## Documentation
- `SearchOllimBot` MCP tool — search `docs.ollim.ai` for architecture, conventions, and integration patterns. Use for "how does X work" or "how to add Y" questions; use code exploration for implementation details and debugging.

## Useful skills
- `/feature-development` -- guided feature dev: explore, clarify, architect, implement, review
- `/systematic-debugging` -- root-cause debugging: investigate, analyze, hypothesize, fix
- `/code-review` -- two-stage review: project compliance + code quality (confidence >= 80)
- `/context-engineering-principles` -- LLM context pipelines, prompt design, information flow
- `/design-principles` -- architecture decisions, boundary design, coupling analysis
- `/python-principles` -- Python code quality (also loaded in plan mode)
- `/ux-principles` -- user-facing design, notifications, proactive outreach, bot responses
- `/async-principles` -- concurrency, fork state, locks, contextvars, file I/O atomicity
- `/improve-prompt` -- audit and improve agent prompts, system prompts, skill definitions
- `/learn-skill` -- capture a workflow into a reusable SKILL.md
- `/mermaid` -- generate architecture/flow diagrams as PNG
- `/claude-history` -- investigate past Claude Code sessions for decisions and context
