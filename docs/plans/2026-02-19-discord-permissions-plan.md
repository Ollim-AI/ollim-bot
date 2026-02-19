# Discord Permission Management Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Route Claude Agent SDK permission controls through the Discord interface -- dynamic mode switching via `/permissions` and inline reaction-based tool approval via `canUseTool`.

**Architecture:** New `permissions.py` module owns the approval state (pending futures, session-allowed set). `formatting.py` extracted from `agent.py` to avoid circular imports. `canUseTool` callback blocks on Discord reactions (60s timeout, auto-deny). `/permissions` slash command delegates to `client.set_permission_mode()`.

**Tech Stack:** Claude Agent SDK (`PermissionResultAllow`, `PermissionResultDeny`, `set_permission_mode`), discord.py (reactions, slash commands), asyncio (Futures for cross-coroutine signaling)

**Design doc:** `docs/plans/2026-02-19-discord-permissions-design.md`

---

### Task 1: Extract `formatting.py` from `agent.py`

Move tool-label formatting helpers to a shared module. This breaks the potential circular import between `agent.py` and `permissions.py`.

**Files:**
- Create: `src/ollim_bot/formatting.py`
- Modify: `src/ollim_bot/agent.py` (remove helpers, import from formatting)
- Test: `tests/test_formatting.py`

**Step 1: Write the failing test**

```python
# tests/test_formatting.py
"""Tests for formatting.py — tool label formatting."""

from ollim_bot.formatting import format_tool_label


def test_simple_tool():
    assert format_tool_label("Read", '{"file_path": "/home/user/notes.md"}') == "Read(notes.md)"


def test_mcp_tool_strips_prefix():
    assert format_tool_label("mcp__discord__ping_user", "") == "ping_user"


def test_bash_truncates_command():
    long_cmd = "a" * 100
    label = format_tool_label("Bash", f'{{"command": "{long_cmd}"}}')
    # Bash truncates to 50 chars
    assert len(label) < 60


def test_unknown_tool_returns_name():
    assert format_tool_label("UnknownTool", '{"foo": "bar"}') == "UnknownTool"


def test_bad_json_returns_name():
    assert format_tool_label("Read", "not json") == "Read"


def test_path_shortening():
    label = format_tool_label("Write", '{"file_path": "/home/user/.ollim-bot/reminders/foo.md"}')
    assert label == "Write(reminders/foo.md)"


def test_grep_multiple_keys():
    label = format_tool_label("Grep", '{"pattern": "TODO", "path": "/home/user/src"}')
    assert "TODO" in label
    assert "src" in label
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_formatting.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ollim_bot.formatting'`

**Step 3: Create `formatting.py` and update `agent.py`**

Create `src/ollim_bot/formatting.py`:

```python
"""Tool-label formatting helpers shared by agent and permissions."""

import json

# Tool name → input key(s) to extract for informative labels.
TOOL_LABEL_KEYS: dict[str, str | tuple[str, ...]] = {
    "Read": "file_path",
    "Write": "file_path",
    "Edit": "file_path",
    "Bash": "command",
    "Grep": ("pattern", "path"),
    "Glob": "pattern",
    "WebSearch": "query",
    "WebFetch": "url",
    "Task": "description",
}


def _shorten_path(path: str) -> str:
    """Reduce a path to its last two components."""
    parts = path.rstrip("/").split("/")
    return "/".join(parts[-2:]) if len(parts) > 2 else path


def _escape_md(s: str) -> str:
    """Escape characters that break Discord italic markdown."""
    return s.replace("*", "\\*").replace("_", "\\_")


def format_tool_label(name: str, input_json: str) -> str:
    """Build a descriptive tool-use label like ``Write(reminders/foo.md)``."""
    if name.startswith("mcp__discord__"):
        return name.removeprefix("mcp__discord__")

    try:
        inp = json.loads(input_json) if input_json else {}
    except json.JSONDecodeError:
        return name

    keys = TOOL_LABEL_KEYS.get(name)
    if keys is None:
        return name
    if isinstance(keys, str):
        keys = (keys,)

    parts: list[str] = []
    for key in keys:
        val = inp.get(key, "")
        if not val:
            continue
        if key == "file_path":
            val = _shorten_path(val)
        elif key == "command":
            val = val.split("\n")[0][:50]
        parts.append(_escape_md(str(val)))

    return f"{name}({', '.join(parts)})" if parts else name
```

