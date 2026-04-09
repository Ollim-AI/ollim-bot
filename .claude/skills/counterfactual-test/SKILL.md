---
name: counterfactual-test
description: >-
  Run counterfactual trajectory tests — load a production transcript,
  rewind to a point, apply an intervention, compare the outcome.
  Use when evaluating prompt changes, tool restrictions, or model swaps.
argument-hint: <session_id> <rewind_uuid> <intervention_description>
allowed-tools: Bash(claude-history *), Bash(uv run python *), Read, Write, Grep, Glob
disable-model-invocation: true
---

# Counterfactual Trajectory Test

Replay a real production interaction with modified settings to see how agent behavior changes.

## Workflow

### 1. Find the session and rewind point

List recent bot sessions:
```bash
claude-history sessions --cwd ~/.ollim-bot --since 7d
```

Read the transcript to find the interaction you want to replay:
```bash
claude-history transcript <session_id> --cwd ~/.ollim-bot
```

Note the **UUID** of the user message you want to rewind to. This is the message whose response you want to compare under different conditions.

### 2. Run the test

```bash
counterfactual <session> <rewind_uuid> [flags]
```

Session accepts UUID prefixes, `prev`, `prev-N`, or slug names — same as `claude-history transcript`.

| Goal | Command |
|------|---------|
| Test a prompt change | `counterfactual <s> <uuid> --append "New instruction"` |
| Restrict tools | `counterfactual <s> <uuid> --disallow Bash` |
| Try a cheaper model | `counterfactual <s> <uuid> --model haiku` |
| Send a different message | `counterfactual <s> <uuid> --message "Rephrased question"` |
| Replace prompt entirely | `counterfactual <s> <uuid> --replace-prompt "Custom prompt"` |
| Quick smoke test | `counterfactual <s> <uuid> --append "..." --max-turns 1` |
| Measure non-determinism | `counterfactual <s> <uuid> --append "..." --with-baseline` |

Flags combine freely. `--cwd` / `--project` work the same as claude-history (default: `~/.ollim-bot`).

### 3. Interpret results

The CLI shows original (from transcript) vs variant (with intervention) side-by-side: text, tool calls, cost.

With `--with-baseline`: differences between original and baseline = sampling noise. Differences between baseline and variant = intervention effect.

### 4. Cost awareness

- Default caps: $0.50/run, $1.00 total for baseline+variant
- Omitting `--with-baseline` (the default) halves cost
- `--max-turns 1` for quick smoke tests
- `--model haiku` for cheap exploration

## Gotchas

- **Discord MCP tools unavailable** — the bot's `ping_user`, `discord_embed`, etc. are not connected. Pick rewind points where the original response didn't use discord tools, or the comparison is invalid.
- **No state_dir_guard** — the re-run can write to `~/.ollim-bot/state/`. Check for unexpected modifications after runs.
- **bypassPermissions** — tools denied in production (`dontAsk` mode) succeed in re-runs, changing tool selection behavior.
- **Profile drift** — system prompt uses current `IDENTITY.md` and `USER.md`. If these changed since the original session, baseline vs original differences may reflect profile changes, not non-determinism.
- **Interrupted runs leave temp files** — if a run is killed, check `~/.claude/projects/` for orphaned JSONL files and delete them manually.
