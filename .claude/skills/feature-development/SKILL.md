---
name: feature-development
description: Use when building new features or significant enhancements that touch multiple files or introduce new patterns. Guides systematic development through five phases — understand, explore, clarify, implement, review.
argument-hint: [feature description]
---

# Feature Development

Systematic feature development in five phases. Every feature goes through all five — the depth of each phase scales to the feature's complexity.

## How to Use

| Invocation | What Claude does |
|------------|--------------------|
| `/feature-development [description]` | Start the full workflow for the described feature. |
| `/feature-development` (no args) | Load for reference while developing. |

## Core principle: structured choices over open-ended questions

**Use AskUserQuestion for every user decision.** Structured multi-choice questions are lower-friction than walls of text the user has to read and respond to freeform. The user can always pick "Other" for custom input.

Good question: 2-4 concrete options with tradeoff descriptions, recommended option first.
Bad question: open-ended "how should I handle X?" that forces the user to design the solution.

## Phase 1: Understand

Confirm what needs to be built before exploring code.

1. If the feature description is clear, summarize your understanding in 2-3 sentences
2. Check existing docs and plans for prior discussion of this feature
3. **Confirm** via AskUserQuestion — for clear requests, a single "Does this match what you want?" with proceed/adjust options suffices

If ambiguous, use AskUserQuestion to narrow scope (what problem, what behavior, constraints) before confirming.

## Phase 2: Explore

Understand the relevant codebase deeply before designing.

**Dispatch 2-3 parallel exploration agents**, each targeting a different aspect:

- **Similar features**: "Find features similar to [X] and trace their implementation — entry points, data flow, integration patterns. Return a list of 5-10 key files."
- **Architecture & abstractions**: "Map the architecture and abstractions for [area] — module boundaries, shared state, execution contexts. Return a list of 5-10 key files."
- **Integration points**: "Identify all integration points relevant to [X] — what modules/patterns does this need to connect with? Return a list of 5-10 key files."

After agents return, **read all identified key files** to build deep understanding. Present a summary of findings and patterns discovered.

**During exploration, identify:**
- Which execution contexts the feature touches (main session, interactive fork, bg fork)
- Whether new `stream_chat` entry points are needed (channel-sync invariant — see CLAUDE.md)
- Whether new module-level mutable state is needed (contextvar vs lock decision — load `/async-principles`)
- Whether the feature sends user-visible output (load `/ux-principles`)

## Phase 3: Clarify

Surface design decisions the user should weigh in on — because an unasked question becomes an assumption baked into code that's expensive to change.

**Skip when** exploration reveals a single clear path with no meaningful alternatives. State that you're skipping and why.

**When clarification is needed:**

1. Review exploration findings against the original request
2. Identify genuine decisions: approach alternatives, scope boundaries, edge-case strategies, integration choices
3. **Present via AskUserQuestion** — batch related decisions (up to 4 questions per call):
   - Frame each as a concrete choice, not open-ended
   - Provide 2-4 options with short tradeoff descriptions
   - Lead with your recommended option (add "(Recommended)" to the label)
   - Use multi-select for non-exclusive choices (e.g., "Which edge cases matter?")

**Example — good vs. bad:**
- Bad: "How should I handle errors in this module?"
- Good: "How should webhook validation errors surface?" → "Return 400 with field details (Recommended)" / "Return generic 400, log details server-side" / "Silently drop and log"

**Don't ask when:**
- Existing codebase conventions dictate the approach
- The decision is easily reversible and won't surprise the user
- You'd be asking just to satisfy this phase — forced questions waste more time than they save

## Phase 4: Implement

1. Load `/python-principles` for code quality
2. If the feature involves concurrency: load `/async-principles`
3. If the feature is user-facing: load `/ux-principles`
4. If the feature involves architectural decisions: load `/design-principles`
5. Follow CLAUDE.md code health rules
6. Implement following chosen architecture and codebase conventions

If implementation reveals a design fork not covered in Phase 3 — where both paths are reasonable and codebase conventions don't decide it — use AskUserQuestion before continuing.

## Phase 5: Review

Two-stage review after implementation.

### Stage 1: Spec Compliance

Did I build what was asked? Check independently — don't trust your own memory of what you implemented.

- **Missing requirements**: are there requirements I skipped or missed?
- **Extra work**: did I build things that weren't requested? Over-engineer?
- **Misunderstandings**: did I interpret requirements differently than intended?

### Stage 2: Code Quality

Load `/code-review` and run it against the changes. This checks:
- Project compliance (CLAUDE.md code health rules)
- Code quality (python-principles, design-principles)
- Confidence ≥80 filter (only report issues that truly matter)

For large changes (5+ files), dispatch a fresh-context review agent — it catches things you miss when you wrote the code.
