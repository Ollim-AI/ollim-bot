# Quiet When Busy Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace `skip_if_busy` with always-on "quiet when busy" behavior — bg forks always run but suppress non-critical pings when the user is mid-conversation, funneling findings through `report_updates`.

**Architecture:** Remove `skip_if_busy` from data models, CLI, and SYSTEM_PROMPT. Add a `_busy` contextvar in `forks.py`. `run_agent_background` checks `agent.lock().locked()` and sets the busy flag + prepends a quiet instruction to the prompt. `agent_tools.py` enforces the soft-block on `ping_user`/`discord_embed` when busy (critical bypasses).

**Tech Stack:** Python, contextvars, asyncio

---

### Task 1: Remove `skip_if_busy` from Routine dataclass and tests

**Files:**
- Modify: `src/ollim_bot/scheduling/routines.py:15-49`
- Modify: `tests/test_routines.py:11-27`

**Step 1: Update tests to remove skip_if_busy references**

In `tests/test_routines.py`, remove the `skip_if_busy` assertions and parameters:

```python
# test_routine_new_generates_id (line 18): delete the assertion
#   assert routine.skip_if_busy is True    <-- delete this line

# test_routine_new_with_background (lines 21-27): remove skip_if_busy param and assertion
def test_routine_new_with_background():
    routine = Routine.new(
        message="bg task", cron="*/5 * * * *", background=True
    )

    assert routine.background is True
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_routines.py -v`
Expected: Tests still pass (field still exists). This is a removal task — tests will pass before and after.

**Step 3: Remove `skip_if_busy` from Routine dataclass**

In `src/ollim_bot/scheduling/routines.py`:
- Line 21: delete `skip_if_busy: bool = True`
- Line 33: delete `skip_if_busy: bool = True,`
- Line 44: delete `skip_if_busy=skip_if_busy,`

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_routines.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/ollim_bot/scheduling/routines.py tests/test_routines.py
git commit -m "refactor: remove skip_if_busy from Routine dataclass"
```

---

### Task 2: Remove `skip_if_busy` from Reminder dataclass and tests

**Files:**
- Modify: `src/ollim_bot/scheduling/reminders.py:17-66`
- Modify: `tests/test_reminders.py:53-59`

**Step 1: Update tests to remove skip_if_busy references**

In `tests/test_reminders.py`, update `test_reminder_new_background` (lines 53-59):

```python
def test_reminder_new_background():
    reminder = Reminder.new(
        message="silent", delay_minutes=15, background=True
    )

    assert reminder.background is True
```

**Step 2: Remove `skip_if_busy` from Reminder dataclass**

In `src/ollim_bot/scheduling/reminders.py`:
- Line 23: delete `skip_if_busy: bool = True`
- Line 38: delete `skip_if_busy: bool = True,`
- Line 58: delete `skip_if_busy=skip_if_busy,`

**Step 3: Run tests to verify they pass**

Run: `uv run pytest tests/test_reminders.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add src/ollim_bot/scheduling/reminders.py tests/test_reminders.py
git commit -m "refactor: remove skip_if_busy from Reminder dataclass"
```

---

### Task 3: Remove `skip_if_busy` from CLI commands

**Files:**
- Modify: `src/ollim_bot/scheduling/routine_cmd.py:24,46,85`
- Modify: `src/ollim_bot/scheduling/reminder_cmd.py:24,46,87`

**Step 1: Update `routine_cmd.py`**

- Line 24: in `_fmt_schedule`, delete the `if not r.skip_if_busy:` block (lines 24-25: the "queue" tag)
- Line 46: delete `add_p.add_argument("--no-skip", ...)` line
- Line 85: delete `skip_if_busy=not args.no_skip,` line

After edit, `_fmt_schedule` bg parts should just be:
```python
        parts = ["bg"]
        if r.isolated:
            parts.append("isolated")
        tag = f"[{','.join(parts)}]"
