# Interrupt Command & Fork Button Interrupt — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `/interrupt` slash command and make agent-routed button clicks interrupt an active fork stream.

**Architecture:** Two small additions to existing files. `/interrupt` is a new slash command in `bot.py`. Button interrupt is a 3-line guard added to `_handle_agent_inquiry` in `views.py`.

**Tech Stack:** discord.py, existing `Agent.interrupt()` and `Agent.lock()`

---

### Task 1: Add `/interrupt` slash command

**Files:**
- Modify: `src/ollim_bot/bot.py:295` (insert new command before `/permissions`)

**Step 1: Add the slash command**

Insert before the `/permissions` command (line 295):

```python
@bot.tree.command(name="interrupt", description="Stop the current response")
async def slash_interrupt(interaction: discord.Interaction):
    if agent.lock().locked():
        await agent.interrupt()
    await interaction.response.defer()
    await interaction.delete_original_response()
```

Pattern: fire-and-forget interrupt (no lock acquisition), then silently dismiss the interaction.

**Step 2: Run the bot locally to verify slash command registers**

Run: `uv run ollim-bot`
Expected: "synced N slash commands" (N should be one more than before)

**Step 3: Commit**

```bash
git add src/ollim_bot/bot.py
git commit -m "Add /interrupt slash command"
```

---

### Task 2: Interrupt fork on agent-routed button click

**Files:**
- Modify: `src/ollim_bot/views.py:88-107` (`_handle_agent_inquiry`)

**Step 1: Add interrupt-before-lock guard**

In `_handle_agent_inquiry`, after the `defer()` call and before `async with _agent.lock()`, add the fork interrupt check:

```python
async def _handle_agent_inquiry(
    interaction: discord.Interaction, inquiry_id: str
) -> None:
    prompt = inquiries.pop(inquiry_id)
    if not prompt:
        await interaction.response.send_message(
            "this button has expired.", ephemeral=True
        )
        return

    assert _agent is not None
    channel = interaction.channel
    assert isinstance(channel, discord.abc.Messageable)
    await interaction.response.defer()
    # Interrupt active fork stream so the inquiry gets immediate attention
    if _agent.lock().locked():
        await _agent.interrupt()
    async with _agent.lock():
        set_channel(channel)
        permissions.set_channel(channel)
        await channel.typing()
        await stream_to_channel(channel, _agent.stream_chat(f"[button] {prompt}"))
```

This mirrors the exact pattern from `bot.py:276-277` (`on_message` interrupt-on-new-message).

**Step 2: Commit**

```bash
git add src/ollim_bot/views.py
git commit -m "Interrupt fork stream on agent-routed button click"
```

---

### Task 3: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Add `/interrupt` to the slash commands section**

Add to the "Discord slash commands" section:

```
- `/interrupt` -- stop current response (fire-and-forget, no lock, silent)
```

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "Document /interrupt in CLAUDE.md"
```
