# Interactive Forks Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add interactive forked conversations with clean module boundaries, configurable idle timeouts, and three exit strategies (save, report, discard).

**Architecture:** Extract fork state into `forks.py`, rename `discord_tools.py` to `agent_tools.py`, slim `streamer.py` to pure streaming, then build interactive fork lifecycle on the clean foundation. See `docs/plans/2026-02-18-interactive-forks-design.md` for full design.

**Tech Stack:** Claude Agent SDK (`ClaudeSDKClient`, `create_sdk_mcp_server`, `@tool`), discord.py (embeds, buttons, `DynamicItem`), APScheduler (`IntervalTrigger`)

---

## Phase 1: Architecture Refactor

### Task 1: Create forks.py — extract state from discord_tools.py

**Files:**
- Create: `src/ollim_bot/forks.py`
- Modify: `src/ollim_bot/discord_tools.py` (remove moved code, import from forks)
- Create: `tests/test_forks.py`
- Modify: `tests/test_discord_tools.py` (remove moved tests)

**Step 1: Write tests for forks.py state management**

Create `tests/test_forks.py` with tests for the state functions that will move from discord_tools.py. These are the same tests from `test_discord_tools.py` but importing from `forks` instead.

```python
"""Tests for forks.py — fork state, pending updates, interactive fork lifecycle."""

import asyncio

from ollim_bot.forks import (
    ForkExitAction,
    clear_pending_updates,
    in_interactive_fork,
    peek_pending_updates,
    pop_enter_fork,
    pop_exit_action,
    pop_fork_saved,
    pop_pending_updates,
    request_enter_fork,
    set_exit_action,
    set_in_fork,
    set_interactive_fork,
    touch_activity,
)


def test_bg_fork_saved_flag():
    set_in_fork(True)
    # _fork_saved starts False after set_in_fork
    assert pop_fork_saved() is False
    set_in_fork(False)


def test_set_in_fork_resets_saved():
    set_in_fork(True)
    # Simulate save_context setting the flag directly (tested via tool in test_agent_tools)
    set_in_fork(True)  # re-entering resets
    assert pop_fork_saved() is False
    set_in_fork(False)


def test_peek_reads_without_clearing():
    pop_pending_updates()
    from ollim_bot.forks import _append_update
    _append_update("peeked")

    first = peek_pending_updates()
    second = peek_pending_updates()

    assert first == ["peeked"]
    assert second == ["peeked"]
    pop_pending_updates()


def test_pop_clears_updates():
    pop_pending_updates()
    from ollim_bot.forks import _append_update
    _append_update("cleared")
    pop_pending_updates()

    assert pop_pending_updates() == []


def test_multiple_updates_accumulate():
    pop_pending_updates()
    from ollim_bot.forks import _append_update
    _append_update("first")
    _append_update("second")

    assert pop_pending_updates() == ["first", "second"]


def test_clear_is_idempotent():
    pop_pending_updates()
    clear_pending_updates()
    clear_pending_updates()
    assert peek_pending_updates() == []


# --- Interactive fork state ---

def test_interactive_fork_default():
    assert in_interactive_fork() is False


def test_set_interactive_fork():
    set_interactive_fork(True, idle_timeout=5)
    assert in_interactive_fork() is True
    set_interactive_fork(False)
    assert in_interactive_fork() is False


def test_exit_action_default():
    set_interactive_fork(True, idle_timeout=10)
    assert pop_exit_action() is ForkExitAction.NONE
    set_interactive_fork(False)


def test_set_and_pop_exit_action():
    set_interactive_fork(True, idle_timeout=10)
    set_exit_action(ForkExitAction.SAVE)

    assert pop_exit_action() is ForkExitAction.SAVE
    assert pop_exit_action() is ForkExitAction.NONE
    set_interactive_fork(False)


def test_enter_fork_request():
    request_enter_fork("research topic", idle_timeout=15)

    topic, timeout = pop_enter_fork()
    assert topic == "research topic"
    assert timeout == 15

    # Second pop returns None
    topic2, timeout2 = pop_enter_fork()
    assert topic2 is None
    assert timeout2 == 10  # default


def test_enter_fork_no_topic():
    request_enter_fork(None, idle_timeout=10)

    topic, timeout = pop_enter_fork()
    assert topic is None
    assert timeout == 10
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_forks.py -v`
Expected: ImportError — `ollim_bot.forks` does not exist yet.

**Step 3: Create forks.py with extracted state**

