# Tool Permission System Revamp

**Status: Implemented** (2026-03-01)

All 5 phases completed. `disallowed_tools` fully removed. Key outcomes:
- `tool_policy.py`: validation, `MAIN_SESSION_TOOLS`, `MINIMAL_BG_TOOLS`, dynamic superset
- `subagents.py` + `subagents/*.md`: file-based subagent specs (deleted `subagent_prompts.py`)
- `skills.py`: `tools` field, `collect_skill_tools()` merged into job config
- `forks.py`: `BgForkConfig.from_item()` applies minimal defaults when no tools declared
- `agent.py`: 733 → 643 lines (hardcoded agents + allowed_tools removed)
- 431 tests passing, lint clean

## Context

The current tool permission system evolved in three separate layers — global permission mode (`permissions.py`), hardcoded SDK whitelist (`agent.py`), and per-job YAML overrides (`allowed_tools`/`disallowed_tools`). These layers are disconnected: 18 of 19 routines inherit the full parent tool set because no-config means no restrictions, subagent tools are hardcoded inline in `agent.py`, skills have no tool declarations, and there's no validation of dangerous patterns like `Bash(*)`. The goal is a unified model where every execution context explicitly declares its tools, with validation and principle of least privilege.

## Design Decisions

- **Explicit declaration**: Every level (main session, subagent, routine, reminder, webhook, skill) declares its own tool set
- **No blind inheritance**: No-config = minimal tools (report_updates, ping/embed if allow_ping, help)
- **Job is authoritative**: Each job gets exactly what it declares. No ceiling enforcement from parent — but validation blocks dangerous patterns
- **Dynamic superset**: SDK `allowed_tools` = union of all declared tool sets (so subagents can access their declared tools through the parent)
- **Validation at startup**: Block `Bash(*)`, bash chaining (`&&`, `||`, `;`, `|`), warn on overly broad wildcards
- **Approval model unchanged**: `dontAsk`/`default`/`acceptEdits`/`bypassPermissions` still work orthogonally
- **File-based subagent specs**: Source defaults in `src/ollim_bot/subagents/*.md`, runtime overrides in `~/.ollim-bot/subagents/*.md`
- **Skills declare tools**: `tools` field in SKILL.md, merged into host job's tool set when loaded

## Phases

Phases 1 and 2 can run in parallel. Each phase is a standalone PR.

```
Phase 1 (validation) ─┐
                       ├── Phase 3 (superset) ── Phase 4 (minimal defaults) ── Phase 5 (remove disallowed_tools)
Phase 2 (subagents) ──┘
                            Phase 2b (skill tools) ── ties into Phase 3
```

---

### Phase 1: `tool_policy.py` — Pattern Validation

New module. Pure functions, no state. Validates tool patterns and scans all declarations.

**New file**: `src/ollim_bot/tool_policy.py` (~100 lines)

```python
@dataclass(frozen=True, slots=True)
class ToolPatternError:
    pattern: str
    source: str      # "routine:heartbeat", "subagent:guide", "main"
    message: str
    severity: str    # "error" | "warning"

def validate_pattern(pattern: str) -> list[str]: ...
def validate_tool_set(patterns: list[str], source: str) -> list[ToolPatternError]: ...
def scan_all() -> list[ToolPatternError]: ...
```

**Validation rules**:
- `Bash(*)` → error (too broad)
- `Bash(cmd1 && cmd2)`, `Bash(cmd1 ; cmd2)`, `Bash(cmd1 | cmd2)` → error (chaining)
- `Read(*)` without path restriction → warning (overly broad)
- Empty pattern / malformed parens → error
- `mcp__discord__*`, `Read(**.md)`, `Bash(ollim-bot tasks *)` → valid

**Integration**: Call `scan_all()` in `Agent.__init__` before client creation (before `build_superset`). Validation runs before any tool set feeds into SDK options. Log warnings/errors. Don't block startup.

**Tests**: `tests/test_tool_policy.py` — bash star, chaining, valid patterns, broad wildcard warns, scan integration

**Files touched**: New `tool_policy.py`, minor edit to `agent.py` (add scan call in `__init__`)

---

### Phase 2: File-Based Subagent Specs

Move subagent definitions from inline Python to markdown files.

**New directory**: `src/ollim_bot/subagents/` (5 `.md` files)

