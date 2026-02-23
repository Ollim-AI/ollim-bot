# Fork Context & Pending Updates Fix

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix three bugs: reply-to-fork missing agent context, pending updates lacking observability, and `_bg_output_sent_var` ContextVar not propagating across SDK task boundaries.

**Architecture:** (1) Prepend `[fork-started]` tag to agent prompt on reply-to-fork. (2) Add logging to `append_update`/`pop_pending_updates` for diagnosing silent failures. (3) Replace `_bg_output_sent_var` ContextVar (immutable bool) with a mutable-container ContextVar in `forks.py` so mutations propagate across sibling `start_soon` tasks in the SDK's anyio task group.

**Tech Stack:** Python, asyncio, ContextVar, discord.py

---

### Task 1: Fix reply-to-fork missing agent context

**Files:**
- Modify: `src/ollim_bot/bot.py:311-314`
- Test: manual — no `test_bot.py` exists; existing pattern doesn't unit-test bot.py

The bug: when a user replies to a bg fork message, `on_message` enters an interactive fork and sends the user's message, but never tells the agent it's in a fork. The `/fork` command sends a `[fork-started]` prompt, but reply-to-fork skips it. So the agent ignores `[fork-timeout]` because it has no `[fork-started]` to match.

**Step 1: Add fork-reply prompt prefix**

In `bot.py`, add a constant and prepend it to `content` in the reply-to-fork branch:

```python
# Add after _FORK_NO_TOPIC_PROMPT (line 131):
_FORK_REPLY_PREFIX = (
    "[fork-started] You are now inside an interactive forked session "
    "(resumed from a background fork reply). Use save_context, "
    "report_updates, or exit_fork when the conversation is complete."
)
```

Then change the `on_message` fork entry (lines 311-314) from:

```python
        async with agent.lock():
            if fork_session_id:
                await agent.enter_interactive_fork(resume_session_id=fork_session_id)
                await _send_fork_enter(message.channel, None)
            await _dispatch(message.channel, content, images=images or None)
```

To:

```python
        async with agent.lock():
            if fork_session_id:
                await agent.enter_interactive_fork(resume_session_id=fork_session_id)
                await _send_fork_enter(message.channel, None)
                content = f"{_FORK_REPLY_PREFIX}\n\n{content}"
            await _dispatch(message.channel, content, images=images or None)
```

**Step 2: Verify no new imports needed**

`_FORK_REPLY_PREFIX` is a plain string constant — no new imports.

**Step 3: Commit**

```bash
git add src/ollim_bot/bot.py
git commit -m "fix: prepend [fork-started] context to reply-to-fork messages"
```

---

### Task 2: Add logging to pending updates I/O

**Files:**
- Modify: `src/ollim_bot/forks.py:65-115`
- Test: existing tests cover behavior; logging is observability-only

The bug: `report_updates` returned success but the update never appeared in the main session. No logging exists to verify whether the file was written or when it was consumed. Adding log lines will diagnose the next occurrence.

**Step 1: Add log lines to `append_update`**

After `os.replace(tmp, _UPDATES_FILE)` (line 82), inside the lock:

```python
        os.replace(tmp, _UPDATES_FILE)
        log.info("pending update appended (now %d): %.80s", len(updates), message)
```

**Step 2: Add log lines to `pop_pending_updates`**

After `_UPDATES_FILE.unlink()` (line 114), inside the lock:

```python
        _UPDATES_FILE.unlink()
        log.info("popped %d pending update(s)", len(updates))
```

And add a debug log for the empty case (after line 112):

```python
        if not _UPDATES_FILE.exists():
            log.debug("pop_pending_updates: file does not exist")
            return []
```

**Step 3: Run tests**

