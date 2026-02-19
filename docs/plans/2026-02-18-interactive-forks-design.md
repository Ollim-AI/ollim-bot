# Interactive Forks

Branched conversations from the main session for research, tangents, or focused work. Unlike background forks (fire-and-forget), interactive forks stream responses and support multi-turn chat until explicitly exited.

## Decisions

- Same DM channel with embed banners (no threads)
- `exit_fork` = clean discard; `save_context` = promote; `report_updates` = summary
- Agent enters forks silently (embed indicator, no confirmation)
- Idle timeout resets on any activity (user or agent)
- Multiple forks allowed but not nested (always branch from main). Background forks run in parallel.
- `/fork [topic]` optional topic argument
- `enter_fork(topic?, idle_timeout=10)` configurable timeout

## Architecture Refactor

Adding interactive forks on top of the current module structure would worsen existing responsibility tangles. This feature includes a cleanup.

### Current problems

- `discord_tools.py` mixes MCP tool definitions with state management (channel ref, fork flags, pending updates I/O)
- `streamer.py` mixes Discord streaming with agent orchestration (`dispatch_agent_response`, `run_agent_background`)
- Adding fork lifecycle to `bot.py` without cleanup makes it worse

### New module responsibilities

| Module | Responsibility |
|--------|---------------|
| `agent.py` | SDK client lifecycle, message routing (which client to use), `stream_chat`/`chat`/`slash` |
| `forks.py` (new) | All fork state + lifecycle: interactive (enter/exit/promote/timer) and background (run_agent_background). Pending updates I/O. |
| `agent_tools.py` (rename from `discord_tools.py`) | Pure MCP tool definitions. Delegates state to `forks.py`. Holds `_channel`/`set_channel`. |
| `streamer.py` | Pure Discord streaming: `stream_to_channel` only |
| `bot.py` | Discord events, slash commands, post-stream fork transitions. Absorbs `dispatch_agent_response`/`send_agent_dm` as local helpers. |

### Migration

From `discord_tools.py` to `forks.py`:
- `_in_fork`, `_fork_saved`, `set_in_fork`, `pop_fork_saved`
- `_UPDATES_FILE`, `_append_update`, `peek_pending_updates`, `pop_pending_updates`, `clear_pending_updates`
- New interactive fork state (see below)

From `discord_tools.py` to `agent_tools.py` (rename):
- `_channel`, `set_channel`
- All `@tool` definitions
- `discord_server` renamed to `agent_server`

From `streamer.py` to `forks.py`:
- `run_agent_background`

From `streamer.py` to `bot.py`:
- `dispatch_agent_response` (local helper, not exported)
- `send_agent_dm` (local helper, not exported)

`views.py` and `forks.py` compose the pieces directly (`set_channel` + `channel.typing()` + `stream_to_channel`) to avoid circular imports with bot.py.

## Fork State Model

### Agent class (agent.py)

```python
_fork_client: ClaudeSDKClient | None = None
_fork_session_id: str | None = None
```

Property: `in_fork -> bool` returns `self._fork_client is not None`.

### Fork module (forks.py)

Module-level state (safe because agent lock serializes all access):

```python
# Interactive fork state
_in_interactive_fork: bool = False
_fork_exit_action: ForkExitAction = ForkExitAction.NONE  # NONE/SAVE/REPORT/EXIT
_enter_fork_requested: bool = False
_enter_fork_topic: str | None = None
_fork_idle_timeout: int = 10              # minutes, configurable per-fork
_fork_last_activity: float = 0.0          # monotonic timestamp
_fork_prompted_at: float | None = None    # set on timeout prompt, cleared on user msg

# Background fork state (unchanged from current discord_tools.py)
_in_fork: bool = False
_fork_saved: bool = False
```

`ForkExitAction` enum: `NONE`, `SAVE`, `REPORT`, `EXIT`.

## MCP Tools

All defined in `agent_tools.py`, delegating state to `forks.py`.

### New tools

`enter_fork(topic?, idle_timeout=10)` -- Agent calls this to autonomously start an interactive fork. Sets `_enter_fork_requested = True`, stores topic and timeout. Returns "Fork will be created after this response." After `stream_chat` completes on main session, bot.py checks the flag, creates fork client, sends embed banner. If topic provided, auto-sends as first fork message.

`exit_fork()` -- Clean discard. Sets `_fork_exit_action = EXIT`. Only works when `_in_interactive_fork` is True.

### Updated tools

`save_context` -- Works in both `_in_fork` (bg fork, sets `_fork_saved`) and `_in_interactive_fork` (sets `_fork_exit_action = SAVE`).

`report_updates(message)` -- Same dual-mode: bg fork appends update, interactive fork sets `_fork_exit_action = REPORT` and appends update.

### allowed_tools additions

```python
"mcp__discord__enter_fork",
"mcp__discord__exit_fork",
```

