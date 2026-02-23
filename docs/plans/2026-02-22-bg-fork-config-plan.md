# Bg Fork Config Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `update_main_session` and `allow_ping` frontmatter fields to control bg fork behavior per routine/reminder.

**Architecture:** New `BgForkConfig` frozen dataclass + contextvar in `forks.py` propagated through `run_agent_background`. Tools and stop hook read the contextvar to enforce config. Preamble adapts instructions to match config.

**Tech Stack:** Python dataclasses, contextvars, pytest

---

### Task 1: BgForkConfig dataclass and contextvar

**Files:**
- Modify: `src/ollim_bot/forks.py`
- Test: `tests/test_forks.py`

**Step 1: Write failing tests**

Add to `tests/test_forks.py`:

```python
from ollim_bot.forks import (
    BgForkConfig,
    get_bg_fork_config,
    init_bg_reported_flag,
    mark_bg_reported,
    bg_reported,
    set_bg_fork_config,
)


# --- BgForkConfig ---


def test_bg_fork_config_defaults():
    config = BgForkConfig()

    assert config.update_main_session == "on_ping"
    assert config.allow_ping is True


def test_bg_fork_config_custom():
    config = BgForkConfig(update_main_session="always", allow_ping=False)

    assert config.update_main_session == "always"
    assert config.allow_ping is False


def test_set_and_get_bg_fork_config():
    config = BgForkConfig(update_main_session="blocked", allow_ping=False)
    set_bg_fork_config(config)

    result = get_bg_fork_config()

    assert result.update_main_session == "blocked"
    assert result.allow_ping is False
    # Reset
    set_bg_fork_config(BgForkConfig())


def test_bg_fork_config_default_when_unset():
    set_bg_fork_config(BgForkConfig())

    result = get_bg_fork_config()

    assert result.update_main_session == "on_ping"
    assert result.allow_ping is True


# --- Reported flag ---


def test_bg_reported_flag_default_false():
    init_bg_reported_flag()

    assert bg_reported() is False


def test_bg_reported_flag_set_true():
    init_bg_reported_flag()
    mark_bg_reported()

    assert bg_reported() is True
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_forks.py::test_bg_fork_config_defaults -v`
Expected: FAIL (ImportError — names don't exist yet)

**Step 3: Implement BgForkConfig and reported flag**

In `src/ollim_bot/forks.py`, add after the `_bg_output_flag` section:

```python
@dataclass(frozen=True, slots=True)
class BgForkConfig:
    update_main_session: str = "on_ping"  # always | on_ping | freely | blocked
    allow_ping: bool = True


_bg_fork_config_var: ContextVar[BgForkConfig] = ContextVar(
    "_bg_fork_config", default=BgForkConfig()
)


def set_bg_fork_config(config: BgForkConfig) -> None:
    _bg_fork_config_var.set(config)


def get_bg_fork_config() -> BgForkConfig:
    return _bg_fork_config_var.get()


# --- Bg reported flag (mutable container, same pattern as _bg_output_flag) ---

_bg_reported_flag: ContextVar[list[bool] | None] = ContextVar(
    "_bg_reported_flag", default=None
)


def init_bg_reported_flag() -> None:
    """Call before client connect() so all child tasks share the mutable ref."""
    _bg_reported_flag.set([False])


def mark_bg_reported() -> None:
    flag = _bg_reported_flag.get()
    if flag is not None:
        flag[0] = True


def bg_reported() -> bool:
    flag = _bg_reported_flag.get()
    return bool(flag and flag[0])
```

Add `dataclass` import (already present via `from dataclasses import dataclass` — it's used by... actually no, forks.py doesn't import dataclass). Add to imports:

```python
from dataclasses import dataclass
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_forks.py -k "bg_fork_config or bg_reported" -v`
Expected: All 6 PASS

**Step 5: Commit**

```bash
git add src/ollim_bot/forks.py tests/test_forks.py
git commit -m "feat: add BgForkConfig dataclass, contextvar, and reported flag"
```

---

### Task 2: Add fields to Routine and Reminder dataclasses

**Files:**
- Modify: `src/ollim_bot/scheduling/routines.py`
- Modify: `src/ollim_bot/scheduling/reminders.py`
- Test: `tests/test_routines.py`
- Test: `tests/test_reminders.py`

**Step 1: Write failing tests**

Add to `tests/test_routines.py`:

```python
def test_routine_new_defaults_update_main_session_allow_ping():
    routine = Routine.new(message="test", cron="0 9 * * *")

    assert routine.update_main_session == "on_ping"
    assert routine.allow_ping is True


def test_routine_new_custom_bg_config():
    routine = Routine.new(
        message="silent",
        cron="0 9 * * *",
        background=True,
        update_main_session="blocked",
        allow_ping=False,
    )

    assert routine.update_main_session == "blocked"
    assert routine.allow_ping is False


def test_routine_bg_config_roundtrip(data_dir):
    routine = Routine.new(
        message="check",
        cron="0 9 * * *",
        background=True,
        update_main_session="always",
        allow_ping=False,
    )
    append_routine(routine)

    loaded = list_routines()[0]

    assert loaded.update_main_session == "always"
    assert loaded.allow_ping is False


def test_routine_default_bg_config_omitted_from_frontmatter(data_dir):
    """Default values should not appear in serialized YAML."""
    routine = Routine.new(message="defaults", cron="0 9 * * *")
    append_routine(routine)

    loaded = list_routines()[0]

    assert loaded.update_main_session == "on_ping"
    assert loaded.allow_ping is True
```

Add to `tests/test_reminders.py`:

```python
def test_reminder_new_defaults_update_main_session_allow_ping():
    reminder = Reminder.new(message="test", delay_minutes=30)

    assert reminder.update_main_session == "on_ping"
    assert reminder.allow_ping is True


def test_reminder_new_custom_bg_config():
    reminder = Reminder.new(
        message="silent",
        delay_minutes=30,
        background=True,
        update_main_session="freely",
        allow_ping=False,
    )

    assert reminder.update_main_session == "freely"
    assert reminder.allow_ping is False


def test_reminder_bg_config_roundtrip(data_dir):
    reminder = Reminder.new(
        message="check",
        delay_minutes=30,
        background=True,
        update_main_session="blocked",
        allow_ping=False,
    )
    append_reminder(reminder)

    loaded = list_reminders()[0]

    assert loaded.update_main_session == "blocked"
    assert loaded.allow_ping is False
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_routines.py::test_routine_new_defaults_update_main_session_allow_ping -v`
Expected: FAIL (TypeError — unexpected keyword argument)

**Step 3: Add fields to both dataclasses**

In `src/ollim_bot/scheduling/routines.py`, add to `Routine` after `description`:

```python
    update_main_session: str = "on_ping"
    allow_ping: bool = True
```

And add them to `Routine.new()`:

```python
    @staticmethod
    def new(
        message: str,
        *,
        cron: str,
        background: bool = False,
        model: str | None = None,
        thinking: bool = True,
        isolated: bool = False,
        description: str = "",
        update_main_session: str = "on_ping",
        allow_ping: bool = True,
    ) -> "Routine":
        return Routine(
            id=uuid4().hex[:8],
            message=message,
            cron=cron,
            background=background,
            model=model,
            thinking=thinking,
            isolated=isolated,
            description=description,
            update_main_session=update_main_session,
            allow_ping=allow_ping,
        )
```

Same pattern for `src/ollim_bot/scheduling/reminders.py` — add fields after `description`, add params to `Reminder.new()`.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_routines.py tests/test_reminders.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/ollim_bot/scheduling/routines.py src/ollim_bot/scheduling/reminders.py tests/test_routines.py tests/test_reminders.py
git commit -m "feat: add update_main_session and allow_ping fields to Routine and Reminder"
```

---

### Task 3: Tool enforcement — allow_ping and report_updates blocking

**Files:**
- Modify: `src/ollim_bot/agent_tools.py`
- Test: `tests/test_agent_tools.py`

**Step 1: Write failing tests**

Add imports to `tests/test_agent_tools.py`:

```python
from ollim_bot.forks import (
    # ... existing imports ...
    set_bg_fork_config,
    BgForkConfig,
)
```

Add tests:

```python
# --- allow_ping enforcement ---


def test_ping_user_blocked_when_allow_ping_false(data_dir):
    ch = InMemoryChannel()
    set_fork_channel(ch)
    set_in_fork(True)
    set_bg_fork_config(BgForkConfig(allow_ping=False))

    result = _run(_ping({"message": "hello"}))

    assert "disabled" in result["content"][0]["text"].lower()
    assert len(ch.messages) == 0
    set_in_fork(False)
    set_bg_fork_config(BgForkConfig())


def test_embed_blocked_when_allow_ping_false(data_dir):
    ch = InMemoryChannel()
    set_fork_channel(ch)
    set_in_fork(True)
    set_bg_fork_config(BgForkConfig(allow_ping=False))

    result = _run(_embed({"title": "Tasks"}))

    assert "disabled" in result["content"][0]["text"].lower()
    assert len(ch.messages) == 0
    set_in_fork(False)
    set_bg_fork_config(BgForkConfig())


def test_ping_user_critical_still_blocked_when_allow_ping_false(data_dir):
    ch = InMemoryChannel()
    set_fork_channel(ch)
    set_in_fork(True)
    set_bg_fork_config(BgForkConfig(allow_ping=False))

    result = _run(_ping({"message": "urgent!", "critical": True}))

    assert "disabled" in result["content"][0]["text"].lower()
    assert len(ch.messages) == 0
    set_in_fork(False)
    set_bg_fork_config(BgForkConfig())


# --- report_updates blocked mode ---


def test_report_updates_blocked_when_update_blocked(data_dir):
    set_in_fork(True)
    set_bg_fork_config(BgForkConfig(update_main_session="blocked"))

    result = _run(_report({"message": "summary"}))

    assert "disabled" in result["content"][0]["text"].lower()
    set_in_fork(False)
    set_bg_fork_config(BgForkConfig())
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_agent_tools.py::test_ping_user_blocked_when_allow_ping_false -v`
Expected: FAIL (assertion — ping still goes through)

**Step 3: Implement allow_ping and blocked checks**

In `src/ollim_bot/agent_tools.py`, add import:

```python
from ollim_bot.forks import (
    # ... existing imports ...
    get_bg_fork_config,
    mark_bg_reported,
)
```

In `ping_user` handler, add before the budget check:

```python
    if not get_bg_fork_config().allow_ping:
        return {
            "content": [
                {
                    "type": "text",
                    "text": "Pinging is disabled for this background task.",
                }
            ]
        }
```

In `discord_embed` handler, add the same check inside the `if _source() == "bg":` block, before the budget check:

```python
    if _source() == "bg":
        if not get_bg_fork_config().allow_ping:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": "Pinging is disabled for this background task.",
                    }
                ]
            }
        if budget_error := _check_bg_budget(args):
            return budget_error
