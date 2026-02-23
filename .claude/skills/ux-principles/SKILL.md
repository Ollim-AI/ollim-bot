---
name: ux-principles
description: Use when designing user-facing features, writing bot responses, adding notifications, or reviewing anything the user sees — messages, embeds, buttons, slash commands, proactive outreach, error handling.
---

# UX Principles

Principles for designing how ollim-bot feels to use. Derived from the codebase's existing UX patterns: instant acknowledgment, minimal voice, proactive-but-budgeted outreach, and invisible plumbing.

The user has ADHD. Every principle filters through that: attention is scarce, interruptions are costly, decisions are taxing, and "check back later" is a non-answer.

## Purpose

Every principle here exists to do one or more of these:

1. **Respect attention as the scarcest resource** — every message, notification, and button competes for limited executive function
2. **Make proactive outreach feel like care, not noise** — the bot reaches out because it's the product's core value, but uncontrolled notifications become the problem it's solving
3. **Reduce decisions, not information** — the bot should present one clear action, not a menu of options; context is good, choices are expensive
4. **Keep the bot invisible when nothing is wrong** — plumbing, errors, rate limits, and budget enforcement are internal; the user sees outcomes, not machinery

**Scoring rubric**: After designing or reviewing user-facing behavior, evaluate against [scoring-rubric.md](.claude/skills/ux-principles/scoring-rubric.md).

## How to Use

| Invocation | What Claude does |
|------------|-----------------|
| `/ux-principles` (no args) | Load for reference while designing or reviewing user-facing features. |
| `/ux-principles review` | Review a proposed feature or change for UX quality. Check each principle, flag violations, suggest fixes. |
| `/ux-principles audit [path]` | Scan existing code for UX violations: noisy errors, missing acknowledgment, decision-heavy flows, exposed plumbing. Score against rubric. |

### Before applying

1. **Identify what the user sees** — trace the code path from trigger to Discord message/embed/reaction. If the user sees nothing, these principles don't apply (but ask: should they see something?).
2. **Identify the context** — is this a direct response, a proactive outreach, a button interaction, an error case? Different contexts weight the principles differently.
3. **Check existing patterns** — the codebase has established conventions for each interaction type. Match them unless the new feature genuinely needs something different.

### Priority when principles conflict

1. **Silence over noise** — when in doubt, don't message
2. **Action over explanation** — do the thing rather than describe the thing
3. **Consistency over local optimization** — match existing interaction patterns even if a slightly better UX exists for this one case

## Responsiveness

**Acknowledge instantly, elaborate later.** *(hard rule)*
The user should never wonder "did it hear me?" Eyes reaction (👀) on message receipt, typing indicator during tool execution, 200ms buffer before the first response chunk (so it opens with a sentence, not a word). Instant acknowledgment is a separate concern from response quality — both matter, neither substitutes for the other.

When adding a new interaction path, check: what does the user see in the first 500ms? If the answer is "nothing," add an acknowledgment signal.

**The user's latest message always wins.** *(hard rule)*
New messages interrupt in-progress responses silently — no error, no "I was still talking," no leftover status messages. The interrupted response stops mid-sentence in the channel and the new message gets a fresh response. `/interrupt` deletes its own invocation so the channel stays clean.

This extends to any blocking interaction: if the user takes an action while the bot is busy, the user's action takes priority. Never queue user input behind bot output.

## Communication

