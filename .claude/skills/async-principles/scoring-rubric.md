# Async Principles — Scoring Rubric

Use this checklist to evaluate concurrent code after writing or reviewing. Each item is a yes/no check tied to a principle from SKILL.md. A "no" answer is a violation worth investigating. Skip items that don't apply to the change scope.

---

## Understanding the Execution Model

| # | Check | Principle |
|---|-------|-----------|
| E1 | Does every lock or synchronization primitive protect a critical section that contains an `await`? If not, is there a comment explaining the invariant it documents? | No await, no race / Documenting invariants |
| E2 | Are there zero interleavings assumed between synchronous statements (no "Thread A / Thread B" reasoning applied to asyncio)? | No await, no race |

## Managing Shared State

| # | Check | Principle |
|---|-------|-----------|
| S1 | Do all new entry points into `stream_chat` or `chat` acquire `agent.lock()`? | Teardown vs interaction |
| S2 | Do all teardown operations (client drop, model switch, thinking toggle) null the reference before interrupting? | Teardown without lock |
| S3 | Do all client operations check identity (`client is self._client`) before saving session state? | Teardown without lock |
| S4 | Are all contextvars set *before* `create_forked_client()` or `create_isolated_client()`? | ContextVar before fork |
| S5 | Are all contextvars reset in a `finally` block, even if the stream errors? | ContextVar before fork |
| S6 | For new module-level mutable state: is it a global (accessed under lock) or a ContextVar (accessed from bg forks)? Is the choice documented? | Global under lock, ContextVar for forks |
| S7 | Does every new `stream_chat` entry point call both `agent_tools.set_channel` AND `permissions.set_channel`? | Channel-sync invariant (from CLAUDE.md) |

## Choosing Synchronization Primitives

| # | Check | Principle |
|---|-------|-----------|
| P1 | For periodic/scheduled tasks: does the guard use skip semantics (boolean flag + early return), not wait semantics (Lock)? | Skip, wait, or fail |
| P2 | For shared mutable files accessed from concurrent bg forks: is there a lock protecting the read-modify-write cycle? | Skip, wait, or fail |
| P3 | For one-shot cross-handler communication: is `asyncio.Future` used (not Queue or Event)? | Bridge with narrowest primitive |
| P4 | For completion signals: is `asyncio.Event` used (not Future or Lock)? | Bridge with narrowest primitive |
| P5 | Are all Futures cleaned up (popped from dicts, cancelled on interrupt/clear)? | Bridge with narrowest primitive |

## Resource Lifecycle

| # | Check | Principle |
|---|-------|-----------|
| R1 | Do all file writes use `tempfile.mkstemp(dir=target.parent)` + `os.replace`? | Atomic writes |
| R2 | Is the file descriptor from `mkstemp` wrapped in try/finally to ensure `os.close(fd)` runs on write failure? | Atomic writes |
| R3 | Does client teardown follow null → interrupt (suppress CLIConnectionError) → disconnect (suppress RuntimeError)? | Null, tear down, suppress |
| R4 | For bg fork cleanup: does the outer `finally` reset contextvars/flags, with client disconnect in an inner `finally`? | Null, tear down, suppress |