Format:
```yaml
---
name: guide
description: "ollim-bot setup and usage guide..."
model: haiku
tools:
  - mcp__docs__*
  - Read(**.md)
  - Glob(**.md)
  - Bash(ollim-bot help)
  - Bash(ollim-bot routine list)
  - Bash(ollim-bot reminder list)
---
(system prompt body)
```

**New file**: `src/ollim_bot/subagents.py` (~100 lines)
- `SubagentSpec` frozen dataclass: name, description, model, tools, message
- `load_subagent_specs()` → loads source defaults, then overrides from `~/.ollim-bot/subagents/`
- `build_agent_definitions()` → converts specs to SDK `AgentDefinition` dict
- Override = full replacement (no partial merge)
- Template vars: `{USER_NAME}`, `{BOT_NAME}` expanded via `str.format_map()`

**Changes**:
- `agent.py`: Remove hardcoded `agents={...}` dict (L182-234, ~50 lines). Import and call `build_agent_definitions(load_subagent_specs())`.
- Delete `subagent_prompts.py` (427 lines) — prompts move into `.md` files

**Tests**: `tests/test_subagents.py` — parse, load, override, template expansion, missing fields

---

### Phase 2b: Skill Tool Dependencies

Add `tools` field to `Skill` dataclass. When a routine loads a skill, the skill's tools merge into the job's effective tool set.

**Changes**:
- `skills.py`: Add `tools: list[str] | None = None` to `Skill` dataclass. Parse from SKILL.md YAML frontmatter.
- `scheduling/preamble.py` (`_build_skills_section`): Return loaded skill objects (not just instruction text) so caller can access tool lists
- `scheduling/scheduler.py`: When building `BgForkConfig`, merge skill tools into the job's `allowed_tools`
- `agent_tools.py` (`ChainContext`): Propagate skill tool dependencies through chain reminders

**Tests**: Extend `tests/test_skills.py` — tools field parsing, merge into job tools

---

### Phase 3: Dynamic Superset Construction

Main agent's `allowed_tools` computed as union of all declared tool sets.

**Changes to `tool_policy.py`** (+30 lines):

```python
MAIN_SESSION_TOOLS: list[str] = [
    "Bash(ollim-bot tasks *)", "Bash(ollim-bot cal *)", "Bash(ollim-bot reminder *)",
    "Bash(ollim-bot gmail *)", "Bash(ollim-bot help)", "Bash(claude-history *)",
    "Read(**.md)", "Write(**.md)", "Edit(**.md)", "Glob(**.md)", "Grep(**.md)",
    "WebFetch", "WebSearch",
    "mcp__discord__discord_embed", "mcp__discord__ping_user",
    "mcp__discord__follow_up_chain", "mcp__discord__save_context",
    "mcp__discord__report_updates", "mcp__discord__enter_fork",
    "mcp__discord__exit_fork", "mcp__docs__*", "Task",
]

def collect_all_tool_sets() -> dict[str, list[str]]: ...  # main + subagents + routines + reminders + webhooks + skills
def build_superset(tool_sets: dict[str, list[str]]) -> list[str]: ...  # deduplicated union
```

**Changes to `agent.py`**:
- Replace hardcoded `allowed_tools=[...]` with `build_superset(collect_all_tool_sets())`
- ~20 lines changed (remove inline list, add import + call)

**Behavioral change**: None for current state — existing routines don't declare tools, so superset = `MAIN_SESSION_TOOLS` + subagent tools (same as today). But now any routine that adds `Bash(my-custom-tool)` to its YAML automatically enters the SDK ceiling.

**Tests**: `test_collect_all_tool_sets`, `test_build_superset_deduplicates`, `test_superset_includes_routine_tools`

---

### Phase 4: Minimal Defaults for No-Config Jobs (BREAKING)

Jobs without `allowed_tools` get minimal tools instead of inheriting the full set.

**Minimal default** (in `tool_policy.py`):
```python
MINIMAL_BG_TOOLS: list[str] = [
    "mcp__discord__report_updates",
    "mcp__discord__ping_user",
    "mcp__discord__discord_embed",
    "mcp__discord__follow_up_chain",
    "Bash(ollim-bot help)",
]
```