Update `agent.py`: remove `_TOOL_LABEL_KEYS`, `_shorten_path`, `_escape_md`, `_format_tool_label`. Replace with:

```python
from ollim_bot.formatting import format_tool_label
```

And change the one usage at line 422:

```python
label = format_tool_label(tool_name, tool_input_buf)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_formatting.py tests/ -v`
Expected: ALL PASS (new tests + existing tests still pass)

**Step 5: Commit**

```
git add src/ollim_bot/formatting.py tests/test_formatting.py src/ollim_bot/agent.py
git commit -m "Extract formatting.py from agent.py to enable sharing with permissions"
```

---

### Task 2: Create `permissions.py` — state management and `resolve_approval`

Build the core state: `_session_allowed`, `_pending`, `_channel`, and the resolver. No Discord I/O yet — just the pure state functions that are unit-testable.

**Files:**
- Create: `src/ollim_bot/permissions.py`
- Test: `tests/test_permissions.py`

**Step 1: Write the failing tests**

```python
# tests/test_permissions.py
"""Tests for permissions.py — session-allowed set, resolve, cancel, reset."""

import asyncio

from ollim_bot.permissions import (
    cancel_pending,
    is_session_allowed,
    reset,
    resolve_approval,
    session_allow,
)


def test_session_allowed_default_empty():
    reset()
    assert is_session_allowed("Bash") is False


def test_session_allow_and_check():
    reset()
    session_allow("Bash(rm *)")

    assert is_session_allowed("Bash(rm *)") is True
    assert is_session_allowed("Bash(ls)") is False


def test_reset_clears_session_allowed():
    reset()
    session_allow("WebFetch")

    reset()

    assert is_session_allowed("WebFetch") is False


def test_resolve_approval_sets_future():
    loop = asyncio.new_event_loop()
    future: asyncio.Future[str] = loop.create_future()
    reset()

    # Simulate: store a pending future, then resolve it
    from ollim_bot.permissions import _pending

    _pending[12345] = future
    resolve_approval(12345, "✅")

    assert future.done()
    assert loop.run_until_complete(future) == "✅"
    loop.close()


def test_resolve_approval_ignores_unknown_message():
    reset()
    # Should not raise
    resolve_approval(99999, "✅")


def test_resolve_approval_ignores_already_done():
    loop = asyncio.new_event_loop()
    future: asyncio.Future[str] = loop.create_future()
    future.set_result("✅")
    reset()

    from ollim_bot.permissions import _pending

    _pending[12345] = future

    # Should not raise InvalidStateError
    resolve_approval(12345, "❌")

    assert loop.run_until_complete(future) == "✅"  # Still the original
    loop.close()


def test_cancel_pending_cancels_all():
    loop = asyncio.new_event_loop()
    f1: asyncio.Future[str] = loop.create_future()
    f2: asyncio.Future[str] = loop.create_future()
    reset()

    from ollim_bot.permissions import _pending

    _pending[1] = f1
    _pending[2] = f2

    cancel_pending()

    assert f1.cancelled()
    assert f2.cancelled()

    from ollim_bot.permissions import _pending as after

    assert len(after) == 0
    loop.close()


def test_reset_cancels_pending_and_clears_allowed():
    loop = asyncio.new_event_loop()
    future: asyncio.Future[str] = loop.create_future()
    reset()

    from ollim_bot.permissions import _pending

    _pending[1] = future
    session_allow("Bash")

    reset()

    assert future.cancelled()
    assert is_session_allowed("Bash") is False
    loop.close()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_permissions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ollim_bot.permissions'`

