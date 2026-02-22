---
name: debug-bot-history
description: Investigate ollim-bot runtime issues — missed pings, blocked routines, budget exhaustion, unexpected fork behavior, or "what happened last night?" Use when debugging bot behavior that already occurred.
argument-hint: [description of what went wrong]
allowed-tools: Bash(claude-history:*), Bash(git *), Read, Grep, Glob
---

# Debug Bot History

Investigate what the bot actually did at runtime. Code analysis alone produces plausible but wrong answers because the code shows what *should* happen, but only runtime data shows what *did* happen. Always verify against runtime data before concluding.

## Key principle

The bot's runtime sessions are a **separate Claude Code project** at `~/.ollim-bot/`. Always use `--cwd ~/.ollim-bot` with claude-history commands.

## Investigation workflow

### 1. Read the relevant code

Understand what signals to search for before searching. Read the modules involved in the issue (e.g., `ping_budget.py` for budget issues, `scheduler.py` for missed routines, `agent_tools.py` for tool behavior). If unsure which module, search for the error text or behavior keyword in `src/ollim_bot/`. Note:
- Prompt tags: `[routine-bg:ID]`, `[reminder-bg:ID]`, `[routine:ID]`, `[reminder:ID]`
- Preamble strings injected into bg forks (e.g., `Ping budget:`)
- Tool response strings (e.g., `Embed sent.`, `Message sent.`, `Budget exhausted`)

**Mapping IDs to names:** Routine/reminder IDs in prompt tags (e.g., `ac7216c2`) correspond to the `id` field in YAML frontmatter. To identify which routine/reminder a session belongs to:
```bash
grep -l "ac7216c2" ~/.ollim-bot/routines/*.md ~/.ollim-bot/reminders/*.md
```

### 2. Check deployment timeline

```bash
git log --format="%h %ai %s" --since="<relevant date>" -- src/
```

The bot runs old code until restarted. Knowing when code was deployed vs. when the bot restarted determines which sessions had new behavior.

### 3. List sessions to scope the investigation

This is the primary triage step — it shows the full timeline at a glance, including prompt previews that identify session types without reading each one.

```bash
# List sessions for a time range (best starting point)
claude-history sessions --cwd ~/.ollim-bot --since <date> --size 30

# Search for specific behavior across all sessions
claude-history search --cwd ~/.ollim-bot "<query>"
```

**Reading the session listing:**
- **Prompt previews** show session type: `[routine-bg:ID]` = bg routine, `[reminder-bg:ID]` = bg reminder, `[fork-started]` = interactive fork, `[fork-timeout]` = idle fork
- **Prompt count** signals complexity: 1 prompt = simple bg fork (fired and done), 3+ = multi-turn interaction or interactive fork
- **Timestamps** in the listing show when the session started — gaps between expected fire times indicate bot restarts

If sessions listing shows nothing for the expected time range, the bot likely wasn't running. Check `session_history.jsonl` for the last recorded session before the gap.

### 4. Read session transcripts

Once you've identified key sessions from the listing, read their transcripts to see what the agent actually saw and did.

```bash
# Read full transcript — start with -v (text + tool calls)
claude-history transcript --cwd ~/.ollim-bot <session_id> -v

# Escalate to -vv only when you need the agent's reasoning (adds thinking blocks)
claude-history transcript --cwd ~/.ollim-bot <session_id> -vv

# Read just the prompts (good for seeing what was injected)
claude-history prompts --cwd ~/.ollim-bot <session_id>

# Read one response in detail (use prompt UUID from search results)
claude-history response --cwd ~/.ollim-bot <prompt_uuid> -v
```

**Verbosity guide:** `-v` shows what happened (tool calls, text output) — use this first. `-vv` adds thinking blocks showing *why* the agent made decisions — only escalate to this when the "what" is clear but the "why" isn't.

**Useful search terms:**
- `"routine-bg"`, `"reminder-bg"` — bg fork prompts
- `"Ping budget:"` — budget status in bg preambles
- `"budget exhausted"` — blocked pings
- `"Embed sent"`, `"Message sent"` — successful tool calls
- `"Sat 03"`, `"Sun 10"` — time-of-day patterns (format: `Day HH`)

### 5. Fill gaps with data files

When session transcripts don't tell the full story, these files provide ground truth:

| File | When to use it |
|------|---------------|
| `~/.ollim-bot/session_history.jsonl` | SDK session UUIDs + parent session mapping. First 8 chars of UUID = claude-history session ID. |
| `~/.ollim-bot/ping_budget.json` | Current budget state — but only shows *current* values, not history. Useful for confirming reset timing. |
| `~/.ollim-bot/routines/*.md` | Current routine schedule (cron, background flag, model). Cross-reference with IDs from session listings. |
| `~/.ollim-bot/reminders/*.md` | Pending reminders only — consumed reminders are deleted. Use git history for past reminders. |
| `git -C ~/.ollim-bot log -- reminders/` | Reminder add/remove history with timestamps — fills gaps where sessions show nothing because the reminder was created and consumed between bg forks. |

### 6. Build a timeline

Cross-reference sources to reconstruct what happened:

1. **sessions listing** — what fired and when (from step 3)
2. **transcripts** — what the agent saw and did in each session (from step 4)
3. **git log** — code deploy timestamps (which code version was running)
4. **data files** — state that sessions don't capture (budget values, reminder chains)

Look for gaps between expected and actual fork timestamps — gaps indicate bot restarts, and past-due reminders fire immediately on restart.

## Adapting the workflow

Not every investigation needs all 6 steps:

- **"What happened at 10 PM?"** — skip to step 3 (sessions listing), read the relevant transcript (step 4). Done.
- **"Why did the budget run out?"** — steps 1-4 are essential. Trace budget state across session preambles.
- **"A reminder didn't fire"** — step 3 to check if a session exists for that time. If not, step 5 (data files) to check reminder git history and session_history.jsonl for restart gaps.
- **"New feature isn't working"** — step 2 (deployment) is critical. Compare pre/post deployment sessions.

If search yields nothing for a query, try: different field names (tool calls vs. preamble text vs. tool response), broader time patterns (`"Sat"` instead of `"Sat 03"`), or check data files directly.

## Gotchas

- **Always `--cwd ~/.ollim-bot`** — the bot's sessions are a separate project from the dev repo. Forgetting this searches dev sessions instead.
- **Code analysis is necessary but insufficient** — read the code to know what to search for, then verify with runtime data.
- **`-v` before `-vv`** — `-vv` includes thinking blocks that can be very long. Start with `-v` to see what happened, only escalate when you need to understand *why* the agent decided something.
- **Prompt count = session complexity** — 1-prompt sessions are simple bg forks. Multi-prompt sessions had follow-up interactions or tool approval flows. Use this to prioritize which transcripts to read.
- **Reminder git history fills gaps** — when you see a timeline gap between bg forks, `git -C ~/.ollim-bot log -- reminders/` shows what was created and consumed during that window.
