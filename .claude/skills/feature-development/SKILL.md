---
name: feature-development
description: Use when building new features or significant enhancements that touch multiple files or introduce new patterns — new commands, new integrations, new routines, cross-module work. Not for bugs, refactoring, or review. Five phases: understand, explore, clarify, implement, review.
argument-hint: [feature description]
disable-model-invocation: true
hooks:
  Stop:
    - hooks:
        - type: prompt
          prompt: >-
            Check if this feature-development run covered all 5 phases:
            Understand, Explore, Clarify, Implement, Review.
            Clarify may be explicitly skipped with justification — that counts.
            Implementation without prior Explore is always a failure.
            Respond {"ok": true} if all addressed,
            or {"ok": false, "reason": "Skipped: <phases>. <next step>."}.
          timeout: 30
  PostToolUse:
    - matcher: "Edit|Write"
      hooks:
        - type: command
          command: |
            FILE=$(jq -r '.tool_input.file_path' < /dev/stdin)
            case "$FILE" in *.py) ;; *) exit 0;; esac
            uv run ruff check --fix "$FILE" 2>&1 && uv run ruff format "$FILE" 2>&1
          timeout: 30
---

# Feature Development

Systematic feature development in five phases. Use `AskUserQuestion` for every user decision — structured multi-choice questions over open-ended text.

## Codebase snapshot

Recent changes: !`git diff --stat HEAD~5 2>/dev/null || echo "(< 5 commits)"`
Python files: !`find src -name '*.py' | wc -l`
Largest modules: !`wc -l src/ollim_bot/*.py 2>/dev/null | sort -rn | head -10`

## Phase 1: Understand

Confirm what needs to be built before exploring code.

1. If `$ARGUMENTS` is clear, summarize your understanding in 2-3 sentences
2. Check existing docs and plans for prior discussion of this feature
3. **Confirm** via `AskUserQuestion` — for clear requests, a single "Does this match what you want?" with proceed/adjust options suffices

If ambiguous, use `AskUserQuestion` to narrow scope (what problem, what behavior, constraints).

## Phase 2: Explore

Understand the relevant codebase deeply before designing.

**Dispatch 2-3 parallel Explore agents** (`Agent` tool, `subagent_type="Explore"`, `run_in_background=true`), each with a focused prompt:

- **Similar features**: "Load `/design-principles` first. Find features similar to $ARGUMENTS and trace their implementation — entry points, data flow, integration patterns. Evaluate whether existing patterns should be reused or extended."
- **Architecture & abstractions**: "Load `/design-principles` first. Map the architecture and abstractions relevant to $ARGUMENTS — module boundaries, shared state, execution contexts. Flag boundary violations or coupling concerns."
- **Integration points**: "Load `/design-principles` first. Identify all integration points for $ARGUMENTS — what modules/patterns does this need to connect with? Note where new boundaries or interfaces are needed."

Each agent must end its response with:

```
## Result
- **key_files**: [5-10 absolute file paths]
- **patterns**: [2-4 codebase patterns/conventions discovered]
- **concerns**: [0-3 potential issues or constraints]
```

**Wait for all agents**, then:
1. Deduplicate key_files across all results
2. Read all identified key files
3. Merge patterns and concerns into a single summary

**Exploration decision tree:**
- If feature touches multiple execution contexts (main/interactive fork/bg fork) → load `/async-principles`, map contextvar boundaries
- If feature needs new Discord message sending → verify channel-sync invariant via `stream_chat` entry points (see CLAUDE.md)
- If feature introduces module-level mutable state → load `/async-principles`, decide contextvar vs lock, document choice
- If feature produces user-visible output → load `/ux-principles`, note output format and trigger conditions

**Use `SearchOllimBot`** (the `docs` MCP server) for architecture and convention questions — e.g., "how does ping budget work", "how to add an MCP tool". Prefer it over grep for "how does X work" questions; use code exploration for implementation details.

**Phase 2 output** — present before proceeding:
1. Key files (grouped by role: entry point, data, integration)
2. Patterns to reuse (with file:line references)
3. Decision tree results (which branches fired, what was loaded)
4. If the solution is prompt/routine/doc changes rather than code → state this explicitly, skip Phase 4, and document what to change and where

## Phase 3: Clarify

Surface design decisions the user should weigh in on.

**Skip when** exploration reveals a single clear path with no meaningful alternatives. State that you're skipping and why.

**When clarification is needed:**

1. Review exploration findings against the original request
2. Identify genuine decisions: approach alternatives, scope boundaries, edge-case strategies, integration choices
3. **Present via `AskUserQuestion`** — batch related decisions (up to 4 questions per call):
   - 2-4 concrete options with short tradeoff descriptions
   - Recommended option first (add "(Recommended)" to the label)
   - Multi-select for non-exclusive choices

**Don't ask when:**
- Existing codebase conventions dictate the approach
- The decision is easily reversible and won't surprise the user

## Phase 4: Implement

1. Load `/python-principles`
2. If concurrency involved: load `/async-principles`
3. If user-facing: load `/ux-principles`
4. If architectural decisions: load `/design-principles`
5. Follow CLAUDE.md code health rules
6. Implement following chosen architecture and codebase conventions

If implementation reveals a design fork not covered in Phase 3 — where both paths are reasonable and conventions don't decide — use `AskUserQuestion` before continuing.

## Phase 5: Review

Two-stage review after implementation.

### Stage 1: Spec Compliance

Did I build what was asked? Check independently — don't trust your own memory.

- **Missing requirements**: are there requirements I skipped or missed?
- **Extra work**: did I build things that weren't requested? Over-engineer?
- **Misunderstandings**: did I interpret requirements differently than intended?

### Stage 2: Code Quality

Load `/code-review` and run it against the changes (confidence ≥80 filter).

For large changes (5+ files), dispatch a fresh-context review agent (`Agent` tool, `subagent_type="general-purpose"`).

**Phase 5 output:**
1. Requirements checklist (each requirement → met / partial / missed)
2. Code review verdict (confidence score, critical issues if any, files touched)

## Failure Modes

- **Empty exploration** (agents return no relevant files) → widen search to adjacent modules, or `AskUserQuestion` for entry-point hints
- **Design fork during implementation** (two reasonable paths, conventions don't decide) → stop, `AskUserQuestion` with options and tradeoffs
- **Critical review finding** (confidence ≥80 issue violating a code health rule) → fix in-place, re-run Stage 2 on affected files
- **User skips clarification** (declines or says "you decide") → document assumption inline (`# Assumption: ...`), flag in Phase 5
