# Skill Specification

Skills are reusable instruction sets stored as directories under `skills/`.
Each skill is a directory containing a `SKILL.md` with YAML frontmatter and a
markdown body.

## Directory structure

```
skills/
├── email-triage/
│   ├── SKILL.md          # Required
│   └── references/       # Optional — supporting docs loaded on demand
├── task-review/
│   └── SKILL.md
└── weekly-review/
    └── SKILL.md
```

## SKILL.md format

```yaml
---
name: email-triage
description: Process and triage emails by priority, flag action items, draft replies.
---

## Instructions

1. Read unread emails via gmail-reader subagent
2. Categorize: urgent (needs response today), actionable (needs task), FYI
3. For urgent: draft a reply and ping the user
4. For actionable: create Google Tasks with due dates
5. For FYI: one-line summary in report, don't ping
```

## Required fields

| Field | Constraints |
|-------|-------------|
| `name` | Lowercase letters, numbers, hyphens. Must match directory name. |
| `description` | What the skill does and when to use it (1-2 sentences). |

The markdown body below `---` contains the full instructions.

## Naming

- Directory name must match the `name` field: skill `email-triage` lives at
  `skills/email-triage/SKILL.md`
- Use lowercase and hyphens only

## Using skills in routines & reminders

Add `skills:` to YAML frontmatter to auto-load skill instructions when the
job fires:

```yaml
---
id: "abc12345"
description: "8 AM daily — morning review"
cron: "0 8 * * *"
background: true
skills:
  - email-triage
  - task-review
---

Morning review. Check email for anything urgent, review today's tasks.
```

When the routine fires, referenced skill instructions are injected into the
prompt before the routine body. Works for both background and foreground jobs.
Chain reminders inherit `skills:` from the parent.

## Supporting files

Place additional reference material in the skill directory:

```
skills/email-triage/
├── SKILL.md
└── references/
    └── priority-rules.md
```

The SKILL.md can reference these: "See `skills/email-triage/references/priority-rules.md`
for the priority classification rules." The agent loads them on demand via Read.

## Dynamic context injection

Use `!`command`` in the markdown body to inject live data at fire time. The
command runs as a subprocess (no shell) and is replaced with its stdout.

```markdown
## Current tasks

!`ollim-bot tasks list`

## Today's calendar

!`ollim-bot cal today`
```

When the skill loads at fire time, each `!`command`` is replaced with the
command's stdout. If a command fails, a bracketed error marker appears instead
(e.g., `[command failed (exit 1): cmd]`).

**Rules:**
- Commands run with `cwd=~/.ollim-bot/` (the data directory)
- No shell interpretation — pipes, redirects, and globs don't work (use `sh -c '...'` if needed)
- Per-command timeout: 10 seconds. Total timeout: 30 seconds across all commands.
- Output truncated at 2000 characters to prevent prompt bloat
- Commands that can't run before the total timeout are skipped

## Tips

- Keep SKILL.md under 500 lines — move reference material to separate files
- Be specific in `description` — it's shown in the skill index and helps you
  know when to self-load a skill
- Write instructions as prompts for yourself (you'll execute them)
- Test a skill by reading it in a fork before attaching to routines