Create `src/ollim_bot/forks.py` with:
- `ForkExitAction` enum (NONE, SAVE, REPORT, EXIT)
- Background fork state: `_in_fork`, `_fork_saved`, `set_in_fork()`, `pop_fork_saved()`
- Pending updates: `_UPDATES_FILE`, `_append_update()`, `peek_pending_updates()`, `pop_pending_updates()`, `clear_pending_updates()`
- Interactive fork state: `_in_interactive_fork`, `_fork_exit_action`, `_enter_fork_requested`, `_enter_fork_topic`, `_fork_idle_timeout`, `_fork_last_activity`, `_fork_prompted_at`
- Getters/setters: `in_interactive_fork()`, `set_interactive_fork()`, `set_exit_action()`, `pop_exit_action()`, `request_enter_fork()`, `pop_enter_fork()`, `touch_activity()`, `prompted_at()`, `set_prompted_at()`, `clear_prompted()`, `idle_timeout()`

Move the following from `discord_tools.py` verbatim:
- Lines 194-246: `_in_fork`, `_fork_saved`, `_UPDATES_FILE`, `_TZ`, `set_in_fork`, `pop_fork_saved`, `_append_update`, `peek_pending_updates`, `clear_pending_updates`, `pop_pending_updates`

Add new interactive fork state and accessors.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_forks.py -v`
Expected: All PASS.

**Step 5: Update discord_tools.py to import from forks**

Remove the moved state/functions from `discord_tools.py`. Replace with imports from `forks.py`. The MCP tools (`save_context`, `report_updates`) now call `forks.set_in_fork()`, `forks.pop_fork_saved()`, etc.

Update `discord_tools.py` imports at top:
```python
from ollim_bot.forks import (
    clear_pending_updates,
    pop_fork_saved,
    set_in_fork,
    _append_update,
)
```

Re-export for external callers that still import from discord_tools:
```python
from ollim_bot.forks import (  # re-export for callers
    peek_pending_updates,
    pop_pending_updates,
    set_in_fork,
    pop_fork_saved,
)
```

**Step 6: Update test_discord_tools.py**

Remove tests that moved to `test_forks.py` (pending updates tests, fork state tests). Keep only tool-specific tests (chain context, follow_up_chain, save_context/report_updates via tool handlers). Update imports to come from `forks` where needed.

**Step 7: Run full test suite**

Run: `uv run pytest -v`
Expected: All PASS. No regressions.

**Step 8: Commit**

```bash
git add src/ollim_bot/forks.py tests/test_forks.py src/ollim_bot/discord_tools.py tests/test_discord_tools.py
git commit -m "Extract fork state and pending updates into forks.py"
```

---

### Task 2: Rename discord_tools.py to agent_tools.py

**Files:**
- Rename: `src/ollim_bot/discord_tools.py` → `src/ollim_bot/agent_tools.py`
- Rename: `tests/test_discord_tools.py` → `tests/test_agent_tools.py`
- Modify: `src/ollim_bot/agent.py` (update import)
- Modify: `src/ollim_bot/streamer.py` (update import)
- Modify: `src/ollim_bot/bot.py` (update import if any)
- Modify: `src/ollim_bot/views.py` (update import if any)
- Modify: `src/ollim_bot/scheduling/scheduler.py` (update import)
- Modify: `tests/conftest.py` (update monkeypatch if referencing discord_tools)

**Step 1: Rename files with git mv**

```bash
git mv src/ollim_bot/discord_tools.py src/ollim_bot/agent_tools.py
git mv tests/test_discord_tools.py tests/test_agent_tools.py
```

**Step 2: Update all imports**

Search for `discord_tools` across the codebase and replace with `agent_tools`. Key changes:

`agent.py`: `from ollim_bot.agent_tools import agent_server, peek_pending_updates, pop_pending_updates`

`agent_tools.py` (internal): rename `discord_server` variable to `agent_server`

`streamer.py`: `from ollim_bot.agent_tools import pop_fork_saved, set_channel, set_in_fork`

`scheduling/scheduler.py`: `from ollim_bot.agent_tools import ChainContext, set_chain_context`

`test_agent_tools.py`: `from ollim_bot.agent_tools import ...`

`conftest.py`: no change needed (doesn't reference discord_tools directly)

**Step 3: Update agent_tools.py docstring**

Change module docstring from "MCP tools for Discord interactions" to "MCP tools for agent interactions (embeds, buttons, chain follow-ups, fork control)."

**Step 4: Run full test suite**

Run: `uv run pytest -v`
Expected: All PASS.

**Step 5: Commit**

```bash
git add -A
git commit -m "Rename discord_tools.py to agent_tools.py"
```

---

### Task 3: Slim streamer.py, update bot.py and views.py

**Files:**
- Modify: `src/ollim_bot/streamer.py` (remove dispatch/send/run_agent_background)
- Modify: `src/ollim_bot/forks.py` (absorb run_agent_background)
- Modify: `src/ollim_bot/bot.py` (absorb dispatch_agent_response, send_agent_dm as local helpers)
- Modify: `src/ollim_bot/views.py` (compose directly instead of importing dispatch)
- Modify: `src/ollim_bot/scheduling/scheduler.py` (import from forks.py)

**Step 1: Move run_agent_background to forks.py**

Cut `run_agent_background` (lines 123-158) from `streamer.py` and paste into `forks.py`. Update its imports: it needs `stream_to_channel` from `streamer` (for future interactive fork use) and agent_tools functions.

```python
# In forks.py
async def run_agent_background(
    owner: discord.User,
    agent: Agent,
    prompt: str,
    *,
    skip_if_busy: bool,
) -> None:
    """Run agent on a forked session -- discard fork unless save_context is called."""
    dm = await owner.create_dm()

    if skip_if_busy and agent.lock().locked():
        return

    async with agent.lock():
        from ollim_bot.agent_tools import set_channel
        set_channel(dm)
        set_in_fork(True)

        forked_session_id: str | None = None
        promoted = False
        try:
            client = await agent.create_forked_client()
            try:
                forked_session_id = await agent.run_on_client(client, prompt)
            finally:
                if forked_session_id is not None and pop_fork_saved():
                    await agent.swap_client(client, forked_session_id)
                    promoted = True
                if not promoted:
                    await client.disconnect()
        finally:
            set_in_fork(False)
            if forked_session_id is None:
                pop_fork_saved()
