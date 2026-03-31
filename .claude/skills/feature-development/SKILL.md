---
name: feature-development
description: Orchestrate specialist agents to produce a refined implementation plan for a feature. Use when developing a new feature or fixing a bug that benefits from multiple specialist perspectives (context engineering, UX, prompt quality, product alignment). Triggers a full specialist review automatically.
argument-hint: <feature description or bug to fix>
allowed-tools: Read, Write, Edit, Grep, Glob, Agent, AskUserQuestion, EnterPlanMode, ExitPlanMode
---

Produce a refined implementation plan by orchestrating specialist agents. Assess risks, explore, ask, then build.

**Placeholder rule**: Every `<ANGLE_BRACKET_PLACEHOLDER>` in agent task prompts below must be replaced with the actual value before passing to the agent. Never send literal placeholder strings.

## Phase 1: Enter plan mode and run the risk advisor

Call `EnterPlanMode` immediately.

Run the risk advisor agent before any exploration:

```
Agent task: "You are a risk advisor for ollim-bot feature development. Your job is to identify what could go wrong and how to measure success — not to gatekeep.

Read the product philosophy section from /home/julius/ollim-bot/CLAUDE.md (the section starting with 'Product philosophy'). Use it as context for assessing risks, not as a filter for whether to proceed.

Feature request:
<FEATURE_DESCRIPTION>

Produce three outputs:

1. **Assumptions**: What must be true for this feature to work as intended? List each assumption and how it could be checked (code inspection, user observation, or testing).

2. **Risks**: What could go wrong? For each risk, state severity (low/medium/high) and whether it's detectable before or only after deployment. Focus on risks grounded in the product philosophy or the feature's interaction with existing systems — not abstract concerns.

3. **Measurement criteria**: How will the user know post-implementation if this feature was worth it? Suggest concrete observation criteria: what to watch for in the first week, what would indicate success, what would indicate the feature should be revised or removed. Think A/B comparisons, usage patterns, user friction signals.

Do not produce a verdict or score. The feature will be built — your job is to make the team aware of risks and give them tools to evaluate the result."

Tools: Read
```

Read the risk advisor's output. Extract:
- Key assumptions that need validation
- High-severity risks (if any)
- Measurement criteria for post-implementation evaluation

## Phase 2: Codebase exploration

Run an exploration agent to ground the plan in real code before making decisions.

```
Agent task: "You are exploring the ollim-bot codebase to ground an implementation plan.

Read /home/julius/ollim-bot/CLAUDE.md for architecture context.

Feature: <FEATURE_DESCRIPTION>

Explore the codebase systematically:
1. Use Grep to find all files related to the feature (search for function names, config keys, module names from the description)
2. Read the 4-6 most relevant files or file sections
3. For each file you read, note: file path, key functions/classes, and how they relate to this feature

Produce a structured exploration report:

## What already exists
List each relevant module with file path, key functions, and current behavior. Cite line numbers.

## What's missing
What the feature needs that doesn't exist yet. Be specific about where new code would go.

## Design decisions discovered
1-3 decisions that emerged from reading the code — things where the implementation could go multiple ways and the choice affects the outcome. For each, state the options and their trade-offs.

## Unknowns
Anything you couldn't determine from the code alone — things that require the user's domain knowledge or preference.

Every claim must cite a specific file and function. Do not speculate about code you haven't read.

Keep the report under 500 words. Summarize patterns — do not inventory every file, class, and function you found."

Tools: Read, Grep, Glob, Bash
```

## Phase 3: Exploration-based user checkpoint

Read the exploration agent's report. Cross-check the risk advisor's output from Phase 1: does the exploration confirm or refute any identified risks? A risk about complexity that the codebase already handles is not a real risk — note any that the code evidence resolves.

Extract the design decisions and unknowns.

If there are design decisions with meaningful trade-offs OR unknowns that affect implementation direction, ask the user:

```
AskUserQuestion: "I explored the codebase and found [1-2 sentence summary of what exists].

Before planning, I need your input on [N] decisions:

1. [Design decision or unknown — state the options and trade-offs concisely]
2. [Design decision or unknown]
...

Which direction for each?"
```

Rules for this checkpoint:
- Only ask about decisions where the answer changes what the plan contains — not confirmations of the obvious.
- If the feature request was specific enough and exploration found no ambiguity, skip this checkpoint and note why.
- Combine all questions into ONE AskUserQuestion call, not multiple.
- If the user's answer is partial, use reasonable defaults for unanswered parts and note what you assumed.

Record the user's decisions.

**Iterative refinement**: If the request is still ambiguous after Phase 3, or the user explicitly asked for back-and-forth discussion, use additional `AskUserQuestion` calls to narrow scope before planning. Each question should present a concrete trade-off or option discovered during exploration — not ask for approval. Stop iterating when the direction is specific enough to produce implementation steps with file paths.

## Phase 4: Planning agent

Launch the planning agent with the full context including exploration findings and user decisions. ultrathink

