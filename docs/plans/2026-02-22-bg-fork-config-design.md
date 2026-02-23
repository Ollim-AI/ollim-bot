# Bg Fork Config: `update_main_session` + `allow_ping`

Two new frontmatter fields for routines and reminders that control bg fork
behavior. Both are bg-only (ignored for foreground jobs).

## Fields

### `update_main_session` (str, default `"on_ping"`)

Controls whether the agent must call `report_updates` to update the main
session on what happened:

- `always`: stop hook blocks unless `report_updates` was called
- `on_ping` (default): stop hook blocks only if ping/embed was sent without
  reporting (current behavior)
- `freely`: stop hook never blocks
- `blocked`: `report_updates` returns error; stop hook never blocks

### `allow_ping` (bool, default `true`)

When `false`, `ping_user` and `discord_embed` both return errors in bg forks.
`critical=True` does NOT bypass -- author intent wins over agent runtime
judgment.

## Implementation

### 1. BgForkConfig contextvar (`forks.py`)

Frozen dataclass bundling the two settings, threaded via contextvar (same
pattern as `_busy_var`):

```python
@dataclass(frozen=True, slots=True)
class BgForkConfig:
    update_main_session: str = "on_ping"
    allow_ping: bool = True
```

Contextvar set in `run_agent_background` before `create_forked_client()` so it
propagates through the SDK's task group.

New `_bg_reported_flag` (mutable container, same pattern as `_bg_output_flag`)
for `always` mode -- set to `True` when `report_updates` succeeds in a bg fork.

### 2. Data model (`routines.py`, `reminders.py`)

Two new fields on `Routine` and `Reminder` dataclasses with defaults matching
current behavior.

### 3. Tool enforcement (`agent_tools.py`)

- `ping_user` / `discord_embed`: check `allow_ping` before busy/budget checks.
  Error: "Pinging is disabled for this background task."
- `report_updates`: check `update_main_session == "blocked"`.
  Error: "Reporting to main session is disabled for this background task."
- `require_report_hook` (stop hook):
  - `always`: block unless `_bg_reported_flag` is set
  - `on_ping`: current behavior (block if output sent without report)
  - `freely` / `blocked`: never block

### 4. Preamble (`scheduler.py`)

`_build_bg_preamble` receives `BgForkConfig` and adapts instructions:

- `allow_ping: false` -- omit ping instructions, state "Pinging is disabled."
- `always` -- "You MUST call `report_updates` before finishing to update the
  main session on what happened."
- `freely` -- "You may optionally call `report_updates` to update the main
  session on what happened -- or just finish without it."
- `blocked` -- "This task runs silently -- no reporting to the main session."
- `on_ping` (default) -- current text, with reason added: "to update the main
  session on what happened"

### 5. CLI (`routine_cmd.py`, `reminder_cmd.py`)

- `--update-main-session {always,on_ping,freely,blocked}` (default `on_ping`)
- `--no-ping` (sets `allow_ping=False`)
- `_fmt_schedule` shows non-default settings
- `ChainContext` gets both fields; `follow_up_chain` forwards them

### 6. Prompt and docs

- `SYSTEM_PROMPT`: document new frontmatter fields in routines/reminders tables
- `CLAUDE.md`: update routines/reminders sections

## Test plan

### `test_agent_tools.py`
- `ping_user` error when `allow_ping=False`
- `discord_embed` error when `allow_ping=False`
- `critical=True` still blocked when `allow_ping=False`
- `report_updates` error when `update_main_session=blocked`
- Stop hook blocks on `always` without report
- Stop hook allows on `always` with report
- Stop hook allows on `freely` with unreported output
- Stop hook allows on `blocked`

### `test_forks.py`
- `BgForkConfig` defaults
- `set_bg_fork_config` / `get_bg_fork_config` roundtrip
- `_bg_reported_flag` init/set/read

### `test_scheduler_prompts.py`
- Preamble with `allow_ping=False` omits ping instructions
- Preamble with `always` includes "MUST call report_updates"
- Preamble with `freely` includes "optionally"
- Preamble with `blocked` omits report_updates instructions

### `test_routines.py` / `test_reminders.py`
- Roundtrip serialization with new fields
- Defaults omitted from frontmatter