```

Use `TYPE_CHECKING` for `Agent` to avoid circular imports.

**Step 2: Add dispatch helpers to bot.py**

Add as local helpers (not exported) inside `create_bot()`:

```python
async def _dispatch(channel, prompt, *, images=None):
    """set_channel -> typing -> stream. Caller must hold agent.lock()."""
    from ollim_bot.agent_tools import set_channel
    set_channel(channel)
    await channel.typing()
    await stream_to_channel(channel, agent.stream_chat(prompt, images=images))

async def _send_dm(prompt):
    """Inject a prompt and stream the response as a DM."""
    dm = await owner.create_dm()
    async with agent.lock():
        await _dispatch(dm, prompt)
```

Note: `_send_dm` captures `owner` from `on_ready` closure. This means it's defined inside `on_ready` or `owner` is stored as a nonlocal.

Actually, `owner` is resolved in `on_ready`. Store it and reference from the helper. The cleanest pattern: define `_dispatch` inside `create_bot` (it captures `agent`), and `_send_dm` inside `on_ready` (it captures `owner`). Or store owner on the bot instance.

For simplicity: store `owner` as a module-level or on the agent after `on_ready` resolves it:

```python
_owner: discord.User | None = None  # set in on_ready

async def _send_dm(prompt):
    assert _owner is not None
    dm = await _owner.create_dm()
    async with agent.lock():
        await _dispatch(dm, prompt)
```

**Step 3: Update views.py to compose directly**

Replace `from ollim_bot.streamer import dispatch_agent_response` with direct composition:

```python
from ollim_bot.agent_tools import set_channel
from ollim_bot.streamer import stream_to_channel

async def _handle_agent_inquiry(interaction, inquiry_id):
    prompt = inquiries.pop(inquiry_id)
    if not prompt:
        await interaction.response.send_message("this button has expired.", ephemeral=True)
        return

    assert _agent is not None
    channel = interaction.channel
    assert isinstance(channel, discord.abc.Messageable)
    await interaction.response.defer()
    async with _agent.lock():
        set_channel(channel)
        await channel.typing()
        await stream_to_channel(channel, _agent.stream_chat(f"[button] {prompt}"))
```

**Step 4: Update scheduler.py imports**

Replace `from ollim_bot.streamer import run_agent_background, send_agent_dm` with:

```python
from ollim_bot.forks import run_agent_background
```

For `send_agent_dm`: the scheduler needs to send foreground DMs. Since `send_agent_dm` is now a local helper in bot.py, the scheduler needs its own version. Add a simple one to `forks.py`:

```python
async def send_agent_dm(
    owner: discord.User,
    agent: Agent,
    prompt: str,
) -> None:
    """Inject a prompt into the agent session and stream the response as a DM."""
    from ollim_bot.agent_tools import set_channel
    from ollim_bot.streamer import stream_to_channel

    dm = await owner.create_dm()
    async with agent.lock():
        set_channel(dm)
        await dm.typing()
        await stream_to_channel(dm, agent.stream_chat(prompt))
