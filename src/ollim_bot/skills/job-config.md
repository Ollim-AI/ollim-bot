---
name: job-config
description: Determine tools and behavioral config for bg job creation
---

# Job Configuration

When creating or editing a routine, reminder, or webhook with background config,
use this skill to determine `allowed-tools` and behavioral settings BEFORE
writing the file.

## Discord tools are system-managed

**Never list discord MCP tools in `allowed-tools`.** The system automatically
gates `ping_user`, `discord_embed`, `report_updates`, and `follow_up_chain`
based on `allow_ping` and `update_main_session` flags. Listing them in
`allowed-tools` bypasses the safety gating.

## Step 1: Identify the job archetype

Match the job's purpose to a pattern and start with its baseline tools:

| Archetype | Signs | Baseline tools |
|-----------|-------|----------------|
| Email triage | reads email, triages inbox | `Task`, `Bash(ollim-bot tasks *)` |
| Dashboard | gathers data, sends summary embed | `Task`, `Read`, `Bash(ollim-bot *)` |
| Notification | nudges the user about something | `Read` |
| Maintenance | updates markdown files silently | `Read`, `Write(./**.md)`, `Edit(./**.md)` |
| Review/analysis | analyzes data, produces insights | `Read`, `Glob`, `Task` |
| Scheduler | creates reminders for later | `Bash(ollim-bot reminder *)` |

## Step 2: Add modifiers

Check each and add the tool if the job needs it:

- Manages Google Tasks? add `Bash(ollim-bot tasks *)`
- Checks calendar? add `Bash(ollim-bot cal *)`
- Manages reminders? add `Bash(ollim-bot reminder *)`
- Searches the web? add `WebSearch`
- Fetches a URL? add `WebFetch`
- Delegates to a subagent? add `Task`
- Writes/edits markdown files? add `Write(./**.md)`, `Edit(./**.md)`
- References a skill? add `Skill` and list under `skills:` in YAML
- Runs arbitrary shell commands? add `Bash` (avoid if a specific pattern suffices)

Prefer specific Bash patterns (`Bash(ollim-bot tasks *)`) over bare `Bash`.
Never use `Bash(*)`.

## Step 3: Set behavioral flags

| Flag | Default | When to change |
|------|---------|----------------|
| `allow_ping` | `true` | `false` for silent pollers, maintenance, and analysis jobs |
| `update_main_session` | `on_ping` | `blocked` for invisible jobs, `freely` for maintenance, `always` for critical briefings |
| `model` | (sonnet) | `haiku` for cheap polling, only specify when overriding |
| `skills` | (none) | list skill names the job needs to invoke |

## Step 4: Validate

- Prefer specific Bash patterns over bare `Bash`
- Jobs that write files need `Write(./**.md)` or `Edit(./**.md)`, not bare `Write`
- Jobs using `Task` for subagents must also have the subagent's tools
  covered (subagents have their own tool declarations)
- If `allow_ping: false`, the job cannot send pings or embeds
- If `update_main_session: blocked`, the job cannot call `report_updates`

## Tool reference

**CLI access (Bash patterns):**
- `Bash(ollim-bot tasks *)` -- Google Tasks CRUD
- `Bash(ollim-bot cal *)` -- Google Calendar queries
- `Bash(ollim-bot reminder *)` -- create/list/cancel reminders
- `Bash(ollim-bot gmail *)` -- email (read-only, prefer gmail-reader subagent)
- `Bash(claude-history *)` -- past session review

**File I/O:**
- `Read(./**.md)` -- read markdown (in DEFAULT_BG_TOOLS)
- `Glob(./**.md)` -- find files (in DEFAULT_BG_TOOLS)
- `Grep(./**.md)` -- search content (in DEFAULT_BG_TOOLS)
- `Write(./**.md)` -- create files (declare when needed)
- `Edit(./**.md)` -- modify files (declare when needed)

**Web:** `WebSearch`, `WebFetch`

**Meta:** `Task` (subagents), `Skill` (invoke skills)

## Output

Produce the `allowed-tools` list and any non-default behavioral flags for the
YAML frontmatter. Omit discord tools and fields that match defaults.
