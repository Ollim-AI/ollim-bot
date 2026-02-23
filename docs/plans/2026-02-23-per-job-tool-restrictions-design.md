# Per-Job Tool Restrictions — Design

## Problem

Background routines and reminders run with full tool access. The only restriction
is `allow_ping` (blocks ping_user/discord_embed). For jobs like email triage that
should only access gmail + tasks, there's no way to restrict the agent from using
calendar, web search, file editing, etc.

## Solution

Add `allowed_tools` / `disallowed_tools` to routine/reminder YAML frontmatter.
Uses SDK tool format directly — no abstraction layer, no group mapping.

## YAML examples

```yaml
# Allowlist: only these tools available
allowed_tools:
  - Bash(ollim-bot gmail *)
  - Bash(ollim-bot tasks *)
  - mcp__discord__report_updates
  - mcp__discord__ping_user
  - mcp__discord__discord_embed
```

```yaml
# Denylist: everything except these
disallowed_tools:
  - Bash(ollim-bot cal *)
  - WebFetch
  - WebSearch
```

## Design decisions

- **SDK format, no groups** — tool names match `ClaudeAgentOptions.allowed_tools`
  patterns exactly. Transparent, no mapping layer.
- **SDK enforcement** — `allowed_tools` maps to SDK `allowed_tools`, `disallowed_tools`
  maps to SDK `disallowed_tools`. Agent doesn't see restricted tools at all.
- **`allow_ping` stays separate** — it has rich behavior (critical bypass, budget,
  busy state) that the generic system can't replicate.
- **No essential tools** — only `Bash(ollim-bot help)` is automatically included
  when `allowed_tools` is specified.
- **bg-only** — like `model`, `thinking`, `isolated`. Foreground jobs use the main
  session's full tool set.
- **Mutually exclusive** — specifying both is a validation error (`__post_init__`).

## Data flow

```
Routine/Reminder YAML
  → _parse_md() → dataclass (allowed_tools, disallowed_tools)
  → scheduler._fire() → BgForkConfig(allowed_tools=..., disallowed_tools=...)
  → run_agent_background(bg_config=...)
  → create_isolated_client(allowed_tools=..., disallowed_tools=...)
  → _apply_tool_restrictions(opts, allowed, blocked)
  → replace(opts, allowed_tools=...) or replace(opts, disallowed_tools=...)
  → ClaudeSDKClient(modified_opts) → SDK enforces restrictions
```

Chain reminders inherit restrictions via `ChainContext` → `follow_up_chain` CLI
→ `--allowed-tools` / `--blocked-tools` flags → child `Reminder.new()`.
