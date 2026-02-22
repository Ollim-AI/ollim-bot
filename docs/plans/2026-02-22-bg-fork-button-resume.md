# bg fork button → interactive fork resume

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Clicking an agent button on a bg routine embed opens an interactive fork resuming from that bg session's context, and investigate/fix the reply-to-fork "wrong session" bug.

**Architecture:** `_handle_agent_inquiry` in `views.py` checks `lookup_fork_session(interaction.message.id)`. If found, it enters an interactive fork via `agent.enter_interactive_fork(resume_session_id=...)`, sends the fork-enter embed, and dispatches the inquiry into the fork. Fork-enter helpers are extracted to `embeds.py` (shared between `bot.py` and `views.py`). The bg-resume prompt goes in `prompts.py`.

**Tech Stack:** discord.py, Claude Agent SDK, project-internal MCP tools

---

### Task 1: Extract fork-enter helpers to embeds.py

Currently `_send_fork_enter` in `bot.py` is a closure. `views.py` can't import from `bot.py` (circular), so extract the embed + view building to `embeds.py` where both can import.

**Files:**
- Modify: `src/ollim_bot/embeds.py`
- Modify: `src/ollim_bot/bot.py`
- Test: `tests/test_agent_tools.py`

**Step 1: Write failing tests**

Add to end of `tests/test_agent_tools.py`:

```python
# --- fork-enter embed/view helpers ---


def test_fork_enter_embed_no_topic():
    from ollim_bot.embeds import fork_enter_embed

    embed = fork_enter_embed()
    assert embed.title == "Forked Session"
    assert embed.description == "Open session"


def test_fork_enter_embed_with_topic():
    from ollim_bot.embeds import fork_enter_embed

    embed = fork_enter_embed("morning review")
    assert embed.description == "Topic: morning review"


def test_fork_enter_view_has_three_buttons():
    from ollim_bot.embeds import fork_enter_view

    view = fork_enter_view()
    items = view.children
    assert len(items) == 3
    custom_ids = {item.custom_id for item in items}
    assert custom_ids == {"act:fork_save:_", "act:fork_report:_", "act:fork_exit:_"}
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_agent_tools.py::test_fork_enter_embed_no_topic tests/test_agent_tools.py::test_fork_enter_embed_with_topic tests/test_agent_tools.py::test_fork_enter_view_has_three_buttons -v
```

Expected: ImportError or AttributeError — `fork_enter_embed`/`fork_enter_view` don't exist yet.

**Step 3: Add helpers to embeds.py**

Add after `fork_exit_embed`:

```python
def fork_enter_embed(topic: str | None = None) -> discord.Embed:
    return discord.Embed(
        title="Forked Session",
        description=f"Topic: {topic}" if topic else "Open session",
        color=discord.Color.purple(),
    )


def fork_enter_view() -> View:
    view = View(timeout=None)
    view.add_item(
        Button(
            label="Save Context",
            style=discord.ButtonStyle.success,
            custom_id="act:fork_save:_",
        )
    )
    view.add_item(
        Button(
            label="Report",
            style=discord.ButtonStyle.primary,
            custom_id="act:fork_report:_",
        )
    )
    view.add_item(
        Button(
            label="Exit Fork",
            style=discord.ButtonStyle.danger,
            custom_id="act:fork_exit:_",
        )
    )
    return view
```

Also add `Button` and `View` to the imports at the top of `embeds.py` if not already present (they are, via `from discord.ui import Button, View`).

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_agent_tools.py::test_fork_enter_embed_no_topic tests/test_agent_tools.py::test_fork_enter_embed_with_topic tests/test_agent_tools.py::test_fork_enter_view_has_three_buttons -v
```

Expected: PASS.

**Step 5: Update bot.py to use the new helpers**

In `bot.py`, import at top of file:

```python
from ollim_bot.embeds import fork_enter_embed, fork_enter_view
```

Replace the body of `_send_fork_enter` closure:

```python
async def _send_fork_enter(
    channel: discord.abc.Messageable, topic: str | None
) -> None:
    await channel.send(embed=fork_enter_embed(topic), view=fork_enter_view())
```

**Step 6: Run all tests**

```bash
uv run pytest -v
```

Expected: all pass.

**Step 7: Commit**

```bash
git add src/ollim_bot/embeds.py src/ollim_bot/bot.py tests/test_agent_tools.py
git commit -m "$(cat <<'EOF'
refactor: extract fork-enter embed/view helpers to embeds.py

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Add fork_bg_resume_prompt to prompts.py