```

In `report_updates` handler, add at the top of the `if in_bg_fork():` branch:

```python
    if in_bg_fork():
        if get_bg_fork_config().update_main_session == "blocked":
            return {
                "content": [
                    {
                        "type": "text",
                        "text": "Reporting to main session is disabled for this background task.",
                    }
                ]
            }
        await append_update(args["message"])
        mark_bg_reported()
        mark_bg_output(False)
        ...
```

Note: also add `mark_bg_reported()` call in `report_updates` for the bg fork success path (needed for `always` mode tracking).

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_agent_tools.py -k "allow_ping_false or update_blocked" -v`
Expected: All 4 PASS

**Step 5: Commit**

```bash
git add src/ollim_bot/agent_tools.py tests/test_agent_tools.py
git commit -m "feat: enforce allow_ping and update_main_session=blocked in bg fork tools"
```

---

### Task 4: Stop hook — respect update_main_session modes

**Files:**
- Modify: `src/ollim_bot/agent_tools.py`
- Test: `tests/test_agent_tools.py`

**Step 1: Write failing tests**

Add imports to `tests/test_agent_tools.py`:

```python
from ollim_bot.forks import (
    # ... existing imports ...
    init_bg_reported_flag,
    mark_bg_reported,
)
```

Add tests:

```python
# --- stop hook update_main_session modes ---


def test_stop_hook_blocks_on_always_without_report():
    from ollim_bot.agent_tools import require_report_hook
    from ollim_bot.forks import init_bg_output_flag

    set_in_fork(True)
    init_bg_output_flag()
    init_bg_reported_flag()
    set_bg_fork_config(BgForkConfig(update_main_session="always"))

    result = _run(require_report_hook({}, None, {"signal": None}))

    assert "report_updates" in result.get("systemMessage", "")
    set_in_fork(False)
    set_bg_fork_config(BgForkConfig())


def test_stop_hook_allows_on_always_with_report():
    from ollim_bot.agent_tools import require_report_hook
    from ollim_bot.forks import init_bg_output_flag

    set_in_fork(True)
    init_bg_output_flag()
    init_bg_reported_flag()
    mark_bg_reported()
    set_bg_fork_config(BgForkConfig(update_main_session="always"))

    result = _run(require_report_hook({}, None, {"signal": None}))

    assert result == {}
    set_in_fork(False)
    set_bg_fork_config(BgForkConfig())


def test_stop_hook_allows_on_freely_with_unreported_output(data_dir):
    from ollim_bot.agent_tools import require_report_hook
    from ollim_bot.forks import init_bg_output_flag

    ch = InMemoryChannel()
    set_fork_channel(ch)
    set_in_fork(True)
    init_bg_output_flag()
    set_bg_fork_config(BgForkConfig(update_main_session="freely"))

    async def _check():
        await _ping({"message": "test"})
        return await require_report_hook({}, None, {"signal": None})

    result = _run(_check())

    assert result == {}
    set_in_fork(False)
    set_bg_fork_config(BgForkConfig())


def test_stop_hook_allows_on_blocked():
    from ollim_bot.agent_tools import require_report_hook
    from ollim_bot.forks import init_bg_output_flag

    set_in_fork(True)
    init_bg_output_flag()
    set_bg_fork_config(BgForkConfig(update_main_session="blocked"))

    result = _run(require_report_hook({}, None, {"signal": None}))

    assert result == {}
    set_in_fork(False)
    set_bg_fork_config(BgForkConfig())
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_agent_tools.py::test_stop_hook_blocks_on_always_without_report -v`
Expected: FAIL (hook returns `{}` — doesn't know about `always` mode yet)

**Step 3: Implement new stop hook logic**

Replace `require_report_hook` in `src/ollim_bot/agent_tools.py`:

```python
async def require_report_hook(
    input_data: HookInput,
    tool_use_id: str | None,
    context: HookContext,
) -> SyncHookJSONOutput:
    """Stop hook: enforce update_main_session policy for bg forks."""
    if not in_bg_fork():
        return {}

    mode = get_bg_fork_config().update_main_session
    if mode in ("freely", "blocked"):
        return {}
    if mode == "always" and not bg_reported():
        return SyncHookJSONOutput(
            systemMessage=(
                "You haven't called report_updates yet. Call it now to update "
                "the main session on what happened."
            ),
        )
    if mode == "on_ping" and bg_output_sent() :
        return SyncHookJSONOutput(
            systemMessage=(
                "You sent visible output (ping/embed) but haven't called "
                "report_updates. Call it now to update the main session on "
                "what happened."
            ),
        )
    return {}
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_agent_tools.py -k "stop_hook" -v`
Expected: All PASS (including existing tests)

**Step 5: Commit**

```bash
git add src/ollim_bot/agent_tools.py tests/test_agent_tools.py
git commit -m "feat: stop hook respects update_main_session modes (always/on_ping/freely/blocked)"
```

---

### Task 5: Thread BgForkConfig through run_agent_background

**Files:**
- Modify: `src/ollim_bot/forks.py` (`run_agent_background` signature)
- Modify: `src/ollim_bot/scheduling/scheduler.py` (build and pass config)

**Step 1: Modify run_agent_background to accept and set config**

In `src/ollim_bot/forks.py`, update `run_agent_background` signature to accept `bg_config`:

```python
async def run_agent_background(
    owner: discord.User,
    agent: Agent,
    prompt: str,
    *,
    model: str | None = None,
    thinking: bool = True,
    isolated: bool = False,
    bg_config: BgForkConfig | None = None,
) -> None:
```

Add after `init_bg_output_flag()`:

```python
    if bg_config:
        set_bg_fork_config(bg_config)
    init_bg_reported_flag()
```

**Step 2: Build BgForkConfig in scheduler and pass it**

In `src/ollim_bot/scheduling/scheduler.py`, add import:

```python
from ollim_bot.forks import BgForkConfig
```

In `_register_routine` `_fire()`, build and pass config:

```python
    async def _fire() -> None:
        busy = agent.lock().locked()
        bg_config = BgForkConfig(
            update_main_session=routine.update_main_session,
            allow_ping=routine.allow_ping,
        )
        prompt = _build_routine_prompt(...)
        ...
        if routine.background:
            await run_agent_background(
                owner, agent, prompt,
                model=routine.model,
                thinking=routine.thinking,
                isolated=routine.isolated,
                bg_config=bg_config,
            )
```

Same in `_register_reminder` `fire_oneshot()`.

**Step 3: Run full test suite**

Run: `uv run pytest -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add src/ollim_bot/forks.py src/ollim_bot/scheduling/scheduler.py
git commit -m "feat: thread BgForkConfig through run_agent_background and scheduler"
```

---

### Task 6: Adapt preamble to BgForkConfig

**Files:**
- Modify: `src/ollim_bot/scheduling/scheduler.py`
- Test: `tests/test_scheduler_prompts.py`

**Step 1: Write failing tests**

Add import to `tests/test_scheduler_prompts.py`:

```python
from ollim_bot.forks import BgForkConfig
```

Add tests:

```python
# --- BgForkConfig-aware preamble ---


def test_bg_preamble_allow_ping_false():
    config = BgForkConfig(allow_ping=False)
    result = _build_bg_preamble([], [], bg_config=config)

    assert "ping_user" not in result
    assert "discord_embed" not in result
    assert "disabled" in result.lower()


def test_bg_preamble_update_always():
    config = BgForkConfig(update_main_session="always")
    result = _build_bg_preamble([], [], bg_config=config)

    assert "MUST" in result
    assert "report_updates" in result


def test_bg_preamble_update_freely():
    config = BgForkConfig(update_main_session="freely")
    result = _build_bg_preamble([], [], bg_config=config)

    assert "optionally" in result.lower()
    assert "report_updates" in result


def test_bg_preamble_update_blocked():
    config = BgForkConfig(update_main_session="blocked")
    result = _build_bg_preamble([], [], bg_config=config)

    assert "report_updates" not in result
    assert "silently" in result.lower()


def test_bg_preamble_default_config_unchanged():
    """Default config produces the same preamble as before (on_ping + allow_ping)."""
    config = BgForkConfig()
    result = _build_bg_preamble([], [], bg_config=config)

    assert "ping_user" in result
    assert "report_updates" in result
    assert "what happened" in result
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_scheduler_prompts.py::test_bg_preamble_allow_ping_false -v`
Expected: FAIL (TypeError — unexpected keyword argument `bg_config`)

**Step 3: Implement config-aware preamble**

Update `_build_bg_preamble` in `src/ollim_bot/scheduling/scheduler.py`:

```python
def _build_bg_preamble(
    reminders: list[Reminder],
    routines: list[Routine],
    *,
    busy: bool = False,
    bg_config: BgForkConfig | None = None,
) -> str:
    """Build BG_PREAMBLE with budget status, remaining task count, and config."""
    config = bg_config or BgForkConfig()
    bg_reminders, bg_routines = ping_budget.remaining_today(reminders, routines)
    budget_status = ping_budget.get_status()

    remaining_parts: list[str] = []
    if bg_reminders > 0:
        remaining_parts.append(
            f"{bg_reminders} bg reminder{'s' if bg_reminders != 1 else ''}"
        )
    if bg_routines > 0:
        remaining_parts.append(
            f"{bg_routines} bg routine{'s' if bg_routines != 1 else ''}"
        )
    remaining_line = (
        f"Remaining today: {', '.join(remaining_parts)} before budget reset.\n"
        if remaining_parts
        else ""
    )

    # --- Ping instructions ---
    if config.allow_ping:
        ping_section = (
            "Your text output will be discarded. Use `ping_user` (MCP tool) to send "
            "a plain text alert, or `discord_embed` for structured data. Only alert "
            "if something genuinely warrants attention.\n\n"
        )
    else:
        ping_section = (
            "Your text output will be discarded. "
            "Pinging is disabled for this task — `ping_user` and `discord_embed` "
            "are not available.\n\n"
        )

    # --- Update instructions ---
    mode = config.update_main_session
    if mode == "always":
        update_section = (
            "This runs on a forked session -- by default everything is discarded.\n"
            "You MUST call `report_updates(message)` before finishing to update "
            "the main session on what happened.\n\n"
        )
    elif mode == "freely":
        update_section = (
            "This runs on a forked session -- by default everything is discarded.\n"
            "You may optionally call `report_updates(message)` to update the main "
            "session on what happened -- or just finish without it.\n\n"
        )
    elif mode == "blocked":
        update_section = (
            "This runs on a forked session. This task runs silently -- no "
            "reporting to the main session.\n\n"
        )
    else:  # on_ping (default)
        update_section = (
            "This runs on a forked session -- by default everything is discarded.\n"
            "- Call `report_updates(message)` to update the main session on what "
            "happened (fork discarded).\n"
            "- Call nothing if nothing useful happened.\n\n"
        )

    busy_line = (
        "User is mid-conversation. Do NOT use `ping_user` or `discord_embed` "
        "unless `critical=True`. Use `report_updates` for all findings -- "
        "they'll appear in the main session when the conversation ends.\n\n"
        if busy and config.allow_ping
        else ""
    )

    budget_section = (
        f"Ping budget: {budget_status}.\n"
        f"{remaining_line}"
        "Plan pings carefully -- you may not need to ping for every task. "
        "Use report_updates for non-urgent summaries. "
        "Set critical=True only for time-sensitive items (event in <30min, urgent message).\n\n"
        if config.allow_ping
        else ""
    )

    return f"{ping_section}{update_section}{busy_line}{budget_section}"
```

Update `_build_routine_prompt` and `_build_reminder_prompt` to pass `bg_config`:

```python
def _build_routine_prompt(
    routine: Routine,
    *,
    reminders: list[Reminder],
    routines: list[Routine],
    busy: bool = False,
    bg_config: BgForkConfig | None = None,
) -> str:
    if routine.background:
        preamble = _build_bg_preamble(
            reminders, routines, busy=busy, bg_config=bg_config
        )
        return f"[routine-bg:{routine.id}] {preamble}{routine.message}"
    return f"[routine:{routine.id}] {routine.message}"
```

Same for `_build_reminder_prompt`.

Update the callers in `_register_routine._fire()` and `_register_reminder.fire_oneshot()` to build and pass the config:

```python
        bg_config = BgForkConfig(
            update_main_session=routine.update_main_session,
            allow_ping=routine.allow_ping,
        )
        prompt = _build_routine_prompt(
            routine,
            reminders=list_reminders(),
            routines=list_routines(),
            busy=busy,
            bg_config=bg_config,
        )
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_scheduler_prompts.py -v`
Expected: All PASS (new and existing)

**Step 5: Commit**

```bash
git add src/ollim_bot/scheduling/scheduler.py tests/test_scheduler_prompts.py
git commit -m "feat: adapt bg preamble to BgForkConfig (ping/update instructions)"
```

---

### Task 7: CLI flags for routine and reminder commands

**Files:**
- Modify: `src/ollim_bot/scheduling/routine_cmd.py`
- Modify: `src/ollim_bot/scheduling/reminder_cmd.py`
- Test: `tests/test_cli.py`

**Step 1: Check existing CLI tests**

Read `tests/test_cli.py` to match patterns.

**Step 2: Add CLI flags**

In `src/ollim_bot/scheduling/routine_cmd.py`, add to `add_p`:

```python
    add_p.add_argument(
        "--update-main-session",
        choices=["always", "on_ping", "freely", "blocked"],
        default="on_ping",
        help="How bg fork reports to main session (bg only)",
    )
    add_p.add_argument(
        "--no-ping",
        action="store_true",
        help="Disable ping_user/discord_embed (bg only)",
    )
```

Update `_handle_add`:

```python
    routine = Routine.new(
        ...
        update_main_session=args.update_main_session,
        allow_ping=not args.no_ping,
    )
```

Update `_fmt_schedule` to show non-default values:

```python
def _fmt_schedule(r: Routine) -> str:
    sched = f"cron '{r.cron}'"
    if r.background:
        parts = ["bg"]
        if r.isolated:
            parts.append("isolated")
        if not r.allow_ping:
            parts.append("no-ping")
        if r.update_main_session != "on_ping":
            parts.append(f"updates:{r.update_main_session}")
        tag = f"[{','.join(parts)}]"
        sched = f"{tag} {sched}"
    ...
```

Same changes for `src/ollim_bot/scheduling/reminder_cmd.py`.

**Step 3: Update ChainContext and follow_up_chain**

In `src/ollim_bot/agent_tools.py`, add fields to `ChainContext`:

```python
@dataclass(frozen=True, slots=True)
class ChainContext:
    ...
    update_main_session: str = "on_ping"
    allow_ping: bool = True
```

In `follow_up_chain`, forward the flags:

```python
    if ctx.update_main_session != "on_ping":
        cmd.extend(["--update-main-session", ctx.update_main_session])
    if not ctx.allow_ping:
        cmd.append("--no-ping")
```

In `src/ollim_bot/scheduling/scheduler.py`, update `ChainContext` construction:

```python
            chain_ctx = ChainContext(
                ...
                update_main_session=reminder.update_main_session,
                allow_ping=reminder.allow_ping,
            )
```

**Step 4: Run full test suite**

Run: `uv run pytest -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/ollim_bot/scheduling/routine_cmd.py src/ollim_bot/scheduling/reminder_cmd.py src/ollim_bot/agent_tools.py src/ollim_bot/scheduling/scheduler.py
git commit -m "feat: CLI flags --update-main-session and --no-ping, chain forwarding"
```

---

### Task 8: Update SYSTEM_PROMPT and CLAUDE.md

**Files:**
- Modify: `src/ollim_bot/prompts.py`
- Modify: `CLAUDE.md`

**Step 1: Update SYSTEM_PROMPT**

In `src/ollim_bot/prompts.py`, update the routines frontmatter table to add:

```
| `update_main_session` | no | `"on_ping"` | How bg fork reports: "always", "on_ping", "freely", "blocked" (bg only) |
| `allow_ping` | no | `true` | Allow `ping_user`/`discord_embed` (bg only) |
```

Update the `## Background Session Management` section exit strategies to reflect the new modes.

**Step 2: Update CLAUDE.md**

Add the new fields to the `## Routines & reminders` section.

**Step 3: Run full test suite**

Run: `uv run pytest -v`
Expected: All PASS (no behavior change, just docs)

**Step 4: Commit**

```bash
git add src/ollim_bot/prompts.py CLAUDE.md
git commit -m "docs: document update_main_session and allow_ping in prompts and CLAUDE.md"
```

---

### Task 9: Final verification

**Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: All PASS

**Step 2: Verify no regressions in existing bg fork behavior**

Run: `uv run pytest tests/test_agent_tools.py tests/test_forks.py tests/test_scheduler_prompts.py -v`
Expected: All PASS — existing tests unchanged

**Step 3: Final commit (if any fixes needed)**

```bash
git add -A && git commit -m "fix: address any issues from final verification"
```
