---
name: async-principles
description: Use when writing, reviewing, or auditing concurrent code in ollim-bot — asyncio locks, ContextVar isolation, fork state, file I/O atomicity, client lifecycle, or synchronization primitive choices.
---

# Async & Concurrency Principles

Principles for writing correct concurrent code in ollim-bot. Derived from the codebase's dual-mode concurrency model: a single `asyncio.Lock` serializes the main session, while background forks run lock-free using `ContextVar` isolation.

## Purpose

Every principle here exists to do one or more of these:

1. **Prevent silent corruption** — races, stale state, and lost writes are invisible until they bite
2. **Right-size synchronization** — use the lightest primitive that maintains the invariant
3. **Make the concurrency model legible** — a reader should understand *why* code is safe, not just observe that it runs
4. **Guide the asyncio mental model** — prevent reasoning errors that import multithreaded assumptions into cooperative concurrency

**Scoring rubric**: After writing or reviewing concurrent code, evaluate against [scoring-rubric.md](.claude/skills/async-principles/scoring-rubric.md). Each item is a yes/no check tied to a principle below.

## How to Use

| Invocation | What Claude does |
|------------|-----------------|
| `/async-principles` (no args) | Load for reference while writing or reviewing concurrent code. |
| `/async-principles audit [path]` | Scan for violations: missing locks where needed, unnecessary locks, wrong primitives, teardown bugs. Score against rubric. |
| `/async-principles review` | Review a proposed change for concurrency correctness. Check which execution contexts (main, interactive fork, bg fork) the new code runs in, and verify the right state access pattern is used. |

### Before applying

1. **Identify the execution context** — is this code reachable from the main session (under `agent.lock()`), from an interactive fork (also under lock), or from a background fork (no lock, contextvar-scoped)?
2. **Check existing patterns** — the codebase already has conventions for each concurrency concern. Match them unless there's a specific reason to diverge.
3. **Read the actual code path** — don't guess which lock is held or which contextvar is set. Trace the call chain from the entry point.

### Priority when principles conflict

1. **Correctness over simplicity** — a correct program with a defensive lock beats an elegant program with a race
2. **Match existing patterns** — consistency prevents the next developer from reasoning about two conventions
3. **Right primitive over no primitive** — when in doubt about whether synchronization is needed, add it with a comment explaining the invariant

## Understanding the Execution Model

**No await, no race.** *(hard rule)*
In asyncio's cooperative model, only `await` yields control to other tasks. Synchronous code between two `await` points runs atomically — no other coroutine can interleave.
Before adding synchronization to a code path, find the `await` in the critical section. If there is none, no lock is needed and no race is possible.

This is the foundational rule. Synchronous operations like load-check-save, check-done-then-set-result, and read-and-clear-a-global are all safe without locks — no `await` means no interleaving. It also explains why an audit applying multithreaded interleaving diagrams to asyncio produces false positives — those interleavings require preemption, which asyncio doesn't have.

The corollary: when you DO add an `await` inside a previously-synchronous critical section (e.g., switching from `Path.read_text()` to `aiofiles`), you've introduced a real race and need real synchronization.

**A lock that documents an invariant is not wasted.** *(judgment call)*
Some locks in the codebase wrap synchronous read-modify-write sections. By the no-await rule, they're technically redundant today. But they document "this read-modify-write must be atomic" — if someone later adds an `await` inside, the lock is already there. This is the exception to "no await, no race" — the lock is not needed for correctness today, but earns its keep as documentation.
Keep defensive locks when they protect a genuine invariant. But add a comment explaining what they guard, so a reader doesn't remove them thinking they're unnecessary, and doesn't copy the pattern to places where no invariant exists.

## Managing Shared State

**Teardown without the lock, interaction with it.** *(hard rule)*
Operations that *converse* with the SDK client (`stream_chat`, `slash`, button-triggered agent calls) hold `agent.lock()`. Operations that *destroy or reconfigure* the client (`/clear`, `/model`, `/thinking`, `/interrupt`) do not.

Teardowns follow a specific protocol that makes them safe without the lock:
1. Null the reference first (`self._client = None`) — synchronous, visible immediately
2. Interrupt the old client — may fail if already gone, suppressed
3. Disconnect — may fail from a different task, suppressed

Any in-flight stream sees `client is not self._client` at its next `await` and stops saving state. This avoids deadlock: if `/clear` held the lock, the user couldn't clear a stuck stream.

New operations must choose a tier. The test: does this operation send a *conversation turn* through the client and stream the response (`stream_chat`, `slash`, `query` + `receive_response`)? If yes, it needs the lock. Does it tear down, reconfigure, or send a control command (model switch, permission change)? No lock — teardowns use the null-first protocol, and control commands are fire-and-forget settings the SDK handles safely mid-stream. Does it only read module-level state without touching the client (e.g., checking fork status, reading budget)? No lock needed — synchronous reads are atomic by the no-await rule.

**Every interaction path sets channel in both modules.** *(hard rule)*
Every path into `stream_chat` must call both `agent_tools.set_channel` and `permissions.set_channel` before streaming. Missing either sends output or approval prompts to a stale channel — a silent runtime bug. This is documented as a hard invariant in CLAUDE.md; check it when adding any new entry point.

