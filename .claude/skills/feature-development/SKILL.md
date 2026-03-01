---
name: feature-development
description: Use when building new features or significant enhancements that touch multiple files or introduce new patterns. Guides systematic development through five phases — understand, explore, clarify, implement, review.
argument-hint: [feature description]
---

# Feature Development

Systematic feature development in five phases. Every feature goes through all five phases — the discipline IS the value.

## How to Use

| Invocation | What Claude does |
|------------|-----------------|
| `/feature-development [description]` | Start the full workflow for the described feature. |
| `/feature-development` (no args) | Load for reference while developing. |

## Phase 1: Understand

Confirm what needs to be built before exploring code.

1. If the feature description is clear, summarize your understanding and confirm with the user
2. If ambiguous, ask: what problem does this solve? What should it do? Any constraints?
3. Check existing docs and plans for prior discussion of this feature

**Do not proceed to Phase 2 until the user confirms the goal.**

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

**Do not skip.** This is the phase that prevents wasted implementation work.

1. Review the exploration findings against the original feature request
2. Identify all underspecified aspects: edge cases, error handling, integration points, scope boundaries, design preferences
3. **Present all questions to the user in an organized list**
4. **Wait for answers before proceeding to implementation**

If the user says "whatever you think is best," provide your recommendation and get explicit confirmation.

## Phase 4: Implement

**Do not start without user approval on the approach.**

1. Load `/python-principles` for code quality
2. If the feature involves concurrency: load `/async-principles`
3. If the feature is user-facing: load `/ux-principles`
4. If the feature involves architectural decisions: load `/design-principles`
5. Follow CLAUDE.md code health rules — check hard invariants and design rules
6. Implement following chosen architecture and codebase conventions

## Phase 5: Review

Two-stage review after implementation.

### Stage 1: Spec Compliance

Did I build what was asked? Check independently — don't trust your own memory of what you implemented.

- **Missing requirements**: are there requirements I skipped or missed?
- **Extra work**: did I build things that weren't requested? Over-engineer?
- **Misunderstandings**: did I interpret requirements differently than intended?

### Stage 2: Code Quality

Load `/code-review` and run it against the changes. This checks:
- Project compliance (CLAUDE.md hard invariants and code health rules)
- Code quality (python-principles, design-principles)
- Confidence ≥80 filter (only report issues that truly matter)

For large changes (5+ files), dispatch a fresh-context review agent — it catches things you miss when you wrote the code.

## When to Ask for Clarification

**Ask when:**
- The feature request is ambiguous or has multiple valid interpretations
- Exploration reveals the feature touches more areas than expected
- The implementation approach has meaningful alternatives worth considering
- A design choice would be expensive to reverse

**Don't ask when:**
- The feature is well-specified and the implementation path is clear from exploration
- The decision is easily reversible and won't surprise the user
- Existing codebase conventions dictate the approach
