---
name: setup
description: Interactive setup wizard for names, personality, and user context
disable-model-invocation: true
---

# Setup Wizard

You are running the setup wizard. Walk the user through configuring their bot.

## Step 1: Detect current state

Before asking anything, check what's already configured:

1. Read IDENTITY.md — check if it contains the default template marker `personal ADHD-friendly task assistant` (this means it hasn't been customized)
2. Glob for USER.md — check if it exists
3. Note: the current configured names (user and bot) are already in your system prompt context

## Step 2: Route

- **Already set up** (USER.md exists OR IDENTITY.md is customized): show a summary of current config (names, personality gist, user context gist) and ask what they'd like to change. Jump to the relevant section when they answer.
- **Fresh setup**: ask "quick setup (3 questions) or full walkthrough?"

## Fast path (3 questions, one message each)

1. **Names**: "I'm [bot name] and you're [user name] — want to change either?" → if yes, call `update_names` with both names (both are required), then rewrite IDENTITY.md replacing the old names with the new ones from the tool response. Note: system prompt still has old names until restart.
2. **About you**: "What do you do and what's your typical schedule?" → write USER.md with the basics (work/role, rough hours).
3. **Personality**: "Any personality tweaks? More casual? More structured? Or is the default good?" → edit IDENTITY.md if requested, otherwise keep default.

## Extended path (full walkthrough)

1. **Names** (same as fast Q1)
2. **IDENTITY.md** section-by-section:
   - Personality: how formal/casual, humor level, directness
   - Communication style: response length preference, when to use forks
   - When overwhelmed: one thing vs list, how to push back
   - Write complete IDENTITY.md from answers
3. **USER.md** detailed:
   - Work/study: role, current projects
   - Schedule: work hours, timezone, meeting patterns
   - ADHD patterns: what helps, what doesn't, energy patterns
   - Current priorities: top 3 things on their plate
   - Write USER.md from answers

## Finish

- Summarize what was configured in 3-4 lines
- If names were changed: mention "use `/restart` to apply the new names everywhere"
- If this was fresh setup: suggest trying a routine ("want me to set up a morning check-in?")

## Rules

- Ask ONE question at a time. Wait for the answer before moving on.
- Keep questions conversational, not form-like.
- Don't show raw file contents or YAML — just summarize naturally.
- Use Write/Edit tools for IDENTITY.md and USER.md directly.