```

Scheduler imports: `from ollim_bot.forks import run_agent_background, send_agent_dm`

**Step 5: Remove moved functions from streamer.py**

Delete `dispatch_agent_response`, `send_agent_dm`, `run_agent_background` and their imports. `streamer.py` now contains only `stream_to_channel` and its constants.

**Step 6: Run full test suite**

Run: `uv run pytest -v`
Expected: All PASS.

**Step 7: Commit**

```bash
git add src/ollim_bot/forks.py src/ollim_bot/streamer.py src/ollim_bot/bot.py src/ollim_bot/views.py src/ollim_bot/scheduling/scheduler.py
git commit -m "Clean module boundaries: slim streamer, move dispatch to bot/forks"
```

---

## Phase 2: Interactive Fork Feature

### Task 4: Interactive fork MCP tools

**Files:**
- Modify: `src/ollim_bot/agent_tools.py` (add enter_fork, exit_fork; update save_context, report_updates)
- Modify: `src/ollim_bot/forks.py` (ensure interactive fork state setters are complete)
- Modify: `tests/test_agent_tools.py` (add interactive fork tool tests)

**Step 1: Write failing tests for new tools and dual-mode behavior**

Add to `tests/test_agent_tools.py`:

```python
from ollim_bot.forks import (
    ForkExitAction,
    in_interactive_fork,
    pop_enter_fork,
    pop_exit_action,
    pop_fork_saved,
    set_in_fork,
    set_interactive_fork,
)

# Import new tool handlers
from ollim_bot.agent_tools import enter_fork, exit_fork

_enter = enter_fork.handler
_exit = exit_fork.handler


def test_enter_fork_sets_request():
    result = _run(_enter({"topic": "research ML papers", "idle_timeout": 15}))

    assert "Fork will be created" in result["content"][0]["text"]
    topic, timeout = pop_enter_fork()
    assert topic == "research ML papers"
    assert timeout == 15


def test_enter_fork_no_topic():
    result = _run(_enter({}))

    assert "Fork will be created" in result["content"][0]["text"]
    topic, timeout = pop_enter_fork()
    assert topic is None
    assert timeout == 10


def test_enter_fork_while_in_bg_fork():
    set_in_fork(True)

    result = _run(_enter({}))

    assert "Error" in result["content"][0]["text"]
    set_in_fork(False)


def test_enter_fork_while_in_interactive_fork():
    set_interactive_fork(True, idle_timeout=10)

    result = _run(_enter({}))

    assert "Error" in result["content"][0]["text"]
    set_interactive_fork(False)


def test_exit_fork_not_in_fork():
    result = _run(_exit({}))

    assert "Error" in result["content"][0]["text"]


def test_exit_fork_in_interactive_fork():
    set_interactive_fork(True, idle_timeout=10)

    result = _run(_exit({}))

    assert "discarded" in result["content"][0]["text"].lower()
    assert pop_exit_action() is ForkExitAction.EXIT
    set_interactive_fork(False)


# --- Dual-mode save_context ---

def test_save_context_in_interactive_fork():
    set_interactive_fork(True, idle_timeout=10)

    _run(_save_ctx({}))

    assert pop_exit_action() is ForkExitAction.SAVE
    set_interactive_fork(False)


def test_save_context_bg_fork_unchanged():
    set_in_fork(True)

    _run(_save_ctx({}))

    assert pop_fork_saved() is True
    set_in_fork(False)


# --- Dual-mode report_updates ---

def test_report_updates_in_interactive_fork():
    from ollim_bot.forks import pop_pending_updates
    pop_pending_updates()
    set_interactive_fork(True, idle_timeout=10)

    _run(_report({"message": "found 3 papers"}))

    assert pop_exit_action() is ForkExitAction.REPORT
    assert pop_pending_updates() == ["found 3 papers"]
    set_interactive_fork(False)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_agent_tools.py -v`
Expected: ImportError for `enter_fork`, `exit_fork`.

**Step 3: Implement new tools and update existing tools**

In `agent_tools.py`, add `enter_fork` and `exit_fork` tools:

```python
from ollim_bot.forks import (
    ForkExitAction,
    in_interactive_fork,
    request_enter_fork,
    set_exit_action,
    _in_fork,  # module-level check for bg fork
)

@tool(
    "enter_fork",
    "Start an interactive forked session for research, tangents, or focused work. "
    "The fork branches from the main conversation. Use exit_fork, save_context, or "
    "report_updates to end it.",
    {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "Optional topic for the fork",
            },
            "idle_timeout": {
                "type": "integer",
                "description": "Minutes before idle timeout prompt (default 10)",
            },
        },
    },
)
async def enter_fork(args: dict[str, Any]) -> dict[str, Any]:
    from ollim_bot.forks import _in_fork as bg_fork_active
    if bg_fork_active or in_interactive_fork():
        return {"content": [{"type": "text", "text": "Error: already in a fork"}]}
    request_enter_fork(args.get("topic"), idle_timeout=args.get("idle_timeout", 10))
    return {"content": [{"type": "text", "text": "Fork will be created after this response."}]}