**Change in `forks.py`** (`BgForkConfig.from_item`):
```python
# When neither allowed_tools nor disallowed_tools is specified:
allowed = getattr(item, "allowed_tools", None)
blocked = getattr(item, "disallowed_tools", None)
if allowed is None and blocked is None:
    allowed = list(MINIMAL_BG_TOOLS)
```

**Add `allowed_tools`/`disallowed_tools` to `WebhookSpec`** — currently missing from the dataclass.

**Migration (prerequisite)**: 18 routines need explicit `allowed_tools` added before this code ships.
- Strategy: Have the bot agent audit each routine's prompt and add the right `allowed_tools`
- The agent knows what tools each routine actually uses from the prompt content
- One-shot task, produces 18 YAML edits to `~/.ollim-bot/routines/`

**Tests**: `test_bg_fork_config_applies_minimal_default`, `test_explicit_tools_not_overridden`, `test_minimal_with_allow_ping_false`

---

### Phase 5: Remove `disallowed_tools`

With explicit tool sets everywhere, `disallowed_tools` is redundant. Remove it entirely.

**Changes**:
- `scheduling/routines.py`: Remove `disallowed_tools` field from `Routine` dataclass
- `scheduling/reminders.py`: Remove `disallowed_tools` field from `Reminder` dataclass
- `forks.py`: Remove `disallowed_tools` from `BgForkConfig`. Remove from `from_item()`.
- `agent.py`: Remove `blocked` param from `_apply_tool_restrictions()`. Simplify to only handle `allowed`.
- `agent_tools.py`: Remove `disallowed_tools` from `ChainContext`
- `scheduling/scheduler.py`: Remove `disallowed_tools` branch from `_apply_ping_restrictions()`
- `scheduling/reminder_cmd.py`: Remove `--disallowed-tools` CLI arg
- `storage.py` / YAML parsing: Stop reading `disallowed_tools` from frontmatter (ignore if present for backwards compat)
- `tests/test_tool_restrictions.py`: Remove disallowed_tools test cases, add test that field is ignored in YAML
- Migrate any existing routines/reminders using `disallowed_tools` to explicit `allowed_tools` (check during Phase 4 migration)

---

## Open Questions

1. **`_HELP_TOOL` auto-inclusion**: Keep `Bash(ollim-bot help)` auto-included in `_apply_tool_restrictions()` — belt-and-suspenders safety net.
2. **Foreground routines/reminders**: Not affected — they run in the main session with full tools. `BgForkConfig` only applies to background jobs.
3. **Scan timing**: `scan_all()` runs in `Agent.__init__` before client creation. Runtime-added routines aren't scanned until restart. Acceptable for now.
4. **`agent.py` is 728 lines**: Already over the 400-line threshold. This plan reduces it by ~50 lines (subagent extraction) but doesn't solve the underlying problem. Separate concern.

## Verification

After each phase:
1. `uv run pytest` — all tests pass
2. `uv run ruff check && uv run ruff format --check` — lint clean
3. `uv run ty check` — type check clean
4. Manual: `uv run ollim-bot` — bot starts, agent connects, routines fire correctly
5. Phase 4 specifically: test a routine with and without `allowed_tools` to verify minimal defaults work

## Key Files

| File | Role in plan |
|------|-------------|
| `src/ollim_bot/tool_policy.py` | **New** — validation, superset, constants |
| `src/ollim_bot/subagents.py` | **New** — spec parser, loader, AgentDefinition builder |
| `src/ollim_bot/subagents/*.md` | **New** — 5 subagent spec files |
| `src/ollim_bot/agent.py` (728 lines) | Replace hardcoded allowed_tools + agents with dynamic construction |
| `src/ollim_bot/forks.py` (438 lines) | `BgForkConfig.from_item()` applies minimal defaults |
| `src/ollim_bot/skills.py` (109 lines) | Add `tools` field to Skill |
| `src/ollim_bot/webhook.py` (316 lines) | Add `allowed_tools`/`disallowed_tools` to WebhookSpec |
| `src/ollim_bot/subagent_prompts.py` (427 lines) | **Delete** — content moves to subagent spec files |
| `src/ollim_bot/scheduling/scheduler.py` (276 lines) | Skill tool merging in fire functions |
| `tests/test_tool_policy.py` | **New** — validation + superset tests |
| `tests/test_subagents.py` | **New** — spec parsing + loading tests |