```
Agent task: "You are a senior engineer planning a feature implementation for ollim-bot. You hold four specialist roles simultaneously: context engineer, UX engineer (ADHD-aware), prompt quality reviewer, and implementer.

When specialist perspectives conflict, prioritize: implementation correctness > information flow completeness > user experience > agent text quality.

Start by reading:
1. /home/julius/ollim-bot/CLAUDE.md (architecture overview — read the full file)
2. /home/julius/ollim-bot/.claude/skills/ux-principles/SKILL.md
3. /home/julius/.claude/skills/improve-prompt/SKILL.md

Feature: <FEATURE_DESCRIPTION>
Confirmed direction: <CONFIRMED_DIRECTION_FROM_PHASE_3>
Risk assessment: <RISK_ADVISOR_OUTPUT> (assumptions, risks, measurement criteria from Phase 1)

Exploration findings:
<PASTE_EXPLORATION_REPORT>

User decisions:
<PASTE_USER_DECISIONS_FROM_PHASE_3_OR_'none — feature was unambiguous'>

Verify the exploration findings by reading the cited files yourself — do not trust the exploration report blindly. If you find discrepancies, use what you read directly.

Then produce an implementation plan as your response output. Do not write any files — return the full plan text so the caller can write it.

The plan must contain these sections:

## Problem
One paragraph grounded in what you found in the code. Name the specific file and function where the failure occurs.

## Chosen direction
The confirmed direction with one-sentence rationale.

## Implementation steps
Numbered steps. Each step must specify: file path, function name or line range, what changes, and how to verify the change worked.

## Context engineering
Trace the information flow end-to-end through the fix. Where does information originate, where does it need to arrive? Flag any silent failure risks. Cite specific files and functions.
— Complete when: full chain origin → [each intermediate transform with file:function] → destination. Flags any step where data could be silently lost, corrupted, or stale.

## User interaction design
Every user-visible event the fix produces. Apply ux-principles: acknowledge instantly, one action not a menu, escalate in stages. Write exact Discord message text for any new strings (lowercase, minimal). Note what happens on failure.
— Complete when: lists every user-visible event (message, reaction, embed, error). Provides exact Discord message text for new strings. States failure behavior for each event.

## Agent-facing text changes
Any SKILL.md, agent definition, MCP tool description, or system prompt section the fix adds or modifies. Provide the improved text for anything new. If none, write 'no agent-facing text changes required.'

## Testing strategy
Specific test names and what each verifies. For runtime behavior changes: behavior tests. For pure logic: unit tests. Include the test file path and a one-line description of each test.
— Complete when: names each test function, its file path, and what specific behavior it verifies. Distinguishes unit vs. behavior tests with rationale.

## Validation strategy
How to verify post-implementation that the feature was worth building. Informed by the risk advisor's measurement criteria. Include: what to observe in the first week of use, what signals success, what signals the feature should be revised or removed. If applicable, suggest A/B comparison approaches (e.g., use the feature for a week, then disable it — did behavior improve?). This section addresses product-level validation, not code-level testing.
— Complete when: lists concrete observable criteria, timeframe, and decision triggers (keep/revise/remove).

## Review gates
Which review passes to run before merging. For each applicable gate, specify the gate name, which files/sections it targets, and what specific risk it should catch for this feature. Gates: /simplify (always for code changes), /improve-prompt (for agent-facing text), context-engineer review (for information flow changes).

## Open questions
Anything requiring user input before implementation can start. If none, write 'none.'

## Requirements traceability
List each user requirement from the confirmed direction. For each, cite the implementation step(s) and test(s) that address it. If a requirement has no corresponding step or test, either add one or explain why it's deferred.

Grounding rule: every implementation step must reference a file you actually Read in this session. If you haven't read it, read it before citing it."

Tools: Read, Grep, Glob
```

Write the planning agent's output to the plan mode designated file (the path shown in the plan mode system message).

## Phase 4.5: Plan verification

Read the plan file. Spawn a verification agent:

```
Agent task: "You are verifying an implementation plan for ollim-bot. Read the plan at <PLAN_FILE_PATH>.

Check four things:

1. **Grounding**: Every implementation step cites a specific file and function. Read each cited file to confirm the reference is accurate (function exists, line range is correct, behavior matches what the plan claims).

2. **Section depth**: The following sections must not be single-sentence stubs:
   - Context engineering: must trace a full origin→destination chain with file:function citations
   - User interaction design: must list specific events and exact message text
   - Testing strategy: must name specific test functions with file paths
   Flag any section that falls short.

3. **Direction alignment**: Compare the plan's 'Chosen direction' with the confirmed direction: <CONFIRMED_DIRECTION>. Flag any drift.

4. **Requirements coverage**: Read the 'Requirements traceability' section. Verify that every requirement from the confirmed direction maps to at least one implementation step and one test. Flag any requirement with no corresponding deliverable.

Output: list of issues found, or 'no issues' if the plan passes all checks."

Tools: Read, Grep, Glob
```

If issues found: fix minor issues (wrong line numbers, typos) inline. For shallow sections, re-generate with a focused agent call.

## Phase 5: Open questions checkpoint

Read the plan mode file. Check the "Open questions" section.

If there are open questions (section is not 'none'):

```
AskUserQuestion: "The plan is drafted at [plan file path]. Before finalizing, there are open questions:

[paste open questions from the plan, numbered]

Your answers will be incorporated into the final plan."
```

After receiving answers, update the plan file: resolve the open questions in the relevant sections and change the "Open questions" section to 'none — resolved' or to only the remaining unresolved items.

If the "Open questions" section is 'none': skip this checkpoint.

## Phase 6: Deliver

Call `ExitPlanMode`.

Present a brief summary:
- Confirmed direction and key risks identified by the risk advisor
- The 3 most important implementation steps
- The validation strategy (how to measure post-implementation success)

`ExitPlanMode` presents the plan for user approval — do not duplicate it or ask separately.