**ContextVar before fork, global under lock.** *(hard rule)*
Background forks use `ContextVar` for per-task isolation (channel, chain context, output tracking, message collection, in-fork flag). The main session uses module globals protected by `agent.lock()`. Where both regimes need access to the same logical state, the dual pattern applies: a module global for the main session and a ContextVar for bg forks, with the reader checking the contextvar first, falling back to the module global.

Set every contextvar *before* creating the forked client. The SDK spawns internal tasks that inherit the caller's context. If you set the contextvar after connecting, SDK callbacks won't see the fork's state. The background fork entry point in `forks.py` has a `CRITICAL` comment explaining this ordering — it is not optional.

Clean up in `finally`: contextvars must be reset even if the stream errors. Leaked state corrupts the next task reusing that event loop slot. Use nested try/finally when cleanup has two phases (outer: reset contextvars/flags, inner: disconnect client) — this ensures state is clean even if resource cleanup itself fails.

## Choosing Synchronization Primitives

**Choose the right rejection: skip, wait, or fail.** *(strong default)*
Three rejection strategies exist. Each suits a different situation:

| Strategy | Primitive | When to use | Example |
|----------|-----------|-------------|---------|
| **Skip** | Boolean flag + early return | Periodic checks where a stale run is worthless | Scheduler reentrancy guard |
| **Wait** | `asyncio.Lock` | Shared mutable resource where every write matters | Pending-updates file I/O |
| **Fail** | Return error / raise | Caller must know the operation didn't happen | Daily budget enforcement |

A lock where you need a skip-guard makes periodic tasks queue uselessly. A skip-flag where you need a lock loses writes. Matching the rejection strategy to the situation is as important as choosing whether to synchronize at all.

Boolean skip-guards are safe in asyncio because the check-and-set is synchronous (no `await` between them). They implement "skip if busy" semantics — distinct from a lock's "wait your turn."

**Bridge execution contexts with the narrowest primitive.** *(strong default)*
When separate execution paths must communicate (event handlers, scheduled tasks, streaming loops), pick the primitive that matches the communication pattern:

| Pattern | Primitive | Example |
|---------|-----------|---------|
| One-shot value from handler A to handler B | `asyncio.Future` + `wait_for` | Tool approval: send prompt → store Future → reaction handler resolves |
| Completion signal to a background task | `asyncio.Event` | Streamer: signal tells editor task to flush and exit |
| Deferred state transition after stream | Module-level flag, read post-stream | Fork transitions: MCP tool sets flag, post-stream check reads it |
| Batch cleanup of pending operations | Dict of Futures + cancel helper | Approval cleanup: interrupt cancels all outstanding Futures |

Avoid the wrong primitive: a `Queue` for a one-shot value adds buffering complexity that hides the 1:1 correlation. A `Lock` for a completion signal blocks instead of signaling. A `Future` where you need a reusable signal requires recreation after each use. Use the primitive whose semantics match.

## Resource Lifecycle

**Atomic writes: tempfile in the same directory.** *(hard rule)*
All file writes use `tempfile.mkstemp(dir=target.parent)` then `os.write` then `os.close` then `os.replace`. The same-directory constraint ensures `os.replace` maps to an atomic `rename(2)` on the same filesystem. If the temp file were in `/tmp` and the target in `~/.ollim-bot/`, they could be on different filesystems, and the rename would not be atomic.

Wrap the file descriptor in try/finally: if `os.write` fails (disk full, encoding error), `os.close(fd)` must still run to avoid leaking a file descriptor. Every `mkstemp` call creates a real fd that the OS tracks — an unclosed fd is a resource leak, not just untidy code.

**Null the reference, then tear down, then suppress.** *(strong default)*
When destroying an async resource (SDK client, subprocess connection):

1. **Null the reference** (`self._client = None`) — synchronous, makes the resource instantly invisible to concurrent code
2. **Interrupt** — send stop signal; suppress `CLIConnectionError` (subprocess may have already exited)
3. **Disconnect** — clean up transport; suppress `RuntimeError` (anyio cancel scope mismatch when caller task differs from connect task)

This ordering matters. If you interrupt before nulling, a concurrent identity check (`client is not self._client`) still sees the old reference and may try to save state from a dying stream. If you disconnect before interrupting, the interrupt has no target.

For background forks with contextvar state, use nested try/finally: the outer block resets contextvars (always succeeds), the inner block disconnects the client (may raise). This ensures the fork's state is clean even if the SDK subprocess crashes during disconnect.

## When to Ask for Clarification

**Ask when:**
- The execution context (main, interactive fork, bg fork) is ambiguous for the code path
- A new entry point into `stream_chat` is being added — verify channel-sync and lock discipline
- Two principles suggest different primitives for the same situation
- A defensive lock has no comment explaining what invariant it protects

**Don't ask when:**
- The code path is clearly under `agent.lock()` (main session / interactive fork)
- The code path is clearly in a bg fork (contextvar setup visible in caller)
- The synchronization pattern matches an existing pattern in the codebase