Note: MCP server name stays `"discord"` in the tool prefix even though the module is renamed to `agent_tools.py`. The server name is set in `create_sdk_mcp_server("discord", ...)` and can be updated to `"agent"` as a separate change if desired.

## Message Routing

### stream_chat fork awareness (agent.py)

```python
if self._fork_client is not None:
    client = self._fork_client
    message = _prepend_context(message, clear=False)  # peek updates, don't pop
else:
    message = _prepend_context(message)  # timestamp + pop updates
    client = await self._get_client()
```

Session ID saving:

```python
if self._fork_client is not None and client is self._fork_client:
    self._fork_session_id = msg.session_id   # in-memory only
elif self._client is client:
    save_session_id(msg.session_id)           # persist to disk
```

### Agent methods for fork lifecycle

`enter_interactive_fork(idle_timeout=10)` -- Creates forked client via `create_forked_client()`, stores in `_fork_client`. Sets interactive fork state in forks.py.

`exit_interactive_fork(action: ForkExitAction)` -- Based on action:
- `SAVE`: promote fork via `swap_client(_fork_client, _fork_session_id)`, clear pending updates
- `REPORT`: already queued by tool; disconnect fork client
- `EXIT`: disconnect fork client silently

All paths clear `_fork_client`, `_fork_session_id`, and interactive fork state.

### Post-stream transition check (bot.py)

After every `stream_chat` call in `on_message`, bot.py calls a check:

```python
# After stream_to_channel completes:
if forks.enter_fork_requested():
    topic, timeout = forks.pop_enter_fork()
    await agent.enter_interactive_fork(idle_timeout=timeout)
    forks.set_interactive_fork(True, idle_timeout=timeout)
    await channel.send(embed=fork_enter_embed(topic))
    if topic:
        await stream_to_channel(channel, agent.stream_chat(topic))
        # recurse: check again after topic response

exit_action = forks.pop_exit_action()
if exit_action is not ForkExitAction.NONE:
    await agent.exit_interactive_fork(exit_action)
    await channel.send(embed=fork_exit_embed(exit_action))
```

## /fork Slash Command

```
/fork [topic]
```

- If already in a fork: ephemeral error "already in a fork"
- Otherwise: defer, acquire lock, create fork, send enter embed
- If topic provided: auto-send to fork and stream response

## Visual Indicators

### Enter fork embed (purple)

```
Forked Session
Topic: <topic or "open session">

[Save Context] [Report] [Exit Fork]
```

### Exit fork embed (green/blue)

```
Fork Ended
Result: context saved / summary reported / discarded
```

### Button actions

New actions in views.py: `fork_save:_`, `fork_report:_`, `fork_exit:_`.

Handlers acquire agent lock, call `agent.exit_interactive_fork(action)`, clear fork state, send confirmation embed.

## Timeout Timer

Registered as an APScheduler `IntervalTrigger(seconds=60)` job when a fork starts. Removed when fork exits.

### Logic

```
every 60s:
  if not in interactive fork: return

  if prompted_at is set and (now - prompted_at) > idle_timeout minutes:
    auto-exit with report_updates
    return

  if (now - last_activity) > idle_timeout minutes and prompted_at is not set:
    acquire lock
    send to fork: "[fork-timeout] idle for {idle_timeout} min. Use save_context,
      report_updates, or exit_fork. Ask Julius if still engaged."
    set prompted_at = now
```

### Activity tracking

- `_fork_last_activity` resets on any message (user or agent)
- `_fork_prompted_at` clears only on user messages (prevents infinite agent self-talk)
- Second timeout after prompt with no user response: auto `report_updates` + exit

## System Prompt Addition

```
## Interactive Forks

You can enter a forked session for research, tangents, or focused work.

| Tool | Effect |
|------|--------|
| `enter_fork(topic?, idle_timeout=10)` | Start an interactive fork |
| `exit_fork` | Discard fork, return to main session |
| `save_context` | Promote fork to main session |
| `report_updates(message)` | Queue summary, discard fork |

Julius can also use `/fork [topic]`.

Rules:
- Forks always branch from the main session (never nested)
- Use for research, complex tool chains, or anything tangential
- After idle_timeout minutes idle, you'll be prompted to exit
- If Julius doesn't respond after another timeout period, auto-exit with report_updates
```

## Files Changed Summary

| File | Change |
|------|--------|
| `forks.py` (new) | All fork state, lifecycle, pending updates I/O, `run_agent_background` |
| `agent_tools.py` (rename) | Pure MCP tool definitions, channel ref, new `enter_fork`/`exit_fork` tools |
| `agent.py` | Fork client fields, `enter_/exit_interactive_fork()`, fork-aware routing |
| `streamer.py` | Slimmed to `stream_to_channel` only |
| `bot.py` | `/fork` command, post-stream transitions, absorbs dispatch helpers |
| `views.py` | `fork_save`/`fork_report`/`fork_exit` button handlers |
| `prompts.py` | Interactive forks section |
| `scheduling/scheduler.py` | Imports from `forks.py`, fork timeout job |