@tool(
    "exit_fork",
    "Exit the current interactive fork. The fork is discarded and the main session resumes.",
    {"type": "object", "properties": {}},
)
async def exit_fork(args: dict[str, Any]) -> dict[str, Any]:
    if not in_interactive_fork():
        return {"content": [{"type": "text", "text": "Error: not in an interactive fork"}]}
    set_exit_action(ForkExitAction.EXIT)
    return {"content": [{"type": "text", "text": "Fork will be discarded after this response."}]}
```

Update `save_context` for dual-mode:

```python
async def save_context(args: dict[str, Any]) -> dict[str, Any]:
    if in_interactive_fork():
        set_exit_action(ForkExitAction.SAVE)
        clear_pending_updates()
        return {"content": [{"type": "text", "text": "Context saved -- fork will be promoted to main session."}]}
    if not _in_fork:
        return {"content": [{"type": "text", "text": "Error: not in a forked session"}]}
    global _fork_saved
    _fork_saved = True
    clear_pending_updates()
    return {"content": [{"type": "text", "text": "Context saved -- this session will be preserved."}]}
```

Update `report_updates` similarly: check `in_interactive_fork()` first, set `ForkExitAction.REPORT` + append update.

Add new tools to the MCP server's tools list and to `allowed_tools` in `agent.py`.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_agent_tools.py -v`
Expected: All PASS.

**Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: All PASS.

**Step 6: Commit**

```bash
git add src/ollim_bot/agent_tools.py src/ollim_bot/agent.py tests/test_agent_tools.py
git commit -m "Add enter_fork/exit_fork tools, dual-mode save_context/report_updates"
```

---

### Task 5: Fork-aware stream_chat routing in agent.py

**Files:**
- Modify: `src/ollim_bot/agent.py`

**Step 1: Add fork client fields and in_fork property**

```python
def __init__(self) -> None:
    # ... existing ...
    self._fork_client: ClaudeSDKClient | None = None
    self._fork_session_id: str | None = None

@property
def in_fork(self) -> bool:
    return self._fork_client is not None
```

**Step 2: Add enter_interactive_fork method**

```python
async def enter_interactive_fork(self, *, idle_timeout: int = 10) -> None:
    """Create an interactive fork client and switch routing to it."""
    from ollim_bot.forks import set_interactive_fork, touch_activity
    self._fork_client = await self.create_forked_client()
    self._fork_session_id = None
    set_interactive_fork(True, idle_timeout=idle_timeout)
    touch_activity()
```

**Step 3: Add exit_interactive_fork method**

```python
async def exit_interactive_fork(self, action: ForkExitAction) -> None:
    """Exit interactive fork: promote (SAVE), report (REPORT), or discard (EXIT)."""
    from ollim_bot.forks import clear_pending_updates, set_interactive_fork
    client = self._fork_client
    session_id = self._fork_session_id
    self._fork_client = None
    self._fork_session_id = None
    set_interactive_fork(False)

    if client is None:
        return

    if action is ForkExitAction.SAVE and session_id is not None:
        clear_pending_updates()
        await self.swap_client(client, session_id)
    else:
        with contextlib.suppress(CLIConnectionError):
            await client.interrupt()
        with contextlib.suppress(RuntimeError):
            await client.disconnect()
```

**Step 4: Make stream_chat fork-aware**

At the top of `stream_chat`, add fork routing:

```python
async def stream_chat(self, message, *, images=None):
    if self._fork_client is not None:
        client = self._fork_client
        message = _prepend_context(message, clear=False)
    else:
        message = _prepend_context(message)
        client = await self._get_client()
    # ... rest uses `client` variable
```

Update session ID saving in the `ResultMessage` handler:

```python
elif isinstance(msg, ResultMessage):
    if msg.result:
        result_text = msg.result
    if self._fork_client is not None and client is self._fork_client:
        self._fork_session_id = msg.session_id
    elif self._client is client:
        save_session_id(msg.session_id)
```

Also make `chat()` fork-aware with the same pattern (lines 340-367).

**Step 5: Add allowed_tools entries**

In `Agent.__init__`, add to `allowed_tools`:
```python
"mcp__discord__enter_fork",
"mcp__discord__exit_fork",
```

**Step 6: Run full test suite**