**Step 3: Create `permissions.py` with state functions**

```python
"""Discord-based permission approval for the Claude Agent SDK canUseTool callback."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any

from claude_agent_sdk.types import (
    PermissionResult,
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)

from ollim_bot.forks import in_bg_fork

if TYPE_CHECKING:
    import discord

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_channel: discord.abc.Messageable | None = None
_pending: dict[int, asyncio.Future[str]] = {}
_session_allowed: set[str] = set()

# Emoji constants
APPROVE = "✅"
DENY = "❌"
ALWAYS = "🔓"


def set_channel(channel: object) -> None:
    """Set channel global — called alongside agent_tools.set_channel."""
    global _channel
    _channel = channel


# ---------------------------------------------------------------------------
# Session-allowed management
# ---------------------------------------------------------------------------


def is_session_allowed(tool_name: str) -> bool:
    return tool_name in _session_allowed


def session_allow(tool_name: str) -> None:
    _session_allowed.add(tool_name)


# ---------------------------------------------------------------------------
# Future resolution
# ---------------------------------------------------------------------------


def resolve_approval(message_id: int, emoji: str) -> None:
    """Resolve a pending approval Future. Safe to call from any context."""
    future = _pending.get(message_id)
    if future is None or future.done():
        return
    future.set_result(emoji)


def cancel_pending() -> None:
    """Cancel all pending approval Futures."""
    for future in _pending.values():
        if not future.done():
            future.cancel()
    _pending.clear()


def reset() -> None:
    """Clear session-allowed set and cancel all pending Futures. Called on /clear."""
    cancel_pending()
    _session_allowed.clear()
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_permissions.py -v`
Expected: ALL PASS

**Step 5: Commit**

```
git add src/ollim_bot/permissions.py tests/test_permissions.py
git commit -m "Add permissions.py with state management and resolve_approval"
```

---

### Task 3: Add `request_approval` and `handle_tool_permission` to `permissions.py`

The Discord I/O function that sends the approval message, adds reactions, and awaits the Future. Plus the `canUseTool` callback entry point.

**Files:**
- Modify: `src/ollim_bot/permissions.py`
- Test: `tests/test_permissions.py` (add async tests for the callback routing)

**Step 1: Write the failing tests**

Add to `tests/test_permissions.py`:

```python
import pytest
from ollim_bot.forks import set_in_fork
from ollim_bot.permissions import handle_tool_permission

from claude_agent_sdk.types import PermissionResultDeny, ToolPermissionContext


@pytest.mark.asyncio
async def test_handle_tool_permission_denies_bg_fork():
    set_in_fork(True)
    try:
        result = await handle_tool_permission("Bash", {"command": "rm -rf /"}, ToolPermissionContext())

        assert isinstance(result, PermissionResultDeny)
        assert "not allowed" in result.message
    finally:
        set_in_fork(False)


@pytest.mark.asyncio
async def test_handle_tool_permission_allows_session_allowed():
    reset()
    session_allow("WebFetch")
    try:
        result = await handle_tool_permission("WebFetch", {"url": "https://example.com"}, ToolPermissionContext())

        assert isinstance(result, PermissionResultAllow)
    finally:
        reset()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_permissions.py::test_handle_tool_permission_denies_bg_fork -v`
Expected: FAIL — `cannot import name 'handle_tool_permission'`

**Step 3: Add `request_approval` and `handle_tool_permission`**

Add to `permissions.py`:

```python
from ollim_bot.formatting import format_tool_label

# ---------------------------------------------------------------------------
# Approval flow
# ---------------------------------------------------------------------------


async def request_approval(tool_name: str, input_data: dict[str, Any]) -> PermissionResult:
    """Send approval message to Discord, await reaction, return result."""
    if is_session_allowed(tool_name):
        return PermissionResultAllow()

    import json

    channel = _channel
    assert channel is not None, "permissions.set_channel() not called before approval"

    label = format_tool_label(tool_name, json.dumps(input_data))
    text = f"`{label}` — react {APPROVE} allow {DENY} deny {ALWAYS} always"

    try:
        msg = await channel.send(text)
        await msg.add_reaction(APPROVE)
        await msg.add_reaction(DENY)
        await msg.add_reaction(ALWAYS)
    except Exception:
        return PermissionResultDeny(message="failed to send approval request")

    loop = asyncio.get_running_loop()
    future: asyncio.Future[str] = loop.create_future()
    _pending[msg.id] = future

    try:
        emoji = await asyncio.wait_for(future, timeout=60)
    except (TimeoutError, asyncio.CancelledError):
        with contextlib.suppress(Exception):
            await msg.edit(content=f"~~{text}~~ — timed out")
        return PermissionResultDeny(message="approval timed out")
    finally:
        _pending.pop(msg.id, None)

    if emoji == APPROVE:
        with contextlib.suppress(Exception):
            await msg.edit(content=f"~~{text}~~ — allowed")
        return PermissionResultAllow()
    elif emoji == ALWAYS:
        session_allow(tool_name)
        with contextlib.suppress(Exception):
            await msg.edit(content=f"~~{text}~~ — always allowed")
        return PermissionResultAllow()
    else:
        with contextlib.suppress(Exception):
            await msg.edit(content=f"~~{text}~~ — denied")
        return PermissionResultDeny(message="denied via Discord")


async def handle_tool_permission(
    tool_name: str,
    input_data: dict[str, Any],
    context: ToolPermissionContext,
) -> PermissionResult:
    """canUseTool callback — routes bg forks to deny, everything else to Discord."""
    if in_bg_fork():
        return PermissionResultDeny(message=f"{tool_name} is not allowed")
    return await request_approval(tool_name, input_data)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_permissions.py -v`
Expected: ALL PASS

Check if pytest-asyncio is available. If not:

Run: `uv add --dev pytest-asyncio`

**Step 5: Commit**

```
git add src/ollim_bot/permissions.py tests/test_permissions.py
git commit -m "Add request_approval and handle_tool_permission to permissions.py"
```

---

### Task 4: Wire `permissions.py` into `agent.py`

Replace `_deny_unlisted_tools` with `handle_tool_permission`. Add `cancel_pending` to `interrupt`, `clear`, and `exit_interactive_fork`. Add `set_permission_mode`.

**Files:**
- Modify: `src/ollim_bot/agent.py`

**Step 1: Update imports in agent.py**

Replace:
```python
from claude_agent_sdk.types import (
    PermissionResultDeny,
    StreamEvent,
    ToolPermissionContext,
)
```

With:
```python
from claude_agent_sdk.types import StreamEvent

from ollim_bot.permissions import cancel_pending, handle_tool_permission, reset as reset_permissions
```

**Step 2: Remove `_deny_unlisted_tools`**

Delete the entire function (lines 107-112 currently).

**Step 3: Update `ClaudeAgentOptions`**

Change `can_use_tool=_deny_unlisted_tools` to `can_use_tool=handle_tool_permission`.

**Step 4: Add `cancel_pending` calls**

In `interrupt()`:
```python
async def interrupt(self) -> None:
    cancel_pending()
    if self._client:
        await self._client.interrupt()
```

In `clear()`:
```python
async def clear(self) -> None:
    reset_permissions()
    if self._fork_client:
        await self.exit_interactive_fork(ForkExitAction.EXIT)
    await self._drop_client()
    delete_session_id()
```

In `exit_interactive_fork()`, add before the client teardown:
```python
cancel_pending()
```