The prompt tells the agent it's resuming a bg session and surfaces the button action.

**Files:**
- Modify: `src/ollim_bot/prompts.py`
- Test: `tests/test_agent_tools.py`

**Step 1: Write failing test**

Add to end of `tests/test_agent_tools.py`:

```python
# --- fork_bg_resume_prompt ---


def test_fork_bg_resume_prompt_contains_action():
    from ollim_bot.prompts import fork_bg_resume_prompt

    result = fork_bg_resume_prompt("task completed")
    assert "[fork-started]" in result
    assert "task completed" in result
    assert "background routine" in result
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_agent_tools.py::test_fork_bg_resume_prompt_contains_action -v
```

Expected: ImportError — `fork_bg_resume_prompt` doesn't exist.

**Step 3: Add function to prompts.py**

Add at end of `prompts.py`:

```python
def fork_bg_resume_prompt(inquiry_prompt: str) -> str:
    return (
        f"[fork-started] You are in an interactive fork continuing from the background "
        f"routine you just ran. {USER_NAME} clicked a button in response to your output. "
        f"Button action: {inquiry_prompt}\n\nRespond to their action."
    )
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_agent_tools.py::test_fork_bg_resume_prompt_contains_action -v
```

Expected: PASS.

**Step 5: Run all tests**

```bash
uv run pytest -v
```

**Step 6: Commit**

```bash
git add src/ollim_bot/prompts.py tests/test_agent_tools.py
git commit -m "$(cat <<'EOF'
feat: add fork_bg_resume_prompt for bg-session interactive forks

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Route agent buttons on bg embeds to interactive fork

Modify `_handle_agent_inquiry` in `views.py` to check if the button's message has a tracked fork session. If yes, enter an interactive fork resuming from that bg session and route the inquiry into it.

**Files:**
- Modify: `src/ollim_bot/views.py`

No unit tests here — Discord `Interaction` objects are stateful and hard to stub. Manual testing in Task 5.

**Step 1: Update imports in views.py**

Add to the import block at the top of `views.py`:

```python
from ollim_bot.embeds import fork_enter_embed, fork_enter_view
from ollim_bot.forks import clear_prompted, in_interactive_fork, touch_activity
from ollim_bot.prompts import fork_bg_resume_prompt
from ollim_bot.sessions import lookup_fork_session
```

Remove the existing `from ollim_bot.embeds import fork_exit_embed` line and replace it with a combined import (fork_exit_embed is already there):

```python
from ollim_bot.embeds import fork_enter_embed, fork_enter_view, fork_exit_embed
```

**Step 2: Replace _handle_agent_inquiry**

Replace the entire existing `_handle_agent_inquiry` function:

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

    fork_session_id = lookup_fork_session(interaction.message.id)

    if fork_session_id:
        if in_interactive_fork():
            await interaction.response.send_message(
                "already in a fork.", ephemeral=True
            )
            return
        await interaction.response.defer()
        if _agent.lock().locked():
            await _agent.interrupt()
        async with _agent.lock():
            await _agent.enter_interactive_fork(resume_session_id=fork_session_id)
            await channel.send(embed=fork_enter_embed(), view=fork_enter_view())
            set_channel(channel)
            permissions.set_channel(channel)
            await channel.typing()
            await stream_to_channel(
                channel,
                _agent.stream_chat(fork_bg_resume_prompt(prompt)),
            )
            touch_activity()
            clear_prompted()
    else:
        await interaction.response.defer()
        if _agent.lock().locked():
            await _agent.interrupt()
        async with _agent.lock():
            set_channel(channel)
            permissions.set_channel(channel)
            await channel.typing()
            await stream_to_channel(channel, _agent.stream_chat(f"[button] {prompt}"))
```

**Step 3: Run all tests**

```bash
uv run pytest -v
```

Expected: all pass (no tests for this handler; test coverage comes from manual testing in Task 5).

**Step 4: Commit**

