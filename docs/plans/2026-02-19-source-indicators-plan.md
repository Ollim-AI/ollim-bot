# Source Indicators + Bg Fork Stop Guard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add source labels (main/bg/fork) to ping and embed tools, block ping on main/interactive fork, and prevent bg forks from stopping without calling report_updates.

**Architecture:** A `_source()` helper in `agent_tools.py` returns `"main"`, `"bg"`, or `"fork"` using existing `in_bg_fork()`/`in_interactive_fork()`. A contextvar `_bg_output_sent` tracks whether bg fork has sent visible output. A `Stop` hook on the agent prevents stopping until `report_updates` is called.

**Tech Stack:** Python, Claude Agent SDK hooks (`HookMatcher`, `Stop` event), discord.py embeds

---

### Task 1: Add source helper and ping_user gating

**Files:**
- Modify: `src/ollim_bot/agent_tools.py:117-156` (ping_user + new helper)
- Test: `tests/test_agent_tools.py`

**Step 1: Write failing tests for ping_user source gating**

Add to `tests/test_agent_tools.py`. Import `ping_user`, `set_channel`, `set_fork_channel` and create an `InMemoryChannel` helper:

```python
from ollim_bot.agent_tools import (
    # ... existing imports ...
    ping_user,
    set_channel,
    set_fork_channel,
)


class InMemoryChannel:
    """Collects messages and embeds sent to a channel."""

    def __init__(self):
        self.messages: list[dict] = []

    async def send(self, content=None, *, embed=None, view=None):
        self.messages.append({"content": content, "embed": embed, "view": view})


_ping = ping_user.handler


# --- ping_user source gating ---


def test_ping_user_blocked_on_main():
    set_in_fork(False)
    set_interactive_fork(False)

    result = _run(_ping({"message": "hello"}))

    assert "Error" in result["content"][0]["text"]
    assert "only available in background forks" in result["content"][0]["text"]


def test_ping_user_blocked_on_interactive_fork():
    set_interactive_fork(True, idle_timeout=10)

    result = _run(_ping({"message": "hello"}))

    assert "Error" in result["content"][0]["text"]
    assert "only available in background forks" in result["content"][0]["text"]
    set_interactive_fork(False)


def test_ping_user_prefixed_in_bg_fork():
    ch = InMemoryChannel()
    set_fork_channel(ch)
    set_in_fork(True)

    result = _run(_ping({"message": "check your tasks"}))

    assert result["content"][0]["text"] == "Message sent."
    assert ch.messages[0]["content"] == "[bg] check your tasks"
    set_in_fork(False)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_agent_tools.py -v -k "ping_user"`
Expected: FAIL — ping_user currently has no source gating

**Step 3: Implement source helper and ping_user gating**

In `src/ollim_bot/agent_tools.py`, add helper and update `ping_user`:

```python
def _source() -> Literal["main", "bg", "fork"]:
    """Return the execution context: main session, bg fork, or interactive fork."""
    if in_bg_fork():
        return "bg"
    if in_interactive_fork():
        return "fork"
    return "main"
```

Update `ping_user` function body:

```python
async def ping_user(args: dict[str, Any]) -> dict[str, Any]:
    source = _source()
    if source != "bg":
        return {
            "content": [
                {"type": "text", "text": "Error: ping_user is only available in background forks"}
            ]
        }
    channel = _channel_var.get() or _channel
    if channel is None:
        return {"content": [{"type": "text", "text": "Error: no active channel"}]}

    await channel.send(f"[bg] {args['message']}")
    return {"content": [{"type": "text", "text": "Message sent."}]}
```