```

**Step 2: Update `reminder_cmd.py`**

Same pattern:
- Line 24: delete the `if not r.skip_if_busy:` / `parts.append("queue")` block
- Line 46: delete `add_p.add_argument("--no-skip", ...)` line
- Line 87: delete `skip_if_busy=not args.no_skip,` line

**Step 3: Run all tests**

Run: `uv run pytest -v`
Expected: PASS (no CLI tests reference --no-skip)

**Step 4: Commit**

```bash
git add src/ollim_bot/scheduling/routine_cmd.py src/ollim_bot/scheduling/reminder_cmd.py
git commit -m "refactor: remove skip_if_busy from CLI commands"
```

---

### Task 4: Remove `skip_if_busy` from scheduler and `run_agent_background`

**Files:**
- Modify: `src/ollim_bot/scheduling/scheduler.py:204,273`
- Modify: `src/ollim_bot/forks.py:287,308-310`
- Modify: `tests/test_forks.py:272`

**Step 1: Remove `skip_if_busy` parameter from `run_agent_background`**

In `src/ollim_bot/forks.py`:
- Line 287: delete `skip_if_busy: bool,` parameter
- Lines 308-310: delete the entire `if skip_if_busy and agent.lock().locked():` block

**Step 2: Remove `skip_if_busy=` from scheduler call sites**

In `src/ollim_bot/scheduling/scheduler.py`:
- Line 204: delete `skip_if_busy=routine.skip_if_busy,`
- Line 273: delete `skip_if_busy=reminder.skip_if_busy,`

**Step 3: Update test call site**

In `tests/test_forks.py` line 272:
```python
# Change:
            owner, agent, "[routine-bg:test] do stuff", skip_if_busy=False
# To:
            owner, agent, "[routine-bg:test] do stuff"
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_forks.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/ollim_bot/forks.py src/ollim_bot/scheduling/scheduler.py tests/test_forks.py
git commit -m "refactor: remove skip_if_busy from run_agent_background and scheduler"
```

---

### Task 5: Remove `skip_if_busy` from SYSTEM_PROMPT

**Files:**
- Modify: `src/ollim_bot/prompts.py:107`

**Step 1: Delete the skip_if_busy row from the routine YAML table**

In `src/ollim_bot/prompts.py` line 107, delete:
```
| `skip_if_busy` | no | `true` | Skip if {USER_NAME} is mid-conversation |
```

**Step 2: Run tests**

Run: `uv run pytest -v`
Expected: PASS

**Step 3: Commit**

```bash
git add src/ollim_bot/prompts.py
git commit -m "docs: remove skip_if_busy from SYSTEM_PROMPT"
```

---

### Task 6: Add `_busy` contextvar and busy-aware preamble

**Files:**
- Modify: `src/ollim_bot/forks.py` (add contextvar near line 40)
- Modify: `src/ollim_bot/scheduling/scheduler.py:50-58,101-128` (add busy param to preamble)
- Create: test in `tests/test_forks.py`

**Step 1: Write the failing test for busy contextvar**

In `tests/test_forks.py`, add:

```python
from ollim_bot.forks import is_busy, set_busy


def test_busy_contextvar_default_false():
    assert is_busy() is False


def test_busy_contextvar_set_and_read():
    set_busy(True)
    assert is_busy() is True
    set_busy(False)
    assert is_busy() is False
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_forks.py::test_busy_contextvar_default_false -v`
Expected: FAIL (ImportError — `is_busy` doesn't exist yet)

**Step 3: Add `_busy` contextvar to `forks.py`**

After the `_in_fork_var` block (around line 40), add:

```python
_busy_var: ContextVar[bool] = ContextVar("_busy", default=False)


def set_busy(busy: bool) -> None:
    _busy_var.set(busy)


