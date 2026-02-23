# Background Fork Timeouts

## Problem

`run_agent_background()` awaits SDK calls indefinitely. A hung bg fork holds
resources forever with no cancellation.

## Solution

Wrap the client lifecycle in `asyncio.timeout(BG_FORK_TIMEOUT)` (30 minutes).
On timeout, the existing `finally: client.disconnect()` cleans up, and the
existing `except` block sends a DM alert.

## Scope

Only `run_agent_background()` in `forks.py`. Out of scope: `send_agent_dm()`
(foreground, user can interrupt), Google API calls, storage subprocess, client
connect.

## Design

- Module constant `BG_FORK_TIMEOUT = 1800` at top of `forks.py`.
- `asyncio.timeout(BG_FORK_TIMEOUT)` wraps the inner try block (client create
  through run_on_client).
- `TimeoutError` caught alongside `Exception` — notification message says
  "timed out" (distinct from "failed") so the user knows it wasn't a crash.
- Existing `finally: client.disconnect()` handles cleanup.
- Existing `_notify_fork_failure` pattern reused for the DM alert (with a
  timeout-specific variant or message).

## What changes

- `forks.py`: ~5 lines added. One constant, one context manager, one except
  clause with a distinct log + notification message.

## Decisions

- **30 minutes**: generous for normal use (most bg forks finish in 1-3 min),
  catches truly hung forks.
- **Discord alert on timeout**: user wants visibility into failures.
- **No two-layer timeout**: connect hangs are very rare and the 30min outer
  timeout catches them anyway.