```bash
git add src/ollim_bot/views.py
git commit -m "$(cat <<'EOF'
feat: route agent buttons on bg embeds to interactive fork

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Diagnose and fix reply-to-fork "wrong session"

The user reports that replying to a bg fork message starts a fork with main session context, not bg context. This task confirms the root cause and applies the appropriate fix.

**Files:**
- Possibly modify: `src/ollim_bot/agent.py`

**Step 1: Verify tracking works**

After a bg routine fires and sends a message, inspect the tracking file:

```bash
cat ~/.ollim-bot/fork_messages.json | python3 -m json.tool
```

Expected: one or more records with `message_id`, `fork_session_id`, `parent_session_id`, `ts`.

If the file is empty or missing: the `track_message` contextvar propagation is broken. In that case, add a module-level fallback (similar to `_channel` → `_channel_var`). Skip to Step 4b.

If records ARE present: proceed to Step 2.

**Step 2: Verify session ID in the record is the bg fork's session**

Compare the `fork_session_id` in the record against `~/.ollim-bot/session_history.jsonl`:

```bash
tail -20 ~/.ollim-bot/session_history.jsonl | python3 -c "
import sys, json
for line in sys.stdin:
    e = json.loads(line)
    print(e['event'], e['session_id'][:12])
"
```

The `fork_session_id` in `fork_messages.json` should match the session ID logged as `bg_fork` in the history.

**Step 3: Test whether that session has resumable bg context**

The likely root cause: bg fork sessions created with `fork_session=True` may be ephemeral in the Claude CLI and not resumable after the client disconnects.

Reply to the bg message. If the interactive fork opens but has no bg context (agent doesn't know what the routine did), the fix is to resume without `fork_session=True` (Step 4a).

**Step 4a: Fix — resume without fork_session=True when a specific session ID is given**

In `agent.py`, modify `create_forked_client` to accept an optional `fork` parameter:

```python
async def create_forked_client(
    self, session_id: str | None = None, *, fork: bool = True
) -> ClaudeSDKClient:
    """Create a disposable client that forks from a given or current session.

    fork=False resumes the session directly (no branching). Use when the
    target session is already a completed bg fork that may not be forkable.
    """
    sid = session_id or load_session_id()
    if sid:
        opts = replace(self.options, resume=sid, fork_session=fork)
    else:
        opts = self.options
    client = ClaudeSDKClient(opts)
    await client.connect()
    return client
```

In `enter_interactive_fork`, pass `fork=False` when a specific `resume_session_id` is provided:

```python
async def enter_interactive_fork(
    self, *, idle_timeout: int = 10, resume_session_id: str | None = None
) -> None:
    """Create an interactive fork client and switch routing to it."""
    self._fork_client = await self.create_forked_client(
        session_id=resume_session_id,
        fork=resume_session_id is None,  # fork from current only; resume bg directly
    )
    self._fork_session_id = None
    set_interactive_fork(True, idle_timeout=idle_timeout)
    touch_activity()
```

**Step 4b (only if tracking is broken): Add module-level fallback for msg collector**

If Step 1 showed `fork_messages.json` is empty, add a global fallback in `sessions.py` alongside `_msg_collector`:

```python
_msg_collector_global: list[int] | None = None


def start_message_collector() -> None:
    global _msg_collector_global
    _msg_collector_global = []
    _msg_collector.set(_msg_collector_global)


def track_message(message_id: int) -> None:
    collector = _msg_collector.get() or _msg_collector_global
    if collector is not None:
        collector.append(message_id)


def cancel_message_collector() -> None:
    global _msg_collector_global
    _msg_collector_global = None
    _msg_collector.set(None)
```

**Step 5: Run all tests**

```bash
uv run pytest -v
```

**Step 6: Commit whatever changes were made**

```bash
git add src/ollim_bot/agent.py  # or sessions.py if 4b was applied
git commit -m "$(cat <<'EOF'
fix: resume bg fork session directly for reply-to-fork

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Manual end-to-end test

**No code changes.** Verify the full feature works at runtime.

**Step 1: Trigger a bg routine**

Find a bg routine in `~/.ollim-bot/routines/` or trigger one manually:

```bash
ollim-bot routine list
# pick a bg routine's ID
```

Or temporarily lower the reminder time to fire in 1 minute to get a bg fork message.

**Step 2: Click an agent button on the embed**

When the bg routine sends an embed with agent buttons, click one.

Expected:
- A "Forked Session" embed appears with Save/Report/Exit buttons
- The agent responds in the fork with context from the bg routine (it knows what happened)
- Agent response addresses the button action

**Step 3: Verify reply-to-fork**

Reply (Discord reply feature) to the bg fork message.

Expected:
- Fork opens automatically (same as clicking a button)
- Agent has bg routine context

**Step 4: Verify "already in a fork" guard**

While in an interactive fork, click an agent button on any bg embed.

Expected:
- Ephemeral message: "already in a fork."
- No new fork opened

**Step 5: Verify non-bg embeds still route to main session**

Click an agent button on an embed sent from the main session (not a bg fork).

Expected:
- No fork opened
- Agent responds in main session as before