def is_busy() -> bool:
    return _busy_var.get()
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_forks.py::test_busy_contextvar_default_false tests/test_forks.py::test_busy_contextvar_set_and_read -v`
Expected: PASS

**Step 5: Write the test for busy-aware preamble**

In `tests/test_scheduler.py` (or a new test file if none exists — check first), add a test for `_build_bg_preamble` with `busy=True`:

```python
from ollim_bot.scheduling.scheduler import _build_bg_preamble


def test_build_bg_preamble_normal():
    result = _build_bg_preamble([], [])
    assert "mid-conversation" not in result
    assert "report_updates" in result


def test_build_bg_preamble_busy():
    result = _build_bg_preamble([], [], busy=True)
    assert "mid-conversation" in result
    assert "report_updates" in result
    assert "critical" in result.lower()
```

**Step 6: Run test to verify it fails**

Run: `uv run pytest tests/test_scheduler.py::test_build_bg_preamble_busy -v`
Expected: FAIL (unexpected keyword argument 'busy')

**Step 7: Add `busy` parameter to `_build_bg_preamble`**

In `src/ollim_bot/scheduling/scheduler.py`, update `_build_bg_preamble`:

```python
def _build_bg_preamble(
    reminders: list[Reminder],
    routines: list[Routine],
    *,
    busy: bool = False,
) -> str:
    """Build BG_PREAMBLE with budget status and remaining task count."""
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

    busy_line = (
        "User is mid-conversation. Do NOT use `ping_user` or `discord_embed` "
        "unless `critical=True`. Use `report_updates` for all findings -- "
        "they'll appear in the main session when the conversation ends.\n\n"
        if busy
        else ""
    )

    return (
        f"{_BG_PREAMBLE}"
        f"{busy_line}"
        f"Ping budget: {budget_status}.\n"
        f"{remaining_line}"
        "Plan pings carefully -- you may not need to ping for every task. "
        "Use report_updates for non-urgent summaries. "
        "Set critical=True only for time-sensitive items (event in <30min, urgent message).\n\n"
    )
```

**Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/test_scheduler.py tests/test_forks.py -v`
Expected: PASS

**Step 9: Commit**

```bash
git add src/ollim_bot/forks.py src/ollim_bot/scheduling/scheduler.py tests/test_forks.py tests/test_scheduler.py
git commit -m "feat: add busy contextvar and busy-aware bg preamble"
```

---

### Task 7: Wire busy detection into `run_agent_background`

**Files:**
- Modify: `src/ollim_bot/forks.py:282-312` (run_agent_background)
- Modify: `src/ollim_bot/scheduling/scheduler.py:131-170` (pass busy to prompt builders)

**Step 1: Write the test for busy bg fork still running**

In `tests/test_forks.py`, add a test that verifies a bg fork runs even when the lock is held (previously it would be skipped):

```python
def test_bg_fork_runs_when_busy(monkeypatch, data_dir):
    """A bg fork runs even when agent lock is held (quiet mode, not skipped)."""
    owner = AsyncMock()
    owner.create_dm = AsyncMock(return_value=AsyncMock())

    agent = AsyncMock()
    lock = asyncio.Lock()
    agent.lock.return_value = lock

    client = AsyncMock()
    agent.create_forked_client = AsyncMock(return_value=client)
    agent.run_on_client = AsyncMock(return_value="fork-session-id")

    # Acquire lock to simulate busy
    _run(lock.acquire())

    try:
        _run(
            run_agent_background(
                owner, agent, "[routine-bg:test] do stuff"
            )
        )
        # Fork should have run (not skipped)
        agent.create_forked_client.assert_awaited()
    finally:
        lock.release()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_forks.py::test_bg_fork_runs_when_busy -v`
Expected: PASS (the skip_if_busy check was already removed in Task 4)

Actually this test should pass already since we removed skip_if_busy. The real behavior change is the prompt injection. Let's also add a test that checks the busy flag is set when lock is held:

```python
def test_bg_fork_sets_busy_when_lock_held(monkeypatch, data_dir):
    """When agent lock is held, the _busy contextvar is set during fork execution."""
    from ollim_bot.forks import is_busy

    observed_busy: list[bool] = []

    owner = AsyncMock()
    owner.create_dm = AsyncMock(return_value=AsyncMock())

    agent = AsyncMock()
    lock = asyncio.Lock()
    agent.lock.return_value = lock

    async def capture_busy(client, prompt, **kwargs):
        observed_busy.append(is_busy())
        return "fork-session-id"

    client = AsyncMock()
    agent.create_forked_client = AsyncMock(return_value=client)
    agent.run_on_client = AsyncMock(side_effect=capture_busy)

    _run(lock.acquire())
    try:
        _run(
            run_agent_background(
                owner, agent, "[routine-bg:test] do stuff"
            )
        )
    finally:
        lock.release()

    assert observed_busy == [True]
```

**Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_forks.py::test_bg_fork_sets_busy_when_lock_held -v`
Expected: FAIL (is_busy() returns False — busy flag not set yet)

**Step 4: Wire busy detection into `run_agent_background`**

In `src/ollim_bot/forks.py`, in `run_agent_background`:

After `tag = _extract_prompt_tag(prompt)` (line 306), add:

```python
    busy = agent.lock().locked()
    if busy:
        log.info("bg fork running in quiet mode (user busy): %s", tag)
    set_busy(busy)
```

And in the `finally` block (line 355-357), add `set_busy(False)`:

```python
    finally:
        set_in_fork(False)
        set_busy(False)
        cancel_message_collector()
```

**Step 5: Pass `busy` through prompt builders**

In `src/ollim_bot/scheduling/scheduler.py`, update `_build_routine_prompt` and `_build_reminder_prompt` to accept and pass `busy`:

```python
def _build_routine_prompt(
    routine: Routine,
    *,
    reminders: list[Reminder],
    routines: list[Routine],
    busy: bool = False,
) -> str:
    if routine.background:
        preamble = _build_bg_preamble(reminders, routines, busy=busy)
        return f"[routine-bg:{routine.id}] {preamble}{routine.message}"
    return f"[routine:{routine.id}] {routine.message}"
```

```python
def _build_reminder_prompt(
    reminder: Reminder,
    *,
    reminders: list[Reminder],
    routines: list[Routine],
    busy: bool = False,
) -> str:
    ...
    if reminder.background:
        parts.append(_build_bg_preamble(reminders, routines, busy=busy).rstrip())
    ...
```

And update `_fire()` in `_register_routine` and `fire_oneshot()` in `_register_reminder` to check `agent.lock().locked()` and pass it:

```python
    async def _fire() -> None:
        busy = agent.lock().locked()
        prompt = _build_routine_prompt(
            routine,
            reminders=list_reminders(),
            routines=list_routines(),
            busy=busy,
        )
```

Same for `fire_oneshot()`:
```python
    async def fire_oneshot() -> None:
        busy = agent.lock().locked()
        prompt = _build_reminder_prompt(
            reminder,
            reminders=list_reminders(),
            routines=list_routines(),
            busy=busy,
        )
```

**Step 6: Run tests to verify they pass**

Run: `uv run pytest -v`
Expected: PASS

**Step 7: Commit**

```bash
git add src/ollim_bot/forks.py src/ollim_bot/scheduling/scheduler.py tests/test_forks.py
git commit -m "feat: wire busy detection into bg forks and prompt builders"
```

---

### Task 8: Soft-block non-critical pings when busy

**Files:**
- Modify: `src/ollim_bot/agent_tools.py:96-111,166-174,213-224`
- Create: test for busy blocking

**Step 1: Write the failing test**

Create a test that verifies `ping_user` and `discord_embed` return errors when busy and not critical. This needs to mock the contextvar. Add to a new `tests/test_agent_tools.py` or extend existing tests:

```python
# tests/test_agent_tools_busy.py
import asyncio
from unittest.mock import AsyncMock