Add `Literal` to typing imports.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_agent_tools.py -v -k "ping_user"`
Expected: PASS

**Step 5: Commit**

```bash
git add src/ollim_bot/agent_tools.py tests/test_agent_tools.py
git commit -m "feat: block ping_user on main/fork, prefix [bg] in bg forks"
```

---

### Task 2: Add discord_embed footer for fork sources

**Files:**
- Modify: `src/ollim_bot/agent_tools.py:117-132` (discord_embed function)
- Test: `tests/test_agent_tools.py`

**Step 1: Write failing tests for embed footer**

```python
from ollim_bot.agent_tools import discord_embed

_embed = discord_embed.handler


def test_embed_no_footer_on_main():
    ch = InMemoryChannel()
    set_channel(ch)
    set_in_fork(False)
    set_interactive_fork(False)

    _run(_embed({"title": "Tasks"}))

    assert ch.messages[0]["embed"].footer.text is discord.Embed.Empty or ch.messages[0]["embed"].footer.text is None
    set_channel(None)


def test_embed_footer_bg_fork():
    ch = InMemoryChannel()
    set_fork_channel(ch)
    set_in_fork(True)

    _run(_embed({"title": "Tasks"}))

    assert ch.messages[0]["embed"].footer.text == "bg"
    set_in_fork(False)


def test_embed_footer_interactive_fork():
    ch = InMemoryChannel()
    set_channel(ch)
    set_interactive_fork(True, idle_timeout=10)

    _run(_embed({"title": "Tasks"}))

    assert ch.messages[0]["embed"].footer.text == "fork"
    set_interactive_fork(False)
    set_channel(None)
```

Note: the exact "no footer" assertion may need adjusting — discord.py uses `None` or `Embed.Empty` for unset footers. Check actual behavior and adjust.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_agent_tools.py -v -k "embed_footer"`
Expected: FAIL — no footer logic exists

**Step 3: Implement embed footer**

Update `discord_embed` in `agent_tools.py`:

```python
async def discord_embed(args: dict[str, Any]) -> dict[str, Any]:
    channel = _channel_var.get() or _channel
    if channel is None:
        return {"content": [{"type": "text", "text": "Error: no active channel"}]}

    config = EmbedConfig(
        title=args["title"],
        description=args.get("description"),
        color=args.get("color", "blue"),
        fields=tuple(EmbedField(**f) for f in args.get("fields", [])),
        buttons=tuple(ButtonConfig(**b) for b in args.get("buttons", [])),
    )
    embed = build_embed(config)
    source = _source()
    if source != "main":
        embed.set_footer(text=source)
    view = build_view(config.buttons)
    await channel.send(embed=embed, view=view)
    return {"content": [{"type": "text", "text": "Embed sent."}]}
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_agent_tools.py -v -k "embed_footer"`
Expected: PASS

**Step 5: Commit**

```bash
git add src/ollim_bot/agent_tools.py tests/test_agent_tools.py
git commit -m "feat: add source footer to embeds from fork sessions"
```

---

### Task 3: Add bg output tracking + Stop hook

**Files:**
- Modify: `src/ollim_bot/agent_tools.py` (contextvar + flag sets + hook callback)
- Modify: `src/ollim_bot/agent.py` (register Stop hook in options)
- Test: `tests/test_agent_tools.py`

**Step 1: Write failing tests for bg output tracking and stop hook**

```python
from ollim_bot.agent_tools import bg_output_sent, require_report_hook


def test_bg_output_flag_set_on_ping():
    ch = InMemoryChannel()
    set_fork_channel(ch)
    set_in_fork(True)

    _run(_ping({"message": "test"}))

    assert bg_output_sent() is True
    set_in_fork(False)


def test_bg_output_flag_cleared_on_report():
    _run(pop_pending_updates())
    set_in_fork(True)

    _run(_ping({"message": "test"}))
    _run(_report({"message": "summary"}))

    assert bg_output_sent() is False
    set_in_fork(False)


def test_stop_hook_allows_stop_on_main():
    set_in_fork(False)

    result = _run(require_report_hook({}, None, {"signal": None}))

    assert result == {}


def test_stop_hook_allows_stop_in_bg_no_output():
    set_in_fork(True)

    result = _run(require_report_hook({}, None, {"signal": None}))

    assert result == {}
    set_in_fork(False)


def test_stop_hook_blocks_stop_in_bg_with_unreported_output():
    ch = InMemoryChannel()
    set_fork_channel(ch)
    set_in_fork(True)

    _run(_ping({"message": "test"}))
    result = _run(require_report_hook({}, None, {"signal": None}))

    assert "report_updates" in result.get("systemMessage", "")
    set_in_fork(False)
```

