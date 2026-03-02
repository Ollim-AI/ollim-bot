# Claude Code Plugin Marketplace — Research & Fit Analysis

Research into whether the Claude Code plugin marketplace can extend ollim-bot's
routine system, and what alternatives align better with design philosophy.

## What the plugin marketplace is

The Claude Code plugin marketplace is a **decentralized distribution system** for
Claude Code extensions. Plugins are plain directories containing any combination
of: skills (`SKILL.md`), agents, commands, hooks (event handlers), MCP servers,
LSP servers, and output styles.

Marketplaces are git repos with a `.claude-plugin/marketplace.json` catalog. No
central store — anyone can host one. 9,000+ plugins exist across official and
community sources.

### Plugin structure

```
my-plugin/
├── .claude-plugin/plugin.json    # manifest (name, version, component paths)
├── skills/<name>/SKILL.md        # skill definitions
├── agents/<name>.md              # subagent system prompts
├── commands/<name>.md            # slash commands
├── hooks/hooks.json              # event handlers (PreToolUse, Stop, etc.)
├── .mcp.json                     # MCP server configs
├── .lsp.json                     # LSP server configs
└── settings.json                 # default settings
```

### Key capabilities

- **Installation**: `claude plugin install foo@marketplace` (CLI)
- **Programmatic loading**: `AgentDefinition(plugin_dirs=["./my-plugin"])` (SDK)
- **Hooks**: 25+ event types (PreToolUse, PostToolUse, Stop, SessionStart, etc.)
- **Scopes**: user, project, local, managed (admin-controlled)
- **Auto-updates**: Git-based, toggleable per marketplace
- **Private repos**: Supports `GITHUB_TOKEN` / SSH key auth

### What plugins can NOT do

- No scheduling — plugins are passive extensions, not jobs
- No execution runtime — they add capabilities, not behaviors
- No proactive outreach — no concept of pinging users
- No state machines — no chaining or follow-up logic
- No runtime config — no model/thinking overrides per execution

## Fit analysis

### Fundamental mismatch

| ollim-bot routines need | Plugin marketplace provides |
|---|---|
| Scheduled execution (cron / one-shot) | Passive extension loading |
| Bg fork with preamble injection | No execution runtime |
| `update_main_session`, `allow_ping`, budget | No proactive outreach concept |
| Chain reminders (`follow_up_chain`) | No chaining or state machine |
| Tool restrictions per job | Tool restrictions per skill (partial) |
| Model/thinking overrides per job | No runtime config |

Plugins add **capabilities** to Claude Code (tools, commands, skills). Routines
are **scheduled behaviors** with a rich execution model. Orthogonal layers.

### What IS adaptable

1. **Plugin format as routine packaging** — a "routine pack" could be a plugin
   directory containing `routines/*.md` files plus supporting skills/MCP tools.
   But routines go to `~/.ollim-bot/routines/`, not `~/.claude/plugins/`, so
   the installation flow doesn't apply.

2. **Skills from plugins could enhance routines** — a routine's prompt could
   reference skills installed via plugin marketplace. E.g., a "code review"
   plugin installs a skill, and a nightly routine invokes it. This works today
   without changes.

3. **Hooks for routine lifecycle** — plugin hooks (Stop, PostToolUse) could
   theoretically intercept routine events. But ollim-bot uses the Agent SDK
   directly, not Claude Code's hook system. The bot already has
   `require_report_hook` for this.

## Alternatives

### A. Routine templates (recommended, zero infrastructure)

Curate a `templates/` directory with example routine `.md` files. Users copy
them to `~/.ollim-bot/routines/`. Already works today — the file format is
self-describing (YAML frontmatter + markdown body).

```
ollim-bot/templates/routines/
  morning-standup.md
  email-triage.md
  eod-review.md
  weekly-planning.md
```

**Philosophy alignment**: files as shared language, no new surfaces, no
abstraction layer. The agent can also install them conversationally.

### B. `ollim-bot routine install <url|path>` CLI command

Copy a routine from URL or local path into `~/.ollim-bot/routines/`, validate
YAML, git-commit. Accepts local paths, raw URLs, or `github:user/repo/file.md`.

Respects file-based model while adding discoverability. Right-sized step for
shareability. Not needed until routines are actually being shared.

### C. Routine packs via git clone

A git repo with standard layout (`routines/*.md`, `reminders/*.md`), installed
via `ollim-bot pack install github:user/repo`. Git-native, versioned, shareable.

Dangerously close to the "Hook System (Event-Driven Plugins)" already rejected
in `feature-brainstorm.md` as premature abstraction.

### D. Agent-authored routines (status quo, strongest option)

The agent already has full file access to `routines/**` and `reminders/**`. It
creates routines conversationally with full context. For a single-user bot, the
agent IS the extensibility system.

**The marketplace solves distribution across users, but ollim-bot is single-user
by design.** The agent authoring routines on the fly is more powerful than any
template system because it's contextual.

## Decision

**Don't adopt the plugin marketplace.** The execution model mismatch is
fundamental. Wrapping routines in plugin packaging adds complexity without value
for a single-user system.

The rejected "Hook System" entry in `feature-brainstorm.md` captures the right
instinct: the codebase is small enough that direct code changes beat abstraction
layers.

**What to invest in instead:**

1. **Routine templates** (option A) — curate examples for onboarding / fork
   users. Zero infrastructure, pure files, philosophically aligned.
2. **Agent-authored routines** (option D) — remains the primary path. The
   agent's contextual understanding of user needs produces better routines than
   any template.
3. **`routine install` CLI** (option B) — right-sized next step IF sharing
   becomes a real need. Not worth building speculatively.
