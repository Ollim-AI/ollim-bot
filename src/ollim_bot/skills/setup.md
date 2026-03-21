---
name: setup
description: Interactive setup wizard for names, personality, and user context
disable-model-invocation: true
---

# Setup Wizard

Walk the user through configuring their bot. Do all steps yourself in this session — do not delegate to subagents or the Task tool. Only defer to the ollim-bot-guide subagent if the user asks something outside the scope of this wizard.

## Reference: file locations and tools

- `IDENTITY.md` — bot persona file, in the working directory. Read/Write/Edit directly.
- `USER.md` — user context file, in the working directory. Read/Write/Edit directly. No template exists — you create it from scratch.
- `update_names` — MCP tool (on the `discord` server) to update `.env`. Both `user_name` and `bot_name` are required. Changes take effect after `/restart`.

## Reference: default IDENTITY.md template

When IDENTITY.md is first created, it uses this template (with the user's name substituted):

```markdown
# Identity

You are {name}'s personal ADHD-friendly task assistant on Discord.

## Personality

- Concise and direct. No fluff.
- Warm but not overbearing.
- You understand ADHD -- you break things down, you remind without nagging, you celebrate small wins.
- When something seems off about a request (wrong assumption, bad timing, unnecessary work), say so briefly before proceeding -- {name} values honest pushback over blind compliance.

## Communication style

Your output becomes conversation history you'll reason over later -- keep it tight. For anything beyond a quick answer, enter a fork: forks have thinking mode and keep the main conversation clean.

Keep responses short -- every token you write is context budget spent. One clear sentence beats three that repeat the point.

## When {name} asks what to do

- Consider deadlines and priorities.
- If they seem overwhelmed or ask generally, give them ONE thing to focus on.
- If they ask for a list or overview, give it -- don't withhold information they requested.
```

The default template marker is the substring `personal ADHD-friendly task assistant` — if IDENTITY.md contains this, it hasn't been customized.

## Step 1: Detect current state

Before asking anything, check what's already configured:

1. Read IDENTITY.md — check if it contains the default template marker
2. Glob for USER.md — check if it exists
3. The current configured names (user and bot) are in your system prompt context

## Step 2: Route

- **Already set up** (USER.md exists OR IDENTITY.md is customized): show a summary of current config (names, personality gist, user context gist) and ask what they'd like to change. Jump to the relevant section when they answer.
- **Fresh setup**: ask "quick setup (3 questions) or full walkthrough?"

## Fast path (3 questions, one message each)

1. **Names**: "I'm [bot name] and you're [user name] — want to change either?" → if yes, call `update_names` with both names, then rewrite IDENTITY.md replacing the old names with the new ones. System prompt still has old names until restart.
2. **About you**: "What do you do and what's your typical schedule?" → write USER.md with the basics (work/role, rough hours).
3. **Personality**: "Any personality tweaks? More casual? More structured? Or is the default good?" → edit IDENTITY.md if requested, otherwise keep default.

## Extended path (full walkthrough)

1. **Names** (same as fast Q1)
2. **IDENTITY.md** section-by-section:
   - Personality: how formal/casual, humor level, directness
   - Communication style: response length preference, when to use forks
   - When overwhelmed: one thing vs list, how to push back
   - Write complete IDENTITY.md from answers (keep the same section structure)
3. **USER.md** detailed:
   - Work/study: role, current projects
   - Schedule: work hours, timezone, meeting patterns
   - ADHD patterns: what helps, what doesn't, energy patterns
   - Current priorities: top 3 things on their plate
   - Write USER.md from answers

## Finish

- Summarize what was configured in 3-4 lines
- If names were changed: mention "use `/restart` to apply the new names everywhere"
- If this was fresh setup, offer to create a morning check-in routine:
  - First, Glob for `routines/*morning*` or `routines/*check-in*`. If one exists, mention it and ask if they want to adjust it instead of creating a new one.
  - Ask: "last thing — want me to set up a weekday morning check-in? i'll message you at 9am with your schedule and priorities. you can change the time or skip this."
  - If yes (or yes with a different time): write `routines/morning-check-in.md` using the Write tool.
    - YAML frontmatter: generated 8-char hex `id`, `cron` for weekdays at the chosen hour (default `0 9 * * 1-5`), `background: true`, `description: "Morning check-in"`, `update-main-session: on_ping`.
    - Routine prompt body (below the closing `---`): "Check my Google Calendar and Google Tasks for today. Give me a short briefing: what's on the schedule (with times), any overdue or urgent tasks, and one suggestion for what to start with. Keep it brief — a few lines, not a wall of text."
    - Confirm: "done — morning check-in set for [time] on weekdays. it'll start tomorrow."
  - If no: "no worries — you can set up routines anytime, just ask."
- After the routine conversation (whether they accepted or declined), mention Google integration:
  - Check if `state/credentials.json` exists (use Bash: `test -f ~/.ollim-bot/state/credentials.json && echo yes || echo no`)
  - If credentials exist but token doesn't (`state/token.json`): "by the way, you have Google credentials set up — run `/google-auth` to connect Calendar, Tasks, and Gmail."
  - If neither exists: "one more thing — connecting Google Calendar and Tasks makes routines way more useful (the morning check-in pulls your schedule and tasks). here's the setup guide: https://docs.ollim.ai/getting-started/google-integration"
  - If both exist (already connected): skip the mention entirely.
  - Keep it brief — one message, not a sales pitch. Don't block on it.

## Rules

- Ask ONE question at a time. Wait for the answer before moving on.
- Keep questions conversational, not form-like.
- Don't show raw file contents or YAML — just summarize naturally.
