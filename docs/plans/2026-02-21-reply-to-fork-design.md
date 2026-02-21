# Reply-to-Fork Design

Replying to a bg fork message starts an interactive fork that resumes from the bg fork's session, with pending updates prepended for main-session context.

## Message Tracking (`sessions.py`)

New file: `~/.ollim-bot/fork_messages.json` — maps Discord message IDs to fork session IDs.

```json
[
  {
    "message_id": 123456789,
    "fork_session_id": "abc-123...",
    "parent_session_id": "xyz-456...",
    "timestamp": "2026-02-20T10:00:00"
  }
]
```

Records pruned after 7 days on load (same pattern as `inquiries.py`).

### Collector API

Contextvar-based collector so streamer/MCP tools stay decoupled from fork logic:

- `start_message_collector()` — initializes contextvar list
- `track_message(message_id: int)` — appends to collector if active, no-op otherwise
- `flush_message_collector(fork_session_id, parent_session_id)` — writes collected IDs to file, clears collector
- `lookup_fork_session(message_id: int) -> str | None` — returns fork session ID or None

## Message Collection (callers)

- `forks.py:run_agent_background()` calls `start_message_collector()` before and `flush_message_collector()` after `run_on_client()`
- `streamer.py:stream_to_channel()` calls `track_message(msg.id)` after creating/editing messages
- MCP tools (`ping_user`, `discord_embed`) call `track_message(msg.id)` after sending

## Reply Detection (`bot.py:_dispatch`)

On every incoming message:

1. Check `message.reference` and resolve the referenced message
2. Call `lookup_fork_session(referenced_message_id)`
3. If fork session found and no interactive fork active: start interactive fork from that bg fork session
4. If no fork session found but replying to a message: prepend quoted replied-to content in prompt text

## Agent Changes (`agent.py`)

- `enter_interactive_fork(resume_session_id=None)` — optional override session ID
- `create_forked_client(session_id=None)` — accepts explicit session ID instead of always loading main

## Unchanged

Fork behavior (exit strategies, idle timeout, buttons, pending updates prepend, channel sync) stays the same. Session history logs the new interactive fork with `parent_session_id` = bg fork session ID.
