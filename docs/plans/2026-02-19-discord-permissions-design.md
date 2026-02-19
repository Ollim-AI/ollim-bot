# Discord Permission Management Design

Route Claude Agent SDK permission controls through the Discord interface.

## Goals

1. **Dynamic permission modes** via `/permissions` slash command (default, acceptEdits, bypassPermissions)
2. **`canUseTool` routed through Discord** -- inline reactions for approve/deny when a non-whitelisted tool is requested
3. **Background forks stay whitelist-only** -- never block on user input

## Three Contexts

| Context | Detection | Permission behavior |
|---|---|---|
| Main session | `not in_bg_fork() and not in_interactive_fork()` | Discord approval flow |
| Interactive fork | `in_interactive_fork()` | Discord approval flow (user is present) |
| Background fork | `in_bg_fork()` (contextvar) | Immediate deny -- no Discord interaction |

## New Module: `permissions.py`

### State

- `_pending: dict[int, asyncio.Future[str]]` -- Discord message ID to Future resolving with reaction emoji
- `_channel: discord.abc.Messageable | None` -- set before each `stream_chat()`, same pattern as `agent_tools._channel`; typed with `TYPE_CHECKING` import
- `_session_allowed: set[str]` -- tool names added via unlock reaction, reset on `/clear`

### Reactions

- Approve: checkmark
- Deny: X
- Always allow (session): unlock

### `request_approval(tool_name: str, input_data: dict[str, Any]) -> PermissionResult`

1. Check `_session_allowed` -- if tool matches, return `PermissionResultAllow()` immediately
2. Format message with tool label (uses `format_tool_label` from extracted module)
3. Send message to `_channel` (assert not None -- fail fast), add three reactions programmatically
4. Create `asyncio.Future`, store in `_pending[msg.id]`
5. `await asyncio.wait_for(future, timeout=60)` in a try/except/finally:
   - `TimeoutError` -> return `PermissionResultDeny(message="approval timed out")`
   - `finally` -> `_pending.pop(msg.id, None)` (prevents `InvalidStateError` on late reactions)
6. Approve reaction: return `PermissionResultAllow()`
7. Deny reaction: return `PermissionResultDeny(message="denied via Discord")`
8. Unlock reaction: add tool name to `_session_allowed`, return `PermissionResultAllow()`
9. Edit original message to show decision (suppress `discord.NotFound`)

Entire function wrapped in try/except for Discord I/O failures -- return `PermissionResultDeny` on any unexpected exception (SDK swallows exceptions and sends error to CLI, but explicit deny is cleaner).

### `resolve_approval(message_id: int, emoji: str) -> None`

Called from `on_raw_reaction_add` in bot.py. Guards:
- `_pending.get(message_id)` -- silently return if not a pending approval
- `future.done()` -- silently return if already resolved (handles double-reactions)
- Then `future.set_result(emoji)`

No lock needed.

### `reset() -> None`

Clears `_session_allowed` and cancels all pending futures. Called on `/clear`.

### `cancel_pending() -> None`

Cancels all pending futures (returns deny). Called on:
- `agent.interrupt()` -- user sent new message mid-approval
- `agent.exit_interactive_fork()` -- fork ended while approval pending

## Shared Utility: Extract `format_tool_label`

Move `_format_tool_label`, `_TOOL_LABEL_KEYS`, `_shorten_path`, `_escape_md` out of `agent.py` into a shared location (e.g., `formatting.py`). This avoids a circular import: `agent.py` imports `permissions.py` (for the callback), `permissions.py` would import `agent.py` (for the label formatter).

Import direction after extraction:
- `agent.py` -> `formatting.py` (for stream labels)
- `permissions.py` -> `formatting.py` (for approval messages)
- `agent.py` -> `permissions.py` (for the `can_use_tool` callback)

No circular imports.

## `canUseTool` Callback

Defined in `permissions.py`. Replaces `_deny_unlisted_tools` in agent.py:

```python
async def handle_tool_permission(
    tool_name: str,
    input_data: dict[str, Any],
    context: ToolPermissionContext,
) -> PermissionResult:
    if in_bg_fork():
        return PermissionResultDeny(message=f"{tool_name} is not allowed")
    return await request_approval(tool_name, input_data)
```

### Contextvar propagation

Works via task-group context inheritance, NOT same-task execution:
1. `run_agent_background()` sets `_in_fork_var=True` on current task context
2. `create_forked_client()` -> `connect()` spawns `_read_messages` task, inheriting context
3. `_read_messages` spawns `_handle_control_request` task, inheriting context
4. `can_use_tool` callback sees `_in_fork_var=True`

**Critical ordering**: `set_in_fork(True)` MUST precede `create_forked_client()` in `run_agent_background`. Add a comment to enforce this.

## `/permissions` Slash Command

New slash command in bot.py with mode choices: default, acceptEdits, bypassPermissions.

(`plan` mode omitted -- needs runtime verification with `set_permission_mode('plan')` before offering.)

Calls `agent.set_permission_mode(mode)`:
- **Interactive fork**: `_fork_client.set_permission_mode(mode)` only -- fork-scoped, dies with fork
- **Main session**: `_client.set_permission_mode(mode)` + update `self.options` via `replace()`

Note: this differs from `/model` which updates both clients. The divergence is intentional -- permission mode is fork-scoped, model is shared.

## Bot.py Integration

### Reaction handler

```python
@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:  # Skip bot's own programmatic reactions
        return
    permissions.resolve_approval(payload.message_id, str(payload.emoji))
```

`resolve_approval` silently ignores unknown message IDs and already-resolved Futures.

### Channel sync

`permissions.set_channel(channel)` called alongside `agent_tools.set_channel(channel)` in `_dispatch()`.

### `/clear` integration

`permissions.reset()` called in `agent.clear()`.

### Interrupt integration

`permissions.cancel_pending()` called in `agent.interrupt()` -- prevents dangling Futures when user sends new message mid-approval.

### Fork exit

`permissions.cancel_pending()` called in `agent.exit_interactive_fork()`.

## `_session_allowed` Scope

Shared across main session and interactive forks. If you unlock-allow a tool in a fork, it stays allowed when you return to main (even if the fork is discarded). Reset only on `/clear`. No `updated_permissions` sent to CLI -- the in-process set is the sole source of truth.

## Channel Reference

Only needs the global `_channel` (not the contextvar). Background forks never reach the approval flow.