**Every word earns its place.** *(hard rule)*
System responses are lowercase, one-line, unpunctuated beyond a period. `"switched to opus."` not `"I've switched the model to Opus for you!"` Empty responses get `"hmm, I didn't have a response for that."` not an apology or explanation. Embed titles are stripped of emoji (LLMs love to add them; users don't need them).

The bot's personality is defined by three constraints: concise and direct, warm but not overbearing, ADHD-aware. That's it. More personality spec creates inconsistency, not character.

When writing new system messages or response templates, read them aloud. If they sound like a customer support chatbot, rewrite.

**One action, not a menu.** *(strong default)*
Present ONE focus item, not a wall of options. The bot picks the best action and presents it. When the agent needs to offer choices, use embed buttons (2-3 max) rather than numbered lists in text.

Exception: when the user explicitly asks "what are my options?" — then list them. But default to a recommendation.

**Promise only what exists.** *(hard rule)*
Never mention, suggest, or hallucinate capabilities the bot doesn't have. "I can set a reminder for that" is only valid if the reminder system exists and works. Suggesting Notion, Slack, or Trello integrations that don't exist is the most frustrating UX failure: the user tries it, it doesn't work, trust erodes.

This applies to feature discussions too. If the user asks about something the bot can't do, say so directly rather than describing how it could hypothetically work.

## Proactive Outreach

**Push, but with a budget.** *(hard rule)*
Proactive outreach is the product's core value, but uncontrolled notifications become the problem the bot is solving. Hard daily limits (default 10/day), silent drops when budget is exhausted, skip-if-busy for routines. The agent receives its budget status at the start of every background job so it can prioritize.

When adding a new proactive feature, it MUST go through the ping budget. No exceptions, no "just this one notification." The budget is the user's trust boundary.

**Tag the source, hide the machinery.** *(strong default)*
The user needs to know WHERE a message came from: `[bg]` prefix on background text, footer on background embeds, purple embed on fork entry, color-coded embed on fork exit. Provenance prevents confusion about context ("why is the bot talking to me right now?").

But the user does NOT need to know HOW it happened: rate limit handling, budget enforcement, serialization fixes, tool denials, and internal retries are invisible. If the machinery is working correctly, the user shouldn't know it exists. If it's broken, show the outcome ("couldn't reach Google Calendar"), not the cause ("OAuth token refresh failed with 401").

**Proactive feels personal, not automated.** *(strong default)*
Scheduled prompts are framed as "reaching out" — the agent uses conversation context to make outreach relevant and personal. Chain reminders track position ("check 2 of 3"). Reconnect messages acknowledge prior context. The bot should never feel like a cron job printing a template.

The test: if you replaced the bot's name with "your assistant" and the message still sounds like it could come from a thoughtful person checking in, it passes. If it sounds like an automated alert, rewrite.

## Interactive Flows

**Successful actions complete silently.** *(strong default)*
Task done → ephemeral `"done ✓"`. Event deleted → ephemeral `"deleted"`. Button clicks that change state don't clutter the channel. Slash commands that reconfigure the bot (`/fork`, `/interrupt`) delete their own invocations.

The principle: the result IS the confirmation. A deleted task is confirmed by its absence. A forked session is confirmed by the purple embed. A model switch is confirmed by the one-liner. Don't add a second confirmation on top of the first.

Exception: destructive or irreversible actions (none exist today, but if added) should confirm before executing.

**Context survives boundaries.** *(strong default)*
Reply-to-fork-message resumes that fork's session. Reconnect acknowledges prior conversation. Button actions inject pending updates so the main session learns about direct state changes. Chain reminders carry position context. Expired buttons degrade gracefully ("this button has expired").

When adding a new interaction that crosses a context boundary (fork → main, bg → main, restart → resume), check: does the receiving context know what happened? If not, bridge it — pending updates, session tracking, or quoted content.

**Escalate in stages, not all at once.** *(strong default)*
Idle timeout prompts before forcing exit (10min soft → 10min hard). Approval times out with strikethrough, not an error. Expired buttons say "expired," not "ERROR." Fork buttons during an active fork say "already in a fork," not a stack trace.

Every degradation the user might see should have three properties: (1) it explains what happened in plain language, (2) it suggests what to do next (or does nothing, which is itself a suggestion), (3) it uses the same minimal voice as everything else.

**Safety is invisible until opted in.** *(judgment call)*
Default permission mode is `dontAsk` — non-whitelisted tools are silently denied. The user never sees approval prompts unless they choose to. When approval IS active, it's one line with three reaction options, auto-timeout at 60s, session-scoped (resets on `/clear`).

This is a judgment call because the right default depends on the user's trust level. The current default (silent deny) optimizes for zero friction at the cost of the user not knowing when tools are blocked. A more cautious user might prefer `default` mode. The principle is: match the friction level to the user's chosen trust tier, and make the tiers easy to switch between.

## When to Ask for Clarification

**Ask when:**
- A new feature sends notifications but the ping budget integration is unclear
- The user-visible copy could be interpreted multiple ways ("should this say 'done' or 'completed task: X'?")
- A feature adds a new interaction pattern that doesn't match existing conventions
- The error case could either be silent or show a message, and both are defensible

**Don't ask when:**
- The interaction pattern matches an existing one (follow the convention)
- The system message is a one-liner with an obvious format
- The feature is entirely invisible to the user (internal plumbing)
- The existing code already handles the edge case you're considering
