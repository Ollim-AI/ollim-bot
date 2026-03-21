---
name: feature-development
description: Orchestrate specialist agents to produce a refined implementation plan for a feature. Use when developing a new feature or fixing a bug that benefits from multiple specialist perspectives (context engineering, UX, prompt quality, product alignment). Triggers a full specialist review automatically.
argument-hint: <feature description or bug to fix>
allowed-tools: Read, Write, Grep, Glob, Bash, Agent, AskUserQuestion, EnterPlanMode, ExitPlanMode
---

Produce a refined implementation plan by orchestrating specialist agents. Challenge first, then build.

## Phase 1: Enter plan mode and run the critic

Call `EnterPlanMode` immediately.

Run the critic agent before any exploration:

```
Agent task: "You are a product critic for ollim-bot. Your job is to challenge feature requests before the team invests in elaboration.

Read the product philosophy section from /home/julius/ollim-bot/CLAUDE.md (the section starting with 'Product philosophy'). Pay particular attention to the 4 core beliefs and their priority order.

Feature request:
<FEATURE_DESCRIPTION>

Challenge this feature on 5 dimensions:

1. **Problem framing**: Is this actually the problem, or a symptom? What is the real user experience failure?
2. **Solution fit**: Is the proposed solution the minimum effective intervention? Are there simpler alternatives?
3. **Product philosophy alignment**: Score each of the 4 core beliefs (1-5, where 5 = perfect fit). Show your scoring.
4. **Scope risk**: What is the smallest version of this fix? What is the biggest this could grow into?
5. **Verdict**: One of: (a) proceed as described, (b) proceed with scope reduction [specify what to cut], (c) reconsider — here is a better framing [provide reframe]

Be direct. A good critic finds the flaw in the obvious solution. A great critic also shows what the right solution is when the obvious one misses."

Tools: Read
```

Read the critic's output. Extract:
- The verdict (proceed / reduce scope / reconsider)
- The recommended framing (if different from the original)
- The scope boundaries (minimum viable version vs. maximum risk version)

## Phase 2: Conditional user gate

If the critic's verdict is **proceed as described**: skip this gate. Record the feature as stated.

If the critic's verdict is **reduce scope** or **reconsider**: present the challenge to the user:

```
AskUserQuestion: "Before building the plan, the product critic flagged a concern:

[critic's verdict and reframe, concise — 3-5 sentences]

Options:
- Proceed as originally described
- [paste critic's scope reduction if they suggested one]
- Use the critic's reframe: [paste critic's alternative framing]
- Describe your own direction"
```

If the user response is ambiguous or auto-approved with no meaningful answer, default to the critic's recommended framing.

Record the confirmed direction.

## Phase 3: Integrated planning agent

Launch one planning agent with the full context. The agent loads specialist skills inline.

```
Agent task: "You are a senior engineer planning a feature implementation for ollim-bot. You hold four specialist roles simultaneously: context engineer, UX engineer (ADHD-aware), prompt quality reviewer, and implementer.

Start by reading:
1. /home/julius/ollim-bot/CLAUDE.md (architecture overview — read the full file)
2. /home/julius/ollim-bot/.claude/skills/ux-principles/SKILL.md
3. /home/julius/.claude/skills/improve-prompt/SKILL.md

Feature: <FEATURE_DESCRIPTION>
Confirmed direction: <CONFIRMED_DIRECTION_FROM_PHASE_2>
Critic notes: <CRITIC_KEY_POINTS>

Explore the codebase to ground your plan:
- Use Grep to find files relevant to the feature (search for function names, config keys, file names mentioned in the description)
- Read the 4-6 most relevant files or sections
- Identify the specific code path the fix touches

Then produce an implementation plan and write it to ~/.claude/plans/<feature-slug>.md using Write. Create the directory first with Bash if it does not exist. Use a slug derived from the feature name (lowercase, hyphens).

The plan must contain these sections:

## Problem
One paragraph grounded in what you found in the code. Name the specific file and function where the failure occurs.

## Chosen direction
The confirmed direction with one-sentence rationale.

## Implementation steps
Numbered steps. Each step must specify: file path, function name or line range, what changes, and how to verify the change worked.

## Context engineering
Trace the information flow end-to-end through the fix. Where does information originate, where does it need to arrive? Flag any silent failure risks. Cite specific files and functions.

## User interaction design
Every user-visible event the fix produces. Apply ux-principles: acknowledge instantly, one action not a menu, escalate in stages. Write exact Discord message text for any new strings (lowercase, minimal). Note what happens on failure.

## Agent-facing text changes
Any SKILL.md, agent definition, MCP tool description, or system prompt section the fix adds or modifies. Provide the improved text for anything new. If none, write 'no agent-facing text changes required.'

## Open questions
Anything requiring user input before implementation can start. If none, write 'none.'

Ground everything in specific files and line evidence. Prefer 'in bot.py line 42' over 'somewhere in the bot.'"

Tools: Read, Write, Grep, Glob, Bash
```

## Phase 4: Deliver

Read the planning agent's output. Verify the plan file was written.

Call `ExitPlanMode`.

Present a brief summary:
- Confirmed direction and why the critic endorsed it (or what scope was cut)
- The 3 most important implementation steps
- Any open questions the user must answer before starting
- Path to the plan file (e.g., `~/.claude/plans/resume-nudge.md`)

Do not ask for approval. If there are open questions, present them as a numbered list and wait for answers before the user begins implementing.
