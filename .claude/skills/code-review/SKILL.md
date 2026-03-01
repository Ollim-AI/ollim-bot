---
name: code-review
description: Use after implementing features, before committing substantial changes, or when asked to review code. Two-stage review — project compliance then code quality — with confidence-based filtering.
argument-hint: [scope — e.g., "unstaged", "last commit", "agent.py"]
---

# Code Review

Two-stage review: first check project-specific rules, then general code quality. Only report issues with confidence >= 80 — quality over quantity.

## How to Use

| Invocation | What Claude does |
|------------|-----------------|
| `/code-review` | Review unstaged changes (`git diff`). |
| `/code-review [scope]` | Review specified scope (e.g., "last 3 commits", "agent.py", "staged"). |
| `/code-review audit [path]` | Full audit of a file or module against all checklists. |

## Stage 1: Project Compliance

Check changes against the project's own rules in CLAUDE.md. Violations here are bugs or tech debt by definition.

### Hard Invariants (CLAUDE.md — violation = runtime bugs)

Check every applicable item:
- **Channel-sync**: does any new `stream_chat` entry point call BOTH `agent_tools.set_channel` AND `permissions.set_channel`?
- **No circular imports**: does the change introduce a new import cycle?
- **Atomic file writes**: do new file writes use `tempfile.mkstemp(dir=target.parent)` + `os.replace`?
- **Client teardown**: does new teardown code follow the null-first protocol?

### Code Health Rules (CLAUDE.md — violation = tech debt)

- **No utils/helpers/common files** — every function in a domain module
- **No catch-all directories** — name for what it does, not what it is
- **Modified files under ~400 lines** — check with `wc -l`, don't guess
- **No duplicate logic introduced** — if 3+ modules now implement the same pattern, extract
- **Correct logging** — `logging.getLogger(__name__)` for library code, `print()` only in CLI commands

### Async Correctness (when concurrent code is touched)

Load `/async-principles` and check:
- Contextvars set before fork creation, reset in `finally`
- Lock held for conversation turns, not for teardowns
- Synchronization primitive matches the pattern (skip vs wait vs fail)
- No `await` added inside previously-synchronous critical section without a lock

### UX Rules (when user-facing code is touched)

Load `/ux-principles` and check:
- New proactive notifications go through ping budget
- System messages: lowercase, one-line, minimal
- No mention of capabilities the bot doesn't have
- Background messages have provenance tags

## Stage 2: Code Quality

Load `/python-principles` and `/design-principles` and check:
- Type safety (explicit types on public functions, no `Any` without justification)
- Error handling (fail fast, no speculative fallbacks, documented failure modes)
- Naming (intent-revealing, consistent with codebase conventions)
- Structure (single responsibility, single level of abstraction)
- No premature abstractions, no gold plating, no scope creep

## Output Format

For each issue (confidence >= 80 only):

```
**[Critical|Important|Minor]** (confidence: N%) — file:line
Description of what's wrong.
Why it matters: [project rule reference or explanation].
Fix: [concrete suggestion].
```

Group by severity. If no issues reach 80% confidence, confirm the code meets standards with a brief summary of what was checked.

## When to Dispatch a Review Agent

For large changes (5+ files, new module, cross-cutting), dispatch a separate review agent with:
- The git diff scope (e.g., `git diff HEAD~3..HEAD`)
- This skill's Stage 1 checklist as explicit requirements
- Instructions to load `/python-principles` and `/design-principles` for Stage 2

A fresh-context review catches things you miss when you wrote the code yourself.

## When to Ask for Clarification

**Ask when:**
- A pattern appears intentional but violates a rule — check if there's a documented reason
- The code's purpose is unclear and you can't assess correctness without understanding intent
- A fix would change behavior and you're unsure if that's desired

**Don't ask when:**
- The violation is clear-cut against a documented rule
- The fix is mechanical and doesn't change behavior
- The issue is below 80% confidence (don't report it at all)