**Step 5: Add `set_permission_mode`**

```python
async def set_permission_mode(self, mode: str) -> None:
    """Switch SDK permission mode. Fork-scoped when in interactive fork."""
    if self._fork_client:
        await self._fork_client.set_permission_mode(mode)
    elif self._client:
        await self._client.set_permission_mode(mode)
        self.options = replace(self.options, permission_mode=mode)
    else:
        self.options = replace(self.options, permission_mode=mode)
```

**Step 6: Run all tests**

Run: `uv run pytest -v`
Expected: ALL PASS

**Step 7: Commit**

```
git add src/ollim_bot/agent.py
git commit -m "Wire handle_tool_permission into agent, add set_permission_mode"
```

---

### Task 5: Wire into `bot.py` — reaction handler, `/permissions`, channel sync

**Files:**
- Modify: `src/ollim_bot/bot.py`

**Step 1: Add imports**

```python
from ollim_bot import permissions
```

**Step 2: Add channel sync to `_dispatch`**

In the `_dispatch` function, after `set_channel(channel)`:
```python
permissions.set_channel(channel)
```

**Step 3: Add `on_raw_reaction_add` event**

After the `on_message` event handler:

```python
@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if bot.user and payload.user_id == bot.user.id:
        return
    permissions.resolve_approval(payload.message_id, str(payload.emoji))
```

**Step 4: Add `/permissions` slash command**

After the existing slash commands:

```python
@bot.tree.command(name="permissions", description="Set permission mode")
@discord.app_commands.describe(mode="Permission mode to use")
@discord.app_commands.choices(
    mode=[
        discord.app_commands.Choice(name="default", value="default"),
        discord.app_commands.Choice(name="acceptEdits", value="acceptEdits"),
        discord.app_commands.Choice(name="bypassPermissions", value="bypassPermissions"),
    ]
)
async def slash_permissions(
    interaction: discord.Interaction, mode: discord.app_commands.Choice[str]
):
    await agent.set_permission_mode(mode.value)
    await interaction.response.send_message(f"permissions: {mode.value}")
```

**Step 5: Run all tests**

Run: `uv run pytest -v`
Expected: ALL PASS

**Step 6: Commit**

```
git add src/ollim_bot/bot.py
git commit -m "Add /permissions command, reaction handler, and channel sync"
```

---

### Task 6: Add contextvar ordering comment to `forks.py`

**Files:**
- Modify: `src/ollim_bot/forks.py`

**Step 1: Add comment**

In `run_agent_background`, before `set_in_fork(True)`:

```python
    # CRITICAL: set_in_fork(True) must precede create_forked_client() so the
    # contextvar propagates through the SDK's task-group spawn chain to reach
    # the can_use_tool callback. See design doc for details.
```

**Step 2: Commit**

```
git add src/ollim_bot/forks.py
git commit -m "Document contextvar ordering requirement in run_agent_background"
```

---

### Task 7: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Add permissions section**

Add after the "Discord embeds & buttons" section:

```markdown
## Permissions
- `permissions.py` -- Discord-based tool approval via reactions, session-allowed set, permission mode switching
- `formatting.py` -- Tool-label formatting helpers (extracted from agent.py, shared by agent and permissions)
- `canUseTool` callback routes through Discord for main/interactive-fork sessions; bg forks get immediate deny
- Approval flow: send message with tool label, add reactions (approve/deny/always), await Future (60s timeout, auto-deny)
- `_session_allowed` set: shared across main + interactive forks, reset on `/clear`
- `/permissions` slash command: switches SDK permission mode (default, acceptEdits, bypassPermissions)
- Permission mode is fork-scoped (only affects active client); `/model` is shared (affects both)
- `cancel_pending()` called on interrupt, fork exit, and `/clear`
```

**Step 2: Commit**

```
git add CLAUDE.md
git commit -m "Document permissions system in CLAUDE.md"
```
