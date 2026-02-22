# /thinking Command Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `/thinking` Discord slash command that toggles extended thinking on/off.

**Architecture:** Updates `max_thinking_tokens` on shared `ClaudeAgentOptions`, then drops the client so it reconnects with new options on the next message. Session ID is preserved.

**Tech Stack:** discord.py slash commands, Claude Agent SDK `ClaudeAgentOptions.max_thinking_tokens`

---

### Task 1: Add `set_thinking()` to Agent + `/thinking` slash command

**Files:**
- Modify: `src/ollim_bot/agent.py:162-168` (after `set_model`)
- Modify: `src/ollim_bot/bot.py:203-216` (after `/model` command)

**Step 1: Add `set_thinking` method to Agent class**

In `agent.py`, add after `set_model()` (line 168):

```python
async def set_thinking(self, enabled: bool) -> None:
    """Toggle extended thinking. Drops client to apply (no live setter)."""
    tokens = 10000 if enabled else None
    self.options = replace(self.options, max_thinking_tokens=tokens)
    await self._drop_client()
    if self._fork_client:
        fork = self._fork_client
        self._fork_client = None
        with contextlib.suppress(CLIConnectionError):
            await fork.interrupt()
        with contextlib.suppress(RuntimeError):
            await fork.disconnect()
```

**Step 2: Add `/thinking` slash command to bot.py**

In `bot.py`, add after the `/model` command block (after line 216):

```python
@bot.tree.command(name="thinking", description="Toggle extended thinking")
@discord.app_commands.describe(enabled="Turn thinking on or off")
@discord.app_commands.choices(
    enabled=[
        discord.app_commands.Choice(name="on", value="on"),
        discord.app_commands.Choice(name="off", value="off"),
    ]
)
async def slash_thinking(
    interaction: discord.Interaction, enabled: discord.app_commands.Choice[str]
):
    await agent.set_thinking(enabled.value == "on")
    await interaction.response.send_message(f"thinking: {enabled.value}.")
```

**Step 3: Verify no tests break**

Run: `uv run pytest -v`
Expected: all existing tests pass (no new test needed — this is config wiring)

**Step 4: Commit**

```bash
git add src/ollim_bot/agent.py src/ollim_bot/bot.py
git commit -m "feat: add /thinking slash command to toggle extended thinking"
```

---

### Task 2: Update CLAUDE.md documentation

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Add `/thinking` to the Discord slash commands section**

After the `/model` line (line 88), add:
```
- `/thinking <on|off>` -- toggle extended thinking (update options + drop client, next message reconnects)
```

After the `Agent.set_model()` line (line 94), add:
```
- `Agent.set_thinking()` -- updates `max_thinking_tokens` on shared options + drops client (no live setter)
```

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document /thinking slash command"
```
