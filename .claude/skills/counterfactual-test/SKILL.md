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

### 2. Define the intervention

Build an `Intervention` from the user's description. Common patterns:

| Goal | Intervention |
|------|-------------|
| Test a system prompt change | `Intervention(system_prompt_append="New instruction here")` |
| Test with tools restricted | `Intervention(disallowed_tools=["Bash"])` |
| Test with a cheaper model | `Intervention(model="haiku")` |
| Test a different message | `Intervention(message_override="Rephrased question")` |
| Replace system prompt entirely | `Intervention(system_prompt_replace="Custom prompt")` |

Combine fields freely. Safety caps default to 5 turns and $0.50 per run.

### 3. Run the test

**CLI** (preferred — same conventions as `claude-history`):
```bash
counterfactual <session> <rewind_uuid> --append "Your instruction"
```

Session accepts UUID prefixes, `prev`, `prev-N`, or slug names — same as `claude-history transcript`.

Common flags:
- `--cwd` / `--project` — same as claude-history (default: `~/.ollim-bot`)
- `--append "text"` — append to system prompt
- `--replace-prompt "text"` — replace system prompt entirely
- `--model haiku` — use a different model
- `--message "text"` — send a different message than the original
- `--disallow Bash` — disallow a tool (repeatable)
- `--max-turns 1` — limit turns (default: 5)
- `--max-budget 0.25` — limit cost per run in USD (default: 0.50)
- `--with-baseline` — also run with original settings (doubles cost)
- `-v` — verbose logging

**Python API** (for programmatic use):
```python
import asyncio
from ollim_bot.eval.counterfactual import run_counterfactual, Intervention

result = asyncio.run(run_counterfactual(
    session_id="<session_id>",
    rewind_uuid="<uuid>",
    intervention=Intervention(system_prompt_append="Prefer Read over Bash."),
    cwd="~/.ollim-bot",
))
```

### 4. Interpret results

The CLI shows a formatted side-by-side comparison of original vs variant, including text, tool calls, and cost.

The **baseline** (when enabled with `--with-baseline`) re-runs with original settings. Differences between original and baseline indicate non-determinism (sampling noise). Differences between baseline and variant indicate the intervention's effect.

### 5. Cost awareness

- Default caps: $0.50/run, $1.00 total for baseline+variant
- Omitting `--with-baseline` (the default) halves cost
- `--max-turns 1` for quick smoke tests
- `--model haiku` for cheap exploration

## Known divergences from production

The re-run environment is standalone (bot not running), so:
- **MCP tools**: Only the `docs` server is available. Discord MCP tools (`ping_user`, `discord_embed`, etc.) are not connected. Pick rewind points where the response didn't use discord tools.
- **Hooks**: No `state_dir_guard` or `auto_commit_hook`. The re-run can write to state/.
- **Permissions**: `bypassPermissions` mode — tools denied in production will succeed.
- **Non-determinism**: LLM responses vary between runs. Use the baseline to measure drift vs. intervention effect.
- **Profile drift**: The system prompt is built from current `IDENTITY.md` and `USER.md`. If these changed since the original session, both baseline and variant use the new versions — differences may reflect profile changes, not non-determinism.
