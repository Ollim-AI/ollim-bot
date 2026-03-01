---
name: systematic-debugging
description: Use when encountering any bug, test failure, or unexpected behavior — before proposing fixes. For runtime investigation of what the bot actually did, use debug-bot-history instead.
argument-hint: [description of the issue]
---

# Systematic Debugging

Find the root cause before attempting fixes. Random fixes waste time and create new bugs.

**Iron law: no fixes without root cause investigation first.** If you haven't completed Phase 1, you cannot propose fixes.

## How to Use

| Invocation | What Claude does |
|------------|-----------------|
| `/systematic-debugging [description]` | Start the debugging workflow for the described issue. |
| `/systematic-debugging` (no args) | Load for reference while debugging. |

**Distinguish from `/debug-bot-history`**: This skill is for code-level debugging — bugs in source, test failures, unexpected behavior in the code itself. `/debug-bot-history` is for runtime investigation — what did the bot actually do at a specific time, using session transcripts and runtime data.

## The Four Phases

Complete each phase before proceeding to the next.

### Phase 1: Investigate

**Before attempting ANY fix:**

1. **Read error messages carefully** — don't skip past errors or warnings. Read stack traces completely. Note line numbers, file paths, error codes. They often contain the exact solution.

2. **Reproduce consistently** — can you trigger it reliably? What are the exact steps? If not reproducible, gather more data — don't guess.

3. **Check recent changes** — what changed that could cause this? `git diff`, recent commits, dependency updates, config changes.

4. **Trace data flow** — where does the bad value originate? Trace backward through the call chain to the source. Fix at source, not at symptom.

5. **For async/concurrent bugs** — load `/async-principles` and identify:
   - Which execution context: main session (under lock), interactive fork (under lock), bg fork (no lock, contextvar-scoped)?
   - Is there an `await` in the critical section? No await = no race in asyncio.
   - Are contextvars set before fork creation?
   - Is cleanup in `finally`?

6. **For multi-component bugs** — add diagnostic instrumentation at component boundaries before fixing. Log what enters and exits each layer. Run once to see WHERE it breaks. Then investigate that specific component.

### Phase 2: Analyze Patterns

1. **Find working examples** — locate similar working code in the codebase. What works that's similar to what's broken?

2. **Compare against references** — if implementing a pattern, read the reference implementation completely. Don't skim.

3. **Identify differences** — list every difference between working and broken, however small. Don't assume "that can't matter."

4. **Map dependencies** — what other components, settings, config, environment does this need? What assumptions does it make?

### Phase 3: Hypothesize and Test

1. **Form one clear hypothesis** — state it explicitly: "I think X is the root cause because Y." Be specific, not vague.

2. **Test minimally** — make the smallest possible change to test the hypothesis. One variable at a time. Don't fix multiple things at once.

3. **Evaluate** — did it work? Yes: proceed to Phase 4. No: form a NEW hypothesis. Don't add more fixes on top.

4. **When you don't know** — say "I don't understand X." Don't pretend to know. Research more or ask for help.

### Phase 4: Fix

1. **Write a failing test** that reproduces the bug. Simplest possible reproduction.

2. **Implement a single fix** addressing the root cause. One change at a time. No "while I'm here" improvements.

3. **Verify** — test passes now? No other tests broken? Issue actually resolved?

4. **If 3+ fix attempts have failed: STOP.** Question the architecture with the user. Each fix revealing a new problem in a different place is a pattern indicating an architectural issue, not a series of independent bugs. Don't attempt fix #4 without discussing fundamentals.

## Red Flags — Stop and Return to Phase 1

If you catch yourself thinking any of these, you're rationalizing. STOP.

| Rationalization | Reality |
|----------------|---------|
| "Quick fix for now, investigate later" | First fix sets the pattern. Do it right from the start. |
| "Just try changing X and see if it works" | That's guessing, not debugging. Trace the data flow. |
| "I don't fully understand but this might work" | Partial understanding guarantees partial fixes. |
| "It's probably X, let me fix that" | "Probably" means you haven't verified. Verify first. |
| "Add multiple changes, run tests" | Can't isolate what worked. Causes new bugs. |
| "Issue is simple, don't need the process" | Simple bugs have root causes too. Process is fast for simple bugs. |
| "Emergency, no time for process" | Systematic debugging is FASTER than guess-and-check thrashing. |
| "I see the problem, let me fix it" | Seeing symptoms is not understanding root cause. |
| "One more fix attempt" (after 2+ failures) | 3+ failures = architectural problem. Question the pattern, don't fix again. |
| "Skip the test, I'll manually verify" | Untested fixes don't stick. Test first proves it. |
| "Pattern says X but I'll adapt it differently" | Partial understanding of patterns guarantees bugs. Read completely. |
| "Here are the main problems: [lists fixes]" | Proposing solutions before investigation is guessing. |

## When to Ask for Clarification

**Ask when:**
- You can't reproduce the issue and need more context about when/how it occurs
- The root cause is in an area you don't fully understand
- 3+ fix attempts have failed (question architecture together)
- The fix involves tradeoffs the user should weigh

**Don't ask when:**
- The error message points directly to the problem
- You can reproduce and trace the issue to its source
- The fix is straightforward and doesn't change behavior