Note: the exact return shape for "block the stop" needs verification — see step 3.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_agent_tools.py -v -k "bg_output or stop_hook"`
Expected: FAIL — no bg_output_sent, no require_report_hook exist

**Step 3: Implement bg output tracking and stop hook**

In `agent_tools.py`, add contextvar and helper:

```python
_bg_output_sent_var: ContextVar[bool] = ContextVar("_bg_output_sent", default=False)


def bg_output_sent() -> bool:
    return _bg_output_sent_var.get()
```

In `ping_user`, after the `await channel.send(...)` line, add:

```python
    _bg_output_sent_var.set(True)
```

In `discord_embed`, after the `await channel.send(...)` line, add:

```python
    if in_bg_fork():
        _bg_output_sent_var.set(True)
```

In `report_updates`, in the `if in_bg_fork():` branch, add after `_append_update`:

```python
        _bg_output_sent_var.set(False)
```

Add the Stop hook callback:

```python
async def require_report_hook(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Stop hook: prevent bg fork from stopping with unreported output."""
    if not in_bg_fork() or not _bg_output_sent_var.get():
        return {}
    return {
        "systemMessage": (
            "You sent visible output (ping/embed) but haven't called "
            "report_updates. Call it now to bridge your findings to the "
            "main session."
        ),
    }
```

**Important**: The `Stop` hook `continue_` semantics need verification. By default (`continue_: True`, or omitted), the agent should continue running after the hook — which is what we want when blocking the stop. If testing shows that `{}` (empty return) allows the stop to proceed and a non-empty `systemMessage` keeps the agent alive, then this works as-is. If the default actually allows the stop, we may need to add explicit `"continue_": False` to override. Verify during testing by checking whether the systemMessage gets injected and the agent resumes.

**Step 4: Register the hook in Agent.__init__**

In `src/ollim_bot/agent.py`, add import:

```python
from claude_agent_sdk import HookMatcher
from ollim_bot.agent_tools import require_report_hook
```

In `Agent.__init__`, add to `ClaudeAgentOptions`:

```python
            hooks={
                "Stop": [HookMatcher(hooks=[require_report_hook])],
            },
```

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_agent_tools.py -v -k "bg_output or stop_hook"`
Expected: PASS

**Step 6: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests PASS

**Step 7: Commit**

```bash
git add src/ollim_bot/agent_tools.py src/ollim_bot/agent.py tests/test_agent_tools.py
git commit -m "feat: stop hook prevents bg fork exit without report_updates"
```

---

### Task 4: Verify Stop hook behavior end-to-end

This is a manual verification step — run the bot and test with a bg routine/reminder.

1. Trigger a bg fork that uses `ping_user` or `discord_embed`
2. Verify the agent calls `report_updates` before stopping
3. If the stop hook doesn't prevent stopping as expected, adjust the `continue_` return value:
   - If `{}` allows the stop: change the guard return to `{"continue_": False, "systemMessage": "..."}`
   - If that also allows the stop: switch to a PostToolUse hook on ping/embed that injects `additionalContext` reminding the agent to call report_updates (soft nudge fallback)
4. Verify source indicators appear correctly:
   - Bg fork pings show `[bg] ` prefix
   - Bg fork embeds show `bg` footer
   - Interactive fork embeds show `fork` footer
   - Main session pings return error
   - Main session embeds have no footer