Run: `uv run pytest -v`
Expected: All PASS.

**Step 7: Commit**

```bash
git add src/ollim_bot/agent.py
git commit -m "Fork-aware stream_chat routing and interactive fork lifecycle"
```

---

### Task 6: /fork slash command and post-stream transitions

**Files:**
- Modify: `src/ollim_bot/bot.py`

**Step 1: Add post-stream fork transition helper**

Inside `create_bot()`, add a helper that checks fork state after every `stream_to_channel` call:

```python
async def _check_fork_transitions(channel):
    """Check if agent requested fork entry/exit during last response."""
    from ollim_bot.forks import (
        ForkExitAction,
        enter_fork_requested,
        pop_enter_fork,
        pop_exit_action,
        touch_activity,
    )

    if enter_fork_requested():
        topic, timeout = pop_enter_fork()
        await agent.enter_interactive_fork(idle_timeout=timeout)
        await channel.send(embed=_fork_enter_embed(topic))
        if topic:
            set_channel(channel)
            await channel.typing()
            await stream_to_channel(channel, agent.stream_chat(topic))
            touch_activity()
            await _check_fork_transitions(channel)  # recurse
        return

    exit_action = pop_exit_action()
    if exit_action is not ForkExitAction.NONE:
        await agent.exit_interactive_fork(exit_action)
        await channel.send(embed=_fork_exit_embed(exit_action))
```

**Step 2: Update on_message to call transition check and track activity**

After `stream_to_channel` in `on_message`:

```python
async with agent.lock():
    await _dispatch(message.channel, content, images=images or None)
    from ollim_bot.forks import touch_activity, clear_prompted, in_interactive_fork
    if in_interactive_fork():
        touch_activity()
        clear_prompted()  # user message clears timeout prompt
    await _check_fork_transitions(message.channel)
```

**Step 3: Add /fork slash command**

```python
@bot.tree.command(name="fork", description="Start a forked conversation")
@discord.app_commands.describe(topic="Optional topic to start with")
async def slash_fork(interaction: discord.Interaction, topic: str | None = None):
    from ollim_bot.forks import in_interactive_fork
    if agent.in_fork:
        await interaction.response.send_message("already in a fork.", ephemeral=True)
        return
    await interaction.response.defer()
    async with agent.lock():
        await agent.enter_interactive_fork()
        channel = interaction.channel
        await interaction.followup.send(embed=_fork_enter_embed(topic))
        if topic and channel:
            set_channel(channel)
            await channel.typing()
            await stream_to_channel(channel, agent.stream_chat(topic))
            from ollim_bot.forks import touch_activity
            touch_activity()
            await _check_fork_transitions(channel)
```

**Step 4: Run full test suite**

Run: `uv run pytest -v`
Expected: All PASS.

**Step 5: Commit**

```bash
git add src/ollim_bot/bot.py
git commit -m "Add /fork slash command and post-stream fork transitions"
```

---

### Task 7: Fork enter/exit embeds and button handlers

**Files:**
- Modify: `src/ollim_bot/bot.py` (embed builder helpers)
- Modify: `src/ollim_bot/views.py` (fork button handlers)

**Step 1: Add fork embed builders to bot.py**

```python
def _fork_enter_embed(topic: str | None) -> discord.Embed:
    embed = discord.Embed(
        title="Forked Session",
        description=f"Topic: {topic}" if topic else "Open session",
        color=discord.Color.purple(),
    )
    view = View(timeout=None)
    view.add_item(Button(label="Save Context", style=discord.ButtonStyle.success, custom_id="act:fork_save:_"))
    view.add_item(Button(label="Report", style=discord.ButtonStyle.primary, custom_id="act:fork_report:_"))
    view.add_item(Button(label="Exit Fork", style=discord.ButtonStyle.danger, custom_id="act:fork_exit:_"))
    # Return (embed, view) tuple — caller sends both
    return embed  # actually need to return view too

# Better: return a tuple or send both
async def _send_fork_enter(channel, topic: str | None):
    embed = discord.Embed(
        title="Forked Session",
        description=f"Topic: {topic}" if topic else "Open session",
        color=discord.Color.purple(),
    )
    view = View(timeout=None)
    view.add_item(Button(label="Save Context", style=discord.ButtonStyle.success, custom_id="act:fork_save:_"))
    view.add_item(Button(label="Report", style=discord.ButtonStyle.primary, custom_id="act:fork_report:_"))
    view.add_item(Button(label="Exit Fork", style=discord.ButtonStyle.danger, custom_id="act:fork_exit:_"))
    await channel.send(embed=embed, view=view)


def _fork_exit_embed(action: ForkExitAction) -> discord.Embed:
    labels = {
        ForkExitAction.SAVE: ("context saved — promoted to main session", discord.Color.green()),
        ForkExitAction.REPORT: ("summary reported — fork discarded", discord.Color.blue()),
        ForkExitAction.EXIT: ("fork discarded", discord.Color.greyple()),
    }
    label, color = labels[action]
    return discord.Embed(title="Fork Ended", description=label, color=color)
```

