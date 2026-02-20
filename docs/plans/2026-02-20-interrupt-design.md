# Interrupt Command & Fork Button Interrupt

## Problem

1. No way to stop the agent mid-stream without sending a new message (which triggers a new response).
2. Clicking an embed button during an active interactive fork blocks until the stream finishes, instead of interrupting and acting immediately.

## Design

### `/interrupt` slash command

Silent interrupt of the current agent stream. Mirrors the existing interrupt-on-new-message pattern without sending a follow-up message.

- If `agent.lock()` is held: call `agent.interrupt()` (cancels pending approvals + interrupts SDK client)
- If lock is NOT held: no-op
- Always: defer the interaction response and delete it (silent, no visible message)
- No lock acquisition needed -- interrupt is fire-and-forget

### Agent-routed button clicks interrupt interactive fork

When `_handle_agent_inquiry` fires during an active interactive fork and the agent is streaming:

- Before acquiring the lock, check if `in_interactive_fork()` and `agent.lock().locked()`
- If both true: call `agent.interrupt()` first (same pattern as `on_message`)
- Then acquire lock and proceed with the inquiry as normal

Scope: only `_handle_agent_inquiry` (`agent:<uuid>` buttons). Direct actions (`task_done`, `event_del`, `dismiss`) and fork buttons (`fork_save`, `fork_report`, `fork_exit`) are unchanged.

## Rejected alternatives

- **Cancel + re-route into fork context**: Complex, unclear semantics about which session receives the inquiry.
- **Queue inquiry for after stream**: Adds latency, doesn't match user expectation of immediate action.
