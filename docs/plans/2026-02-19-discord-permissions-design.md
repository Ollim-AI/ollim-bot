# Discord Permission Management Design

Route Claude Agent SDK permission controls through the Discord interface.

## Goals

1. **Dynamic permission modes** via `/permissions` slash command (default, acceptEdits, bypassPermissions, plan)
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
- `_channel: discord.abc.Messageable | None` -- set before each `stream_chat()`, same pattern as `agent_tools._channel`
- `_session_allowed: set[str]` -- tool names added via unlock reaction, reset on `/clear`

### `request_approval(tool_name, input_data) -> PermissionResult`

1. Check `_session_allowed` -- if tool matches, return `PermissionResultAllow()` immediately
2. Format message: `` `Bash(rm old-data.json)` -- react to approve `` with tool label from `_format_tool_label`
3. Send message to `_channel`, add three reactions programmatically
4. Create `asyncio.Future`, store in `_pending[msg.id]`
5. `await asyncio.wait_for(future, timeout=60)` -- auto-deny on timeout
6. Approve reaction: return `PermissionResultAllow()`
7. Deny reaction: return `PermissionResultDeny(message="denied via Discord")`
8. Unlock reaction: add tool name to `_session_allowed`, return `PermissionResultAllow()`
9. Edit original message to show the decision

### `resolve_approval(message_id, emoji)`

Called from `on_raw_reaction_add` in bot.py. Sets the Future result. No lock needed.

### `reset()`

Clears `_session_allowed` and cancels any pending futures. Called on `/clear`.

### `cancel_pending()`

Cancels all pending futures (returns deny). Called on fork exit.

## `canUseTool` Callback

Replaces `_deny_unlisted_tools` in agent.py:

```python
async def _handle_tool_permission(
    tool_name: str,
    input_data: dict,
    context: ToolPermissionContext,
) -> PermissionResult:
    if in_bg_fork():
        return PermissionResultDeny(message=f"{tool_name} is not allowed")
    return await permissions.request_approval(tool_name, input_data)
```

Contextvar propagation works because `run_agent_background()` -> `run_on_client()` -> SDK calls `canUseTool` in the same asyncio task.

## `/permissions` Slash Command

New slash command in bot.py with mode choices (default, acceptEdits, bypassPermissions, plan).

Calls `agent.set_permission_mode(mode)`:
- **Interactive fork**: `_fork_client.set_permission_mode(mode)` -- fork-scoped, dies with fork
- **Main session**: `_client.set_permission_mode(mode)` + update `self.options` via `replace()`

## Bot.py Integration

### Reaction handler

```python
@bot.event
async def on_raw_reaction_add(payload):
    # Only handle reactions on pending approval messages
    # Only from the bot owner (not from the bot adding reactions)
    permissions.resolve_approval(payload.message_id, str(payload.emoji))
```

### Channel sync

`permissions.set_channel(channel)` called alongside `agent_tools.set_channel(channel)` in `_dispatch()`.

### `/clear` integration

`permissions.reset()` called in `agent.clear()`.

### Fork exit

`permissions.cancel_pending()` called in `agent.exit_interactive_fork()`.

## `_session_allowed` Scope

Shared across main session and interactive forks. If you unlock-allow a tool in a fork, it stays allowed when you return to main. Reset only on `/clear`.

## Channel Reference

Only needs the global `_channel` (not the contextvar). Background forks never reach the approval flow.