Run: `uv run pytest tests/test_forks.py -v`
Expected: all pass (logging doesn't affect behavior)

**Step 4: Commit**

```bash
git add src/ollim_bot/forks.py
git commit -m "fix: add logging to pending updates for diagnosing silent failures"
```

---

### Task 3: Fix `_bg_output_sent_var` ContextVar propagation

**Files:**
- Modify: `src/ollim_bot/forks.py:36-48` (add new exports alongside existing fork state)
- Modify: `src/ollim_bot/agent_tools.py:85-103, 199, 240, 360, 446-460`
- Test: `tests/test_agent_tools.py:350-432`

The bug: each MCP tool call runs in a separate `start_soon` task in the SDK's anyio task group. ContextVar changes (immutable bool) in one task are invisible to sibling tasks. So `discord_embed` sets `_bg_output_sent_var = True`, but `require_report_hook` in a different task sees the default `False`. The hook never fires.

Fix: use a **mutable container** (`list[bool]`) in the ContextVar. Since all sibling tasks inherit the same object reference from the parent (reader loop) context, mutations to the list are visible across tasks.

**Step 1: Add bg output flag to `forks.py`**

After the `in_bg_fork()` function (line 48), add:

```python
# ---------------------------------------------------------------------------
# Bg output tracking — mutable container so mutations propagate across
# sibling tasks in the SDK's anyio task group (ContextVar with immutable
# bool does NOT propagate between start_soon tasks).
# ---------------------------------------------------------------------------

_bg_output_flag: ContextVar[list[bool] | None] = ContextVar(
    "_bg_output_flag", default=None
)


def init_bg_output_flag() -> None:
    """Call before client connect() so all child tasks share the mutable ref."""
    _bg_output_flag.set([False])


def mark_bg_output(sent: bool) -> None:
    flag = _bg_output_flag.get()
    if flag is not None:
        flag[0] = sent


def bg_output_sent() -> bool:
    flag = _bg_output_flag.get()
    return bool(flag and flag[0])
```

**Step 2: Call `init_bg_output_flag()` in `run_agent_background`**

In `run_agent_background` (line 291), add the call after `set_in_fork(True)` and before `start_message_collector()`:

```python
    set_in_fork(True)
    init_bg_output_flag()
    start_message_collector()
```

**Step 3: Update `agent_tools.py` — remove old ContextVar, use new functions**

Remove the old code (lines 85-93):
```python
# DELETE these lines:
_bg_output_sent_var: ContextVar[bool] = ContextVar("_bg_output_sent", default=False)


def bg_output_sent() -> bool:
    return _bg_output_sent_var.get()
```

Add imports from forks at the existing forks import block (line 23-29):
```python
from ollim_bot.forks import (
    ForkExitAction,
    append_update,
    bg_output_sent,      # NEW
    clear_pending_updates,
    in_bg_fork,
    in_interactive_fork,
    mark_bg_output,      # NEW
    request_enter_fork,
    set_exit_action,
)
```

Remove `ContextVar` from the `contextvars` import (line 4) since it's no longer used in this file.

Replace all `_bg_output_sent_var` usages:

- Line 199 (`discord_embed`): `_bg_output_sent_var.set(True)` → `mark_bg_output(True)`
- Line 240 (`ping_user`): `_bg_output_sent_var.set(True)` → `mark_bg_output(True)`
- Line 360 (`report_updates`): `_bg_output_sent_var.set(False)` → `mark_bg_output(False)`
- Line 452 (`require_report_hook`): `not _bg_output_sent_var.get()` → `not bg_output_sent()`

**Step 4: Update tests**

In `tests/test_agent_tools.py`, update the bg output tests to:
1. Import `init_bg_output_flag` from forks
2. Call `init_bg_output_flag()` after `set_in_fork(True)` in each bg output test
3. Change `from ollim_bot.agent_tools import bg_output_sent` to `from ollim_bot.forks import bg_output_sent`

Tests to update:
- `test_bg_output_flag_set_on_ping` (line 350)
- `test_bg_output_flag_set_on_embed` (line 365)
- `test_bg_output_flag_cleared_on_report` (line 380)
- `test_stop_hook_allows_bg_stop_without_output` (line 407)
- `test_stop_hook_blocks_bg_stop_with_unreported_output` (line 418)

Example update for `test_bg_output_flag_set_on_ping`:

```python
def test_bg_output_flag_set_on_ping(data_dir):
    from ollim_bot.forks import bg_output_sent, init_bg_output_flag

    ch = InMemoryChannel()
    set_fork_channel(ch)
    set_in_fork(True)
    init_bg_output_flag()

    async def _check():
        await _ping({"message": "test"})
        return bg_output_sent()

    assert _run(_check()) is True
    set_in_fork(False)
```

**Step 5: Run all tests**

Run: `uv run pytest tests/test_agent_tools.py tests/test_forks.py -v`
Expected: all pass

**Step 6: Commit**

```bash
git add src/ollim_bot/forks.py src/ollim_bot/agent_tools.py tests/test_agent_tools.py
git commit -m "fix: use mutable ContextVar for bg output tracking across SDK tasks"
```