from ollim_bot.forks import set_busy, set_in_fork


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_ping_user_blocked_when_busy(monkeypatch):
    """Non-critical ping_user returns error when busy flag is set."""
    from ollim_bot import agent_tools

    set_in_fork(True)
    set_busy(True)
    monkeypatch.setattr(agent_tools, "_channel", AsyncMock())

    try:
        result = _run(agent_tools.ping_user({"message": "hey"}))
        assert "mid-conversation" in result["content"][0]["text"]
    finally:
        set_in_fork(False)
        set_busy(False)


def test_ping_user_allowed_when_busy_critical(monkeypatch):
    """critical=True ping_user goes through even when busy."""
    from ollim_bot import agent_tools, ping_budget

    set_in_fork(True)
    set_busy(True)
    channel = AsyncMock()
    channel.send = AsyncMock(return_value=AsyncMock(id=123))
    monkeypatch.setattr(agent_tools, "_channel", channel)
    monkeypatch.setattr(ping_budget, "record_critical", lambda: None)

    try:
        result = _run(
            agent_tools.ping_user({"message": "urgent", "critical": True})
        )
        assert "sent" in result["content"][0]["text"].lower()
    finally:
        set_in_fork(False)
        set_busy(False)


def test_discord_embed_blocked_when_busy(monkeypatch):
    """Non-critical discord_embed returns error when busy flag is set."""
    from ollim_bot import agent_tools

    set_in_fork(True)
    set_busy(True)
    monkeypatch.setattr(agent_tools, "_channel", AsyncMock())

    try:
        result = _run(agent_tools.discord_embed({"title": "test"}))
        assert "mid-conversation" in result["content"][0]["text"]
    finally:
        set_in_fork(False)
        set_busy(False)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_agent_tools_busy.py -v`
Expected: FAIL (no busy check in agent_tools yet)

**Step 3: Add busy check to `_check_bg_budget`**

In `src/ollim_bot/agent_tools.py`, add import and modify `_check_bg_budget`:

Add to imports (near line 10-11):
```python
from ollim_bot.forks import is_busy
```

Replace `_check_bg_budget` (lines 96-111):

```python
def _check_bg_budget(args: dict[str, Any]) -> dict[str, Any] | None:
    """Check busy state and ping budget for bg forks.

    Returns error dict if blocked, None if OK.
    Busy check runs first: non-critical pings silently blocked when user
    is mid-conversation. Critical pings bypass the busy check.
    """
    critical = args.get("critical", False)
    if not critical and is_busy():
        return {
            "content": [
                {
                    "type": "text",
                    "text": "User is mid-conversation. Use `report_updates` instead, "
                    "or set `critical=True` for time-sensitive alerts.",
                }
            ]
        }
    if not critical and not ping_budget.try_use():
        return {
            "content": [
                {
                    "type": "text",
                    "text": "Budget exhausted (0 remaining). Use critical=True "
                    "only for genuinely urgent items.",
                }
            ]
        }
    if critical:
        ping_budget.record_critical()
    return None
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_agent_tools_busy.py -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/ollim_bot/agent_tools.py tests/test_agent_tools_busy.py
git commit -m "feat: soft-block non-critical pings when user is busy"
```

---

### Task 9: Update CLAUDE.md and clean up

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Update CLAUDE.md**

In the "Routines & reminders" section, remove any mention of `skip_if_busy`. Add a note about quiet-when-busy behavior:

Find the bullet about `skip_if_busy` (if any) and replace with:
- `Busy-aware: bg forks always run; when user is mid-conversation, non-critical pings are suppressed (agent uses `report_updates` instead). `critical=True` bypasses.`

**Step 2: Run full test suite one final time**

Run: `uv run pytest -v`
Expected: PASS

**Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for quiet-when-busy behavior"
```