Update `_check_fork_transitions` and `slash_fork` to use `_send_fork_enter` instead of bare `channel.send(embed=...)`.

**Step 2: Add fork button handlers to views.py**

Add to the `handlers` dict in `ActionButton.callback`:

```python
handlers = {
    "task_done": _handle_task_done,
    "task_del": _handle_task_delete,
    "event_del": _handle_event_delete,
    "agent": _handle_agent_inquiry,
    "dismiss": _handle_dismiss,
    "fork_save": _handle_fork_save,
    "fork_report": _handle_fork_report,
    "fork_exit": _handle_fork_exit,
}
```

Implement handlers:

```python
async def _handle_fork_save(interaction: discord.Interaction, _data: str) -> None:
    from ollim_bot.forks import ForkExitAction, in_interactive_fork
    if not in_interactive_fork():
        await interaction.response.send_message("no active fork.", ephemeral=True)
        return
    assert _agent is not None
    await interaction.response.defer()
    async with _agent.lock():
        await _agent.exit_interactive_fork(ForkExitAction.SAVE)
    await interaction.followup.send("context saved — promoted to main session.")


async def _handle_fork_report(interaction: discord.Interaction, _data: str) -> None:
    from ollim_bot.forks import ForkExitAction, _append_update, in_interactive_fork
    if not in_interactive_fork():
        await interaction.response.send_message("no active fork.", ephemeral=True)
        return
    assert _agent is not None
    _append_update("fork exited via button (report)")
    await interaction.response.defer()
    async with _agent.lock():
        await _agent.exit_interactive_fork(ForkExitAction.REPORT)
    await interaction.followup.send("summary reported — fork discarded.")


async def _handle_fork_exit(interaction: discord.Interaction, _data: str) -> None:
    from ollim_bot.forks import ForkExitAction, in_interactive_fork
    if not in_interactive_fork():
        await interaction.response.send_message("no active fork.", ephemeral=True)
        return
    assert _agent is not None
    await interaction.response.defer()
    async with _agent.lock():
        await _agent.exit_interactive_fork(ForkExitAction.EXIT)
    await interaction.followup.send("fork discarded.")
```

**Step 3: Run full test suite**

Run: `uv run pytest -v`
Expected: All PASS.

**Step 4: Commit**

```bash
git add src/ollim_bot/bot.py src/ollim_bot/views.py
git commit -m "Fork enter/exit embeds and button handlers"
```

---

### Task 8: Timeout timer

**Files:**
- Modify: `src/ollim_bot/forks.py` (timeout check function)
- Modify: `src/ollim_bot/scheduling/scheduler.py` (register timeout job)

**Step 1: Write failing test for timeout detection**

Add to `tests/test_forks.py`:

```python
import time

def test_fork_idle_detection():
    set_interactive_fork(True, idle_timeout=10)
    touch_activity()

    from ollim_bot.forks import is_idle
    assert is_idle() is False

    # Simulate time passing by backdating _fork_last_activity
    import ollim_bot.forks as forks_mod
    forks_mod._fork_last_activity = time.monotonic() - 601

    assert is_idle() is True
    set_interactive_fork(False)


def test_prompted_tracking():
    from ollim_bot.forks import clear_prompted, prompted_at, set_prompted_at

    set_interactive_fork(True, idle_timeout=10)
    assert prompted_at() is None

    set_prompted_at()
    assert prompted_at() is not None

    clear_prompted()
    assert prompted_at() is None
    set_interactive_fork(False)


def test_should_auto_exit():
    from ollim_bot.forks import set_prompted_at, should_auto_exit
    import ollim_bot.forks as forks_mod

    set_interactive_fork(True, idle_timeout=10)
    set_prompted_at()
    assert should_auto_exit() is False

    # Backdate prompted_at
    forks_mod._fork_prompted_at = time.monotonic() - 601

    assert should_auto_exit() is True
    set_interactive_fork(False)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_forks.py::test_fork_idle_detection -v`
Expected: ImportError for `is_idle`.

**Step 3: Implement timeout helpers in forks.py**

