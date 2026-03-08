# Permission System Redesign

Design document settling issues #13, #16, #17. Produced by agent team debate
(sdk-realist, ux-advocate, architect) — two rounds on 2026-03-08.

## Context

The permission system has two layers — an SDK layer (static, per-subprocess) and
an application layer (dynamic, runtime). A "superset" data structure in
`tool_policy.py` unions all declared tool sets and passes them as `allowed_tools`
to the SDK. Three issues pointed at friction:

- **#13**: Tool policy superset baked at startup; new routines can't expand it
- **#16**: `allowed-tools` in bg jobs error-prone (underspec = silent failure)
- **#17**: Default tool allowlists hardcoded; users can't customize

## Key SDK Findings

### 1. Each client is an independent subprocess

Each `ClaudeSDKClient` spawns its own CLI subprocess. `allowed_tools` becomes
`--allowedTools` CLI args — fully independent, no parent ceiling. Confirmed from
SDK source (`subprocess_cli.py:_build_command()`).

### 2. `allowed_tools` is pre-approval, not restriction

SDK docs: *"When you set allowed_tools=["Read", "Grep"], those tools are
auto-approved while tools not listed still exist and fall through to the
permission mode and canUseTool callback."*

Tools in `allowed_tools` **never trigger `canUseTool`**. They are auto-approved
at the CLI level. Tools NOT in `allowed_tools` fall through to the callback.

### 3. The two-layer architecture

| Layer | Mechanism | Scope | When it fires |
|-------|-----------|-------|---------------|
| **SDK (static)** | `allowed_tools` | Pre-approval per subprocess | Set once at client creation |
| **SDK (static)** | `disallowed_tools` | Hard deny | Always enforced, even in bypassPermissions |
| **App (dynamic)** | `canUseTool` callback | Runtime decisions | Only for tools NOT resolved by SDK layer |

SDK evaluation order: Hooks → deny rules (`disallowed_tools`) → permission mode
→ allow rules (`allowed_tools`) → `canUseTool` callback.

### 4. `dontAsk` does not exist in the Python SDK

