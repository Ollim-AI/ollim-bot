# Session ID History (JSONL)

## Problem

The bot stores a single session ID in `~/.ollim-bot/sessions.json` as a plain string.
Previous session IDs are permanently lost when:

- `/clear` deletes the file
- `swap_client()` overwrites it (fork promoted to main)
- SDK auto-compaction assigns a new session ID

The bot has 113 JSONL transcript files, 68 with parent session IDs (forks or compacted
sessions). There is no index connecting them -- reconstructing the session tree requires
opening each file and parsing headers.

Fork session IDs are especially ephemeral: bg fork IDs exist only in `run_on_client()`'s
return value, interactive fork IDs live in `_fork_session_id` in memory. Both are lost on
process restart.

## Solution

Append-only JSONL event log at `~/.ollim-bot/session_history.jsonl`. Each entry records
a session birth or death. The existing `sessions.json` plain-string file is unchanged
(fast current-session reads on the hot path).

## Data Model

```python
from dataclasses import dataclass
from typing import Literal

SessionEventType = Literal[
    "created",            # new main session (no prior session ID existed)
    "compacted",          # SDK auto-compaction assigned a new main session ID
    "swapped",            # interactive fork promoted to main via save_context
    "cleared",            # /clear destroyed the session
    "interactive_fork",   # interactive fork branched from main
    "bg_fork",            # bg fork branched from main (logged after completion)
]

@dataclass(frozen=True)
class SessionEvent:
    session_id: str
    event: SessionEventType
    timestamp: str                         # ISO 8601
    parent_session_id: str | None = None   # what this forked/compacted from
```

### Example log

```jsonl
{"session_id": "04f89a40", "event": "created", "timestamp": "2026-02-17T03:38:00-08:00", "parent_session_id": null}
{"session_id": "e68c9109", "event": "compacted", "timestamp": "2026-02-17T18:46:00-08:00", "parent_session_id": "04f89a40"}
{"session_id": "d5ff8c62", "event": "bg_fork", "timestamp": "2026-02-18T09:00:00-08:00", "parent_session_id": "e68c9109"}
{"session_id": "b78a11b9", "event": "interactive_fork", "timestamp": "2026-02-18T10:05:00-08:00", "parent_session_id": "e68c9109"}
{"session_id": "3906f8d0", "event": "compacted", "timestamp": "2026-02-19T12:00:00-08:00", "parent_session_id": "e68c9109"}
{"session_id": "e68c9109", "event": "cleared", "timestamp": "2026-02-20T11:00:00-08:00", "parent_session_id": null}
```

## Integration Points

### SDK constraint

The SDK does not expose session IDs until a query is processed. From the docs:

> `StreamEvent.session_id` -- available on every StreamEvent (requires
> `include_partial_messages=True`, which the bot already uses).
>
> `ResultMessage.session_id` -- available at end of turn.

There is no `client.session_id` property. Session IDs are captured from messages only.

### Event triggers

| Event | Where | session_id | parent_session_id |
|---|---|---|---|
| `created` | `save_session_id()` when no prior ID | new ID | None |
| `compacted` | `save_session_id()` when new ID != current | new ID | old ID |
| `swapped` | `swap_client()` | new main ID | old main ID |
| `cleared` | `clear()` | current ID | None |
| `interactive_fork` | `stream_chat()` first StreamEvent for fork client | fork ID | main ID |
| `bg_fork` | `run_agent_background()` after `run_on_client()` returns | fork ID | main ID |

### Detection logic

**`created` vs `compacted`:** `save_session_id()` reads the current file before writing.
If missing/empty, log `created`. If the stored ID differs from the new ID, log `compacted`.
If same ID, no event (normal per-turn save). A `_swap_in_progress` flag prevents
`save_session_id()` from logging `compacted` when `swap_client()` is the caller.

**`interactive_fork`:** `stream_chat()` checks if client is `_fork_client` and
`_fork_session_id is None`. On the first StreamEvent, captures `session_id` and logs
the event. This also sets `_fork_session_id` earlier than the current code (StreamEvent
vs ResultMessage).

**`bg_fork`:** `run_on_client()` already returns the fork's session ID from ResultMessage.
`run_agent_background()` logs after the call completes.

## Why no fork_end events

Fork start alone captures the fork's session ID and its parent -- sufficient for tree
reconstruction. The transcript files (accessible via `claude-history transcript <id>`)
provide all detail about what the fork did. Duration and completion status are computable
from transcript timestamps. Logging fork_end would be analytics, not session history.

## Files changed

- `sessions.py` -- add `SessionEvent` dataclass, `SessionEventType`, `log_session_event()`,
  detection logic in `save_session_id()`, `_swap_in_progress` flag
- `agent.py` -- call `log_session_event` from `swap_client()`, `clear()`; pass fork
  session ID from `stream_chat()` first StreamEvent
- `forks.py` -- call `log_session_event` from `run_agent_background()` after `run_on_client()`

Uses `storage.append_jsonl()` for writes (includes git auto-commit).
