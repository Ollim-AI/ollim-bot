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

```python
import asyncio
from tests.counterfactual import run_counterfactual, Intervention

result = asyncio.run(run_counterfactual(
    session_id="<session_id>",
    rewind_uuid="<uuid>",
    intervention=Intervention(
        system_prompt_append="Always prefer Read over Bash for file reading.",
    ),
    cwd="~/.ollim-bot",  # Must match the bot's working directory
))
```

Set `skip_baseline=True` to halve cost (only runs the variant, not baseline).

### 4. Interpret results

Compare `result.original` vs `result.variant`:
- **`.text`** — what the agent said
- **`.tool_calls`** — which tools it used and with what inputs
- **`.total_cost_usd`** — cost of the run

The **baseline** (when not skipped) re-runs with original settings. Differences between original and baseline indicate non-determinism (sampling noise). Differences between baseline and variant indicate the intervention's effect.

### 5. Cost awareness

- Default caps: $0.50/run, $1.00 total for baseline+variant
- `skip_baseline=True` halves cost
- `Intervention(max_turns=1)` for quick smoke tests
- `Intervention(model="haiku")` for cheap exploration

## Known divergences from production

The re-run environment is standalone (bot not running), so:
- **MCP tools**: Only the `docs` server is available. Discord MCP tools (`ping_user`, `discord_embed`, etc.) are not connected. Pick rewind points where the response didn't use discord tools.
- **Hooks**: No `state_dir_guard` or `auto_commit_hook`. The re-run can write to state/.
- **Permissions**: `bypassPermissions` mode — tools denied in production will succeed.
- **Non-determinism**: LLM responses vary between runs. Use the baseline to measure drift vs. intervention effect.