The Python SDK's `PermissionMode` is `Literal["default", "acceptEdits", "plan",
"bypassPermissions"]`. The application layer's `_dont_ask` flag + silent deny in
`canUseTool` is a necessary reimplementation.

### 5. The superset made `canUseTool` dead code

By putting every declared tool in `allowed_tools`, the superset auto-approved
everything at the CLI level. `canUseTool` only fired for tools not in ANY
declared set — effectively dead code for normal operations. **Eliminating the
superset restores the intended two-layer design.**

## The Two Permission Layers — Detailed

### Layer 1: SDK (`allowed_tools` — static pre-approval)

Set once per `ClaudeSDKClient` via `ClaudeAgentOptions`. Tools matching these
patterns are auto-approved without calling `canUseTool`.

- **Main session**: `MAIN_SESSION_TOOLS` — bot's core tools (Read/Write/Edit
  `./**.md`, restricted Bash, MCP discord/docs tools, etc.)
- **Bg forks**: per-job tools via `BgForkConfig` + `apply_tool_restrictions()`
- **Interactive forks**: inherit main session options

### Layer 2: Application (`canUseTool` — dynamic runtime)

`handle_tool_permission()` in `permissions.py`. Only fires for tools NOT in
`allowed_tools`. Evaluation order (first match wins):

1. **State-dir write protection** — `Write`/`Edit` targeting `state/` → hard deny
2. **Bg fork gating** — `in_bg_fork()` contextvar:
   - Discord MCP tools → check `BgForkConfig` (`allow_ping`, `update_main_session`)
     per-call; allow or deny based on runtime config
   - Everything else → deny (not pre-approved = not available in bg forks)
3. **`_dont_ask` mode** — check `_session_allowed` → allow if present, else
   silent deny + record for strikethrough
4. **Ask mode** — check `_session_allowed` → allow if present, else Discord
   approval prompt (✅❌🔓, 60s timeout)

### How they interact

| Tool | Context | In `allowed_tools`? | `canUseTool` called? | User experience |
|------|---------|--------------------|--------------------|-----------------|
| `Write(routines/foo.md)` | Main | Yes (`Write(./**.md)`) | No | Invisible — tool executes |
| `Bash(git status)` | Main | No | Yes | dontAsk: strikethrough. Ask: Discord prompt |
| `mcp__discord__ping_user` | Main | Yes | No | Invisible — tool executes |
| `mcp__discord__ping_user` | Bg fork | No | Yes | Dynamic: allowed if `allow_ping=True` + budget |
| `mcp__discord__report_updates` | Bg fork | No | Yes | Dynamic: allowed if `update_main_session!="blocked"` |
| `Read(routines/foo.md)` | Bg fork | Yes (`Read(./**.md)`) | No | Invisible — tool executes |
| `Bash(rm -rf *)` | Main | No | Yes | dontAsk: strikethrough. Ask: Discord prompt |

The **gap** between "all tools the agent can attempt" and "tools in
`allowed_tools`" is what makes permission modes meaningful. Tools in the gap
go through `canUseTool` where dontAsk/ask mode routes them.

### `_session_allowed` — dynamic app-layer approval

When a user reacts with 🔓 in ask mode, the tool is added to `_session_allowed`.
This is checked inside `canUseTool` before mode routing — effectively a dynamic
extension of `allowed_tools`, but at the app layer (SDK doesn't support runtime
`allowed_tools` modification). Resets on `/clear`.

## Decisions

### 1. Eliminate the superset (unanimous)

**Delete** `build_superset()` and `collect_all_tool_sets()` from `tool_policy.py`
(~88 lines). The main session uses `MAIN_SESSION_TOOLS` directly:

```python
# agent.py, Agent.__init__
self.options = ClaudeAgentOptions(
    allowed_tools=tool_policy.MAIN_SESSION_TOOLS,
    ...
)
```

Bg forks already get their own `allowed_tools` via `BgForkConfig` +
`apply_tool_restrictions()`. Interactive forks inherit main session options.

**Issue #13 solved by elimination** — no superset ceiling means no stale ceiling.
New routines/reminders/webhooks created after startup get their own
`allowed_tools` on their bg fork client. Nothing to rebuild.

**This also restores the intended two-layer design**: tools in
`MAIN_SESSION_TOOLS` are pre-approved (SDK layer), everything else falls through
to `canUseTool` (app layer) where permission modes take effect.

Also delete the deferred imports of routines, reminders, subagents, webhooks
from `tool_policy.py` — they were only needed for `collect_all_tool_sets()`.

**Files changed:**
- `tool_policy.py`: delete `build_superset`, `collect_all_tool_sets`,
  `load_agent_tool_sets` if unused elsewhere (~88 lines)
- `agent.py`: simplify `__init__` to use `MAIN_SESSION_TOOLS` directly (~5 lines)

### 2. Expand bg fork defaults with read-only tools; discord tools fully dynamic (2-1, revised)

**Rename** `MINIMAL_BG_TOOLS` → `DEFAULT_BG_TOOLS`. Add read-only context tools.
**Remove** all discord MCP tools from the static list — they move to dynamic
`canUseTool` gating (see Decision 12):

```python
DEFAULT_BG_TOOLS: list[str] = [
    # CLI helpers
    "Bash(ollim-bot help)",
    "Bash(ollim-bot tasks *)",
    # Context reading (safe, read-only)
    # Patterns are relative to cwd (DATA_DIR = ~/.ollim-bot/).
    # ./**.md matches all .md files recursively — safe because:
    # - Scoped to DATA_DIR by cwd (cannot escape ~/.ollim-bot/)
    # - state/ contains only .json/.jsonl files, never .md
    # - Covers agent-created directories without pattern maintenance
    "Read(./**.md)",
    "Glob(./**.md)",
    "Grep(./**.md)",
]
```

**Pattern scoping**: Read/Edit patterns follow gitignore syntax (see SDK docs
"Permission rule syntax"). Four path types: `//abs` (filesystem root), `~/home`,
`/project-root`, `path` or `./path` (relative to cwd). `*` matches one
directory level, `**` matches recursively. All patterns here are bare paths
(relative to `cwd` = DATA_DIR = `~/.ollim-bot/`).

`Read(./**.md)` is safe for bg forks because: (1) `./` explicitly anchors to
cwd (DATA_DIR) — cannot escape `~/.ollim-bot/`, (2) `state/` contains only
`.json`/`.jsonl` files by convention, never `.md`, (3) covers agent-created
directories without requiring pattern maintenance.

`MAIN_SESSION_TOOLS` should also adopt `./` anchoring: `Write(./**.md)` /
`Edit(./**.md)` / `Read(./**.md)` etc. These could theoretically reach
`state/*.md` if `.md` files appeared there — Decision 10's PreToolUse hook
blocks writes to `state/` before `allowed_tools` matching fires.

`tool-policy.yaml` at DATA_DIR root is `.yaml`, not `.md` — not matched by
`./**.md` patterns, preventing bg forks from reading or modifying their own
tool policy.

Discord MCP tools (`report_updates`, `ping_user`, `discord_embed`,
`follow_up_chain`) are no longer statically pre-approved in bg forks. Instead,
they fall through to `canUseTool` where Decision 12's dynamic gating checks
`BgForkConfig` fields (`allow_ping`, `update_main_session`) per-call.

**Rationale**: Most bg forks need to read context (routines, reminders, task
lists) to do useful work. Read-only operations on known subdirectories are safe.
Withholding them forces every non-trivial routine to declare `allowed_tools`,
which is the error-prone pattern Issue #16 describes. Per-job `allowed_tools`
overrides still work for further expansion or narrowing. Discord tools need
dynamic gating because their availability depends on runtime state (ping budget,
busy flag, config), not static patterns.

**Files changed:**
- `tool_policy.py`: rename constant, add read-only patterns, remove discord tools (~5 lines)
- `fork_state.py`: delete `apply_ping_restrictions()` and
  `apply_reporting_restrictions()` (~30 lines), delete `_PING_TOOLS` and
  `_REPORTING_TOOLS` constants, update import reference

### 3. YAML tool config for non-technical users (revised — owner override)

**Issue #17 reopened.** The original "won't fix" assumed the user is also the
developer. For onboarding non-technical users, editing Python constants is not
acceptable. Introduce a `tool-policy.yaml` config file:

```yaml
# ~/.ollim-bot/tool-policy.yaml
# Agent + human managed. Agent proposes changes, human can edit directly.
# Merged with code constants — YAML entries extend (not replace) the defaults.

main_session:
  # Additional tools pre-approved for the main session (beyond MAIN_SESSION_TOOLS)
  additional_allowed: []
  # Tools to remove from MAIN_SESSION_TOOLS
  # remove: []

bg_forks:
  # Additional tools pre-approved for all bg forks (beyond DEFAULT_BG_TOOLS)
  additional_allowed: []
  # Override DEFAULT_BG_TOOLS entirely (if set, replaces the default list)
  # override: []
```

**Location**: `~/.ollim-bot/tool-policy.yaml` (DATA_DIR root, not `state/`).
State dir is write-protected for agent tools, but this file needs to be agent-
managed (the agent proposes tool additions when creating routines that need
non-default tools). DATA_DIR root is the natural home — same level as
`routines/`, `reminders/`, `webhooks/`.

**Merge semantics**: Code constants (`MAIN_SESSION_TOOLS`, `DEFAULT_BG_TOOLS`)
are the base. YAML `additional_allowed` extends. YAML `override` replaces (bg
forks only — main session always includes the base). This prevents users from
accidentally removing critical infrastructure tools.

**Agent workflow**: When the agent creates a routine needing tools beyond
`DEFAULT_BG_TOOLS`, it can either (a) add `allowed-tools` to the routine's
frontmatter (per-job), or (b) add to `tool-policy.yaml`'s
`bg_forks.additional_allowed` (global default). The YAML file is auto-committed
by the existing `auto_commit_hook`.

**Files changed:**
- `tool_policy.py`: add `load_yaml_config()`, merge with code constants (~25 lines)
- `agent.py`: call `load_yaml_config()` at init for main session tools (~3 lines)

### 4. Validate on dispatch (unanimous)

Move tool pattern validation from startup-only to dispatch-time. Before each
`run_agent_background` call, validate the job's `allowed_tools`:

```python
# scheduler.py, before run_agent_background:
errors = tool_policy.validate_tool_set(config.allowed_tools, source=routine.id)
if any(e.severity == "error" for e in errors):
    log.error("Skipping %s: invalid tool patterns", routine.id)
    return
```

Keep `scan_all()` at startup as a log-only early warning for existing files.
Dispatch validation catches routines created after startup.

**Files changed:**
- `scheduling/scheduler.py`: add validation before dispatch (~8 lines)

### 5. Do NOT add `disallowed_tools` for bg forks (unanimous in Round 2)

sdk-realist retracted this proposal. The `canUseTool` deny-all for bg forks
(`in_bg_fork()` check) is simple, reliable, and lets us control the denial
message the agent sees.

### 6. Keep all 4 permission modes (2-1, reversed from Round 1)

Keep `dontAsk`, `default`, `acceptEdits`, `bypassPermissions` in `/permissions`.

**Rationale**: Round 2 reversed the Round 1 tiebreaker. sdk-realist retracted
support for collapsing, noting these are SDK modes that map to real behavioral
differences. The cost of keeping 4 options in a Discord dropdown is minimal.
`acceptEdits` provides genuine granularity (auto-approve file edits, still prompt
for Bash).

### 7. Prompt-engineering fix for bg fork failures (unanimous)

Add to the bg fork preamble (`scheduling/preamble.py`):

```
If you cannot complete part of your task because a needed tool is unavailable,
mention this briefly in your report_updates message.
```

Makes silent tool failures visible through the agent's communication channel.

**Files changed:**
- `scheduling/preamble.py`: add instruction (~3 lines)

### 8. Make strikethrough denials actionable (unanimous)

Change denial rendering from:

```
-# *~~Write(foo.md)~~ — denied*
```

To:

```
-# *~~Write(foo.md)~~ — denied (use /permissions ask to approve)*
```

One string change that makes the denial self-documenting.

**Files changed:**
- `streamer.py` or `permissions.py`: update denial format string (~1 line)

### 9. Consolidate `_session_allowed` check (unanimous)

Pull the `is_session_allowed()` check to a single early location in
`handle_tool_permission()`, before mode routing. Remove the duplicate check
from `request_approval()`:

```python
async def handle_tool_permission(...) -> PermissionResult:
    # Hard security boundaries (state-dir moved to PreToolUse hook — Decision 10)
    # Bg fork gating (dynamic discord tools — Decision 12)
    if in_bg_fork():
        config = bg_fork_config()
        if tool_name in _DISCORD_MCP_TOOLS:
            if tool_name in _PING_TOOLS and not config.allow_ping:
                return PermissionResultDeny("pings disabled for this job")
            if tool_name in _REPORTING_TOOLS and config.update_main_session == "blocked":
                return PermissionResultDeny("reporting blocked for this job")
            return PermissionResultAllow()
        return PermissionResultDeny("not available in background forks")
    # Dynamic pre-approval (app-layer)
    if is_session_allowed(tool_name):
        return PermissionResultAllow()
    # Mode routing
    if _dont_ask:
        _denied_labels.add(...)
        return PermissionResultDeny(...)
    return await request_approval(tool_name, input_data)
```

Cleaner separation: `request_approval` becomes purely "Discord prompt + wait."
Bg fork gating is now 3 responsibilities: discord dynamic check, general deny,
and config-based routing.

**Files changed:**
- `permissions.py`: restructure check order (~5 lines moved)

### 10. Move state-dir write protection to PreToolUse hook (2-1)

The `_is_protected_path()` check in `canUseTool` is dead code for pre-approved
tools (`Write(./**.md)` / `Edit(./**.md)` in `MAIN_SESSION_TOOLS` skip `canUseTool`).
Move it to a `PreToolUse` hook, which fires at SDK step 1 — before
`allowed_tools` auto-approval.

```python
# hooks.py — new PreToolUse hook
async def state_dir_guard(input_data, tool_use_id, context):
    """Block Write/Edit to state/ directory."""
    tool_input = input_data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if file_path and _is_protected_path(file_path):
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "state/ is write-protected",
            }
        }
    return {}
```

Register alongside existing hooks:

```python
hooks={
    "PreToolUse": [HookMatcher(matcher="Write|Edit", hooks=[state_dir_guard])],
    "PostToolUse": [HookMatcher(matcher="Write|Edit", hooks=[auto_commit_hook])],
    ...
}
```

Remove `_is_protected_path` check from `handle_tool_permission()`. `canUseTool`
drops to 3 responsibilities: bg fork deny, dontAsk deny, Discord approval.

**Rationale**: Security boundaries shouldn't depend on file extension coincidence
(state/ currently has no `.md` files). PreToolUse hooks fire for ALL tools
regardless of `allowed_tools` — robust against future pattern changes. Same hook
pattern already used for auto-commit.

**Files changed:**
- `hooks.py`: add `state_dir_guard` PreToolUse hook (~15 lines)
- `agent.py`: register hook in hooks dict (~2 lines)
- `permissions.py`: remove `_is_protected_path` check (~5 lines removed)

### 12. Fully dynamic discord tool gating in bg forks (owner override)

**Remove** all discord MCP tools from `DEFAULT_BG_TOOLS` static pre-approval.
**Add** dynamic per-call gating in `canUseTool` based on `BgForkConfig` fields.
**Delete** `apply_ping_restrictions()` and `apply_reporting_restrictions()` from
`fork_state.py` — their logic moves into `canUseTool`.

The current system has triple-gating for bg fork discord tools:
1. Static `allowed_tools` (pre-approval at SDK layer)
2. Dynamic stripping (`apply_ping_restrictions` / `apply_reporting_restrictions`
   modify `allowed_tools` before client creation)
3. Tool-internal auth (`_check_bg_budget()`, busy state, `allow_ping` checks)

This collapses layers 1 and 2 into a single `canUseTool` dynamic check:

```python
# permissions.py, inside handle_tool_permission(), bg fork branch
_DISCORD_MCP_TOOLS = {
    "mcp__discord__ping_user",
    "mcp__discord__discord_embed",
    "mcp__discord__report_updates",
    "mcp__discord__follow_up_chain",
}
_PING_TOOLS = {"mcp__discord__ping_user", "mcp__discord__discord_embed"}
_REPORTING_TOOLS = {"mcp__discord__report_updates", "mcp__discord__follow_up_chain"}

if in_bg_fork():
    config = bg_fork_config()
    if tool_name in _DISCORD_MCP_TOOLS:
        if tool_name in _PING_TOOLS and not config.allow_ping:
            return PermissionResultDeny("pings disabled for this job")
        if tool_name in _REPORTING_TOOLS and config.update_main_session == "blocked":
            return PermissionResultDeny("reporting blocked for this job")
        return PermissionResultAllow()
    return PermissionResultDeny("not available in background forks")
```

**Layer 3 (tool-internal auth) stays** as defense-in-depth. The `canUseTool`
check is the policy gate (should this tool run?); tool-internal auth handles
runtime constraints (is there budget? is the user busy?). These are different
concerns — policy vs. resource management.

**Benefits:**
- Single place to understand bg fork tool availability (`canUseTool`)
- No more pre-dispatch mutations of `allowed_tools` lists
- Runtime config changes (e.g., mid-session `allow_ping` toggle) take effect
  immediately — no client restart needed
- `fork_state.py` drops ~30 lines and two functions

**Files changed:**
- `permissions.py`: add discord tool constants + dynamic gating (~15 lines)
- `fork_state.py`: delete `apply_ping_restrictions()`,
  `apply_reporting_restrictions()`, `_PING_TOOLS`, `_REPORTING_TOOLS` (~30 lines)
- `forks.py`: remove calls to `apply_ping_restrictions()` and
  `apply_reporting_restrictions()` before client creation (~4 lines)

### 14. Future: two-tier `allowed_tools` (deferred)

If finer-grained permission modes are wanted (e.g., `ask` mode should prompt
for `Write(./**.md)` too), the architecture supports splitting `MAIN_SESSION_TOOLS`
into `ALWAYS_ALLOWED` (MCP tools, infrastructure) and `STANDARD_TOOLS` (file
ops, Bash). In ask mode, only `ALWAYS_ALLOWED` goes into `allowed_tools`;
standard tools fall through to `canUseTool` for Discord approval.

Not implemented now — the current gap (declared vs undeclared tools) is
sufficient for the product's needs.

## Net Impact

| Module | Before | After | Change |
|--------|--------|-------|--------|
| `tool_policy.py` | 301 | ~245 | -56 (delete superset + collect, expand defaults, add YAML loader) |
| `permissions.py` | 201 | ~205 | +4 (remove state-dir check, consolidate session_allowed, add dynamic discord gating) |
| `hooks.py` | ~30 | ~45 | +15 (state_dir_guard PreToolUse hook) |
| `agent.py` | 471 | ~464 | -7 (simplify init, register hook, YAML config) |
| `fork_state.py` | 252 | ~222 | -30 (delete apply_ping/reporting_restrictions + constants) |
| `forks.py` | ~280 | ~276 | -4 (remove restriction calls before client creation) |
| `scheduling/scheduler.py` | ~210 | ~218 | +8 (dispatch validation) |
| `scheduling/preamble.py` | ~330 | ~333 | +3 (prompt fix) |
| `streamer.py` | 313 | ~314 | +1 (actionable hint) |
| **Total** | ~2388 | ~2322 | **-66 lines** |

## Issue Resolution Summary

| Issue | Resolution | Status |
|-------|-----------|--------|
| #13 Superset stale | Eliminated — each client independent, no ceiling | Solved |
| #16 Bg underspec | Expanded defaults + dynamic discord gating + dispatch validation + prompt fix | Solved |
| #17 Hardcoded tools | YAML tool config (`tool-policy.yaml`) for non-technical users | Solved |

## Verification Plan

1. Delete superset code, update agent init → `uv run pytest`
2. Expand `DEFAULT_BG_TOOLS` with read-only patterns (no discord tools) →
   `uv run pytest` (update test expectations)
3. Add `state_dir_guard` PreToolUse hook → test that Write to state/ is blocked
   even for pre-approved patterns
4. Add dispatch validation in scheduler → create a routine with invalid
   `allowed_tools`, verify it's skipped with log error
5. Update preamble → run a bg fork manually, verify tool denial is mentioned
   in `report_updates`
6. Update strikethrough rendering → trigger a denial in dontAsk mode, verify
   actionable hint appears
7. Consolidate `_session_allowed` check → verify ask mode approval still works,
   session-allowed persists across mode switches
8. Dynamic discord gating → test bg fork with `allow_ping=False` denies
   `ping_user`, `allow_ping=True` allows it. Test `update_main_session="blocked"`
   denies `report_updates`. Verify `apply_ping_restrictions` and
   `apply_reporting_restrictions` are deleted.
9. YAML tool config → create `tool-policy.yaml` with `additional_allowed`,
   verify merge with code constants. Test that `override` replaces
   `DEFAULT_BG_TOOLS`. Test that main session base tools can't be removed.
10. Full suite: `uv run ruff check && uv run ruff format --check && uv run ty check && uv run pytest`

## References

- [SDK Permission Rule Syntax](https://code.claude.com/docs/en/permissions#permission-rule-syntax) — `./` anchoring, gitignore spec, four path types (`//abs`, `~/home`, `/project-root`, `./cwd`). Source for `./**.md` pattern design.
- [SDK Permission System](https://code.claude.com/docs/en/permissions#permission-system) — evaluation order: Hooks → deny rules → permission mode → allow rules → canUseTool callback. Confirms `allowed_tools` is pre-approval, not restriction.
- [SDK Hooks Guide](https://code.claude.com/docs/en/hooks-guide) — PreToolUse hooks fire before the permission system and can deny tool calls. Basis for Decision 10.
- SDK source `subprocess_cli.py:_build_command()` — confirms each `ClaudeSDKClient` spawns independent subprocess with its own `--allowedTools` CLI args. No parent ceiling. Basis for Decision 1.
- `docs/design-philosophy.md` — product philosophy guiding UX decisions (dontAsk default, context quality as product).
- `docs/routine-reminder-spec.md` — `allowed-tools` frontmatter field for per-job tool overrides in routines/reminders.