```python
def is_idle() -> bool:
    """True if interactive fork has been idle longer than idle_timeout."""
    if not _in_interactive_fork:
        return False
    return time.monotonic() - _fork_last_activity > _fork_idle_timeout * 60

def should_auto_exit() -> bool:
    """True if timeout prompt was sent and idle_timeout has passed since."""
    if _fork_prompted_at is None:
        return False
    return time.monotonic() - _fork_prompted_at > _fork_idle_timeout * 60
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_forks.py -v`
Expected: All PASS.

**Step 5: Register timeout job in scheduler.py**

Add a fork timeout check to `setup_scheduler`:

```python
@scheduler.scheduled_job(IntervalTrigger(seconds=60))
async def check_fork_timeout() -> None:
    from ollim_bot.forks import (
        ForkExitAction,
        _append_update,
        in_interactive_fork,
        is_idle,
        set_prompted_at,
        should_auto_exit,
        touch_activity,
    )
    from ollim_bot.agent_tools import set_channel
    from ollim_bot.streamer import stream_to_channel

    if not in_interactive_fork():
        return

    if should_auto_exit():
        dm = await owner.create_dm()
        _append_update("fork auto-exited after idle timeout")
        async with agent.lock():
            await agent.exit_interactive_fork(ForkExitAction.REPORT)
            # Send exit embed
            embed = discord.Embed(
                title="Fork Ended",
                description="auto-exited after idle timeout — summary reported",
                color=discord.Color.greyple(),
            )
            await dm.send(embed=embed)
        return

    if is_idle():
        set_prompted_at()
        dm = await owner.create_dm()
        timeout = forks.idle_timeout()
        async with agent.lock():
            set_channel(dm)
            await dm.typing()
            await stream_to_channel(dm, agent.stream_chat(
                f"[fork-timeout] This fork has been idle for {timeout} minutes. "
                "Decide what to do: use `save_context` to promote to main session, "
                "`report_updates(message)` to send a summary, or `exit_fork` to discard. "
                "If Julius is still engaged, ask them what they'd like to do."
            ))
            touch_activity()
```

**Step 6: Run full test suite**

Run: `uv run pytest -v`
Expected: All PASS.

**Step 7: Commit**

```bash
git add src/ollim_bot/forks.py src/ollim_bot/scheduling/scheduler.py tests/test_forks.py
git commit -m "Fork idle timeout detection and auto-exit scheduler job"
```

---

### Task 9: System prompt and CLAUDE.md updates

**Files:**
- Modify: `src/ollim_bot/prompts.py`
- Modify: `CLAUDE.md`

**Step 1: Add interactive forks section to SYSTEM_PROMPT**

Add before the "## Background Session Management" section:

```python
## Interactive Forks

You can enter a forked session for research, tangents, or focused work that
shouldn't pollute the main conversation. Forks branch from the main session.

| Tool | Effect |
|------|--------|
| `enter_fork(topic?, idle_timeout=10)` | Start an interactive fork |
| `exit_fork` | Discard fork, return to main session |
| `save_context` | Promote fork to main session (full context preserved) |
| `report_updates(message)` | Queue summary, discard fork |

Julius can also use `/fork [topic]` to start a fork from Discord.

Rules:
- Forks always branch from the main session (never nested)
- Use for research, complex tool chains, or anything tangential
- After idle_timeout minutes of inactivity, you'll be prompted to exit
- If Julius doesn't respond after another timeout period, auto-exit with report_updates
- When you're done, present an embed with all 3 exit options so Julius can choose
```

**Step 2: Update CLAUDE.md architecture section**

Update the module list to reflect new `forks.py` and renamed `agent_tools.py`. Add interactive forks documentation section.

**Step 3: Run full test suite (final check)**

Run: `uv run pytest -v`
Expected: All PASS.

**Step 4: Commit**

```bash
git add src/ollim_bot/prompts.py CLAUDE.md
git commit -m "Document interactive forks in system prompt and CLAUDE.md"
```

---

## Phase 3: Verification

### Task 10: End-to-end verification

**Step 1: Run full test suite with coverage**

Run: `uv run pytest --cov=ollim_bot -v`
Expected: All PASS, no regressions.

**Step 2: Verify no import cycles**

Run: `python -c "import ollim_bot.forks; import ollim_bot.agent_tools; import ollim_bot.agent; import ollim_bot.bot; import ollim_bot.views; import ollim_bot.streamer; print('no import cycles')"`
Expected: "no import cycles"

**Step 3: Verify bot starts**

Run: `timeout 10 uv run ollim-bot 2>&1 || true`
Expected: Bot attempts to connect (may fail without token, but no import errors).

**Step 4: Final commit if any fixups needed**

```bash
git add -A
git commit -m "Fix any remaining issues from interactive forks implementation"
```
