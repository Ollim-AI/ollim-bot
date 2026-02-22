# /thinking slash command

Toggle extended thinking on or off in real time.

## Design

Discord slash command with a single `enabled` choice (on / off).

- **On**: `max_thinking_tokens = 10000`
- **Off**: `max_thinking_tokens = None`

### Implementation

`agent.set_thinking(enabled: bool)`:
1. `self.options = replace(self.options, max_thinking_tokens=10000 if enabled else None)`
2. `await self._drop_client()` — no live setter exists on `ClaudeSDKClient`, so drop
   and let the next message reconnect with new options. Session ID is preserved.

Discord registration in `bot.py`:
```python
@bot.tree.command(name="thinking", description="Toggle extended thinking")
@discord.app_commands.choices(enabled=[
    discord.app_commands.Choice(name="on", value="on"),
    discord.app_commands.Choice(name="off", value="off"),
])
async def slash_thinking(interaction, enabled: discord.app_commands.Choice[str]):
    await agent.set_thinking(enabled.value == "on")
    await interaction.response.send_message(f"thinking: {enabled.value}.")
```

No lock needed — `set_thinking` updates options then drops client (same as `/model`
pattern per CLAUDE.md). The drop is safe because the session ID stays intact.

### Files changed

- `agent.py` — add `set_thinking()` method
- `bot.py` — add `/thinking` slash command
- `CLAUDE.md` — document the new command
