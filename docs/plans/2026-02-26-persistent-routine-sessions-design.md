# Persistent Routine Sessions Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let routines opt into `session: persistent` so they accumulate context across fires, with agent-driven compaction.

**Architecture:** Standalone sessions per routine, stored as plain string files in `~/.ollim-bot/state/routine_sessions/<routine-id>`. The agent triggers compaction via a `compact_session` MCP tool that defers execution to after the agent's run completes (MCP tools can't call `client.query()` mid-turn). Existing `update_main_session` mechanism handles reporting.

**Tech Stack:** Claude Agent SDK, APScheduler, asyncio contextvars

**Design doc:** See git history for the approved design (replaced by this plan).

---

### Task 1: Routine Dataclass — `session` Field

**Files:**
- Modify: `src/ollim_bot/scheduling/routines.py:15-62`
- Test: `tests/test_routines.py`

**Step 1: Write failing tests**

```python
# In tests/test_routines.py, add at the end:

# --- Session mode ---


def test_routine_new_defaults_session_none():
    routine = Routine.new(message="test", cron="0 9 * * *")

    assert routine.session is None


def test_routine_new_with_session_persistent():
    routine = Routine.new(
        message="track",
        cron="0 9 * * *",
        background=True,
        session="persistent",
    )

    assert routine.session == "persistent"


def test_routine_session_requires_background():
    import pytest

    with pytest.raises(ValueError, match="background"):
        Routine.new(
            message="bad",
            cron="0 9 * * *",
            session="persistent",
        )


def test_routine_session_mutex_with_isolated():
    import pytest

    with pytest.raises(ValueError, match="isolated"):
        Routine.new(
            message="bad",
            cron="0 9 * * *",
            background=True,
            isolated=True,
            session="persistent",
        )


def test_routine_session_roundtrip(data_dir):
    routine = Routine.new(
        message="track markets",
        cron="0 9 * * 1-5",
        background=True,
        session="persistent",
    )
    append_routine(routine)

    loaded = list_routines()[0]

    assert loaded.session == "persistent"


def test_routine_session_none_omitted_from_frontmatter(data_dir):
    routine = Routine.new(message="defaults", cron="0 9 * * *")
    append_routine(routine)

    loaded = list_routines()[0]

    assert loaded.session is None
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_routines.py -v -k "session"`
Expected: FAIL — `session` field doesn't exist

**Step 3: Implement**

In `src/ollim_bot/scheduling/routines.py`, add `session` field to `Routine` dataclass after `disallowed_tools`:

```python
    session: str | None = None
```

Add validation in `__post_init__` (append to existing method):

```python
        if self.session is not None:
            if self.session != "persistent":
                raise ValueError(f"Invalid session mode: {self.session!r} (must be 'persistent')")
            if not self.background:
                raise ValueError("session: persistent requires background: true")
            if self.isolated:
                raise ValueError("session: persistent and isolated: true are mutually exclusive")
```

Add `session` parameter to `Routine.new()`:

```python
    @staticmethod
    def new(
        ...,
        disallowed_tools: list[str] | None = None,
        session: str | None = None,
    ) -> "Routine":
        return Routine(
            ...,
            disallowed_tools=disallowed_tools,
            session=session,
        )
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_routines.py -v`
Expected: ALL PASS

**Step 5: Commit**

```
feat: add session field to Routine dataclass
```

---

### Task 2: Persistent Session File I/O

**Files:**
- Modify: `src/ollim_bot/sessions.py:18-26` (SessionEventType)
- Modify: `src/ollim_bot/sessions.py` (add functions at end)
- Modify: `tests/conftest.py:31` (add monkeypatch)
- Test: `tests/test_sessions.py`

**Step 1: Write failing tests**

```python
# In tests/test_sessions.py, add at the end:

from ollim_bot.sessions import (
    delete_persistent_session,
    load_persistent_session,
    save_persistent_session,
)


# --- Persistent session file I/O ---


def test_load_persistent_session_missing(data_dir):
    assert load_persistent_session("nonexistent") is None


def test_save_and_load_persistent_session(data_dir):
    save_persistent_session("routine-abc", "session-123")

    assert load_persistent_session("routine-abc") == "session-123"


def test_save_persistent_session_overwrites(data_dir):
    save_persistent_session("routine-abc", "session-old")
    save_persistent_session("routine-abc", "session-new")

    assert load_persistent_session("routine-abc") == "session-new"


def test_delete_persistent_session(data_dir):
    save_persistent_session("routine-abc", "session-123")

    assert delete_persistent_session("routine-abc") is True
    assert load_persistent_session("routine-abc") is None


def test_delete_persistent_session_missing(data_dir):
    assert delete_persistent_session("nonexistent") is False
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sessions.py -v -k "persistent_session"`
Expected: FAIL — functions don't exist

**Step 3: Implement**

In `src/ollim_bot/sessions.py`, add `"persistent_bg"` to `SessionEventType`:

```python
SessionEventType = Literal[
    "created",
    "compacted",
    "swapped",
    "cleared",
    "interactive_fork",
    "bg_fork",
    "isolated_bg",
    "persistent_bg",
]
```

Add at end of `sessions.py`:

```python
# ---------------------------------------------------------------------------
# Persistent routine sessions — one session ID file per routine
# ---------------------------------------------------------------------------

ROUTINE_SESSIONS_DIR = STATE_DIR / "routine_sessions"


def load_persistent_session(routine_id: str) -> str | None:
    path = ROUTINE_SESSIONS_DIR / routine_id
    if not path.exists():
        return None
    text = path.read_text().strip()
    return text or None


def save_persistent_session(routine_id: str, session_id: str) -> None:
    ROUTINE_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=ROUTINE_SESSIONS_DIR, suffix=".tmp")
    try:
        os.write(fd, session_id.encode())
    finally:
        os.close(fd)
    os.replace(tmp, ROUTINE_SESSIONS_DIR / routine_id)


def delete_persistent_session(routine_id: str) -> bool:
    path = ROUTINE_SESSIONS_DIR / routine_id
    if path.exists():
        path.unlink()
        return True
    return False
```

In `tests/conftest.py`, add monkeypatch after line 31 (the FORK_MESSAGES_FILE line):

```python
    monkeypatch.setattr(sessions_mod, "ROUTINE_SESSIONS_DIR", state_dir / "routine_sessions")
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_sessions.py -v`
Expected: ALL PASS

**Step 5: Commit**

```
feat: persistent session file I/O and "persistent_bg" event type
```

---

### Task 3: Contextvars for Persistent Sessions

**Files:**
- Modify: `src/ollim_bot/forks.py` (add after bg ping counter section, ~line 165)
- Test: `tests/test_forks.py`

**Step 1: Write failing tests**

```python
# In tests/test_forks.py, add at the end:

from ollim_bot.forks import (
    get_persistent_routine_id,
    init_compact_request,
    is_persistent_active,
    pop_compact_request,
    set_compact_request,
    set_persistent_routine_id,
)


# --- Persistent session contextvars ---


def test_persistent_routine_id_default_none():
    assert get_persistent_routine_id() is None


def test_set_and_get_persistent_routine_id():
    set_persistent_routine_id("routine-abc")

    assert get_persistent_routine_id() == "routine-abc"

    set_persistent_routine_id(None)

    assert get_persistent_routine_id() is None


def test_active_persistent_guard():
    assert is_persistent_active("routine-abc") is False


def test_compact_request_default_none():
    init_compact_request()

    assert pop_compact_request() is None


def test_set_and_pop_compact_request():
    init_compact_request()
    set_compact_request("preserve key observations")

    assert pop_compact_request() == "preserve key observations"
    assert pop_compact_request() is None
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_forks.py -v -k "persistent"`
Expected: FAIL — functions don't exist

**Step 3: Implement**

In `src/ollim_bot/forks.py`, add after the bg ping counter section (after line 164):

```python
# ---------------------------------------------------------------------------
# Persistent session state — routine ID, client ref, compact request, skip guard
# ---------------------------------------------------------------------------

_persistent_routine_id_var: ContextVar[str | None] = ContextVar(
    "_persistent_routine_id", default=None
)


def set_persistent_routine_id(routine_id: str | None) -> None:
    _persistent_routine_id_var.set(routine_id)


def get_persistent_routine_id() -> str | None:
    return _persistent_routine_id_var.get()


# Mutable container so mutations propagate across SDK's anyio task group.
_compact_request_var: ContextVar[list[str | None] | None] = ContextVar(
    "_compact_request", default=None
)


def init_compact_request() -> None:
    """Call before client connect() so all child tasks share the mutable ref."""
    _compact_request_var.set([None])


def set_compact_request(instructions: str) -> None:
    req = _compact_request_var.get()
    if req is not None:
        req[0] = instructions


def pop_compact_request() -> str | None:
    req = _compact_request_var.get()
    if req is not None and req[0] is not None:
        instructions = req[0]
        req[0] = None
        return instructions
    return None


# Skip guard — prevents same persistent routine from running concurrently.
# Module-level set (not contextvar) because it tracks across tasks.
_active_persistent: set[str] = set()


def is_persistent_active(routine_id: str) -> bool:
    return routine_id in _active_persistent


def mark_persistent_active(routine_id: str) -> None:
    _active_persistent.add(routine_id)


def mark_persistent_inactive(routine_id: str) -> None:
    _active_persistent.discard(routine_id)
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_forks.py -v`
Expected: ALL PASS

**Step 5: Commit**

```
feat: contextvars and skip guard for persistent routine sessions
```

---

### Task 4: `create_persistent_client` Method

**Files:**
- Modify: `src/ollim_bot/agent.py:367-384` (add after `create_isolated_client`)
- Modify: `src/ollim_bot/agent.py:153-175` (add compact_session to allowed_tools)

**Step 1: No separate test — tested through Task 6 integration tests**

The method follows the same pattern as `create_isolated_client` (which also has no direct unit test). It will be tested through `run_agent_background` tests.

**Step 2: Implement**

In `src/ollim_bot/agent.py`, add after `create_isolated_client` (after line 384):

```python
    async def create_persistent_client(
        self,
        session_id: str | None = None,
        *,
        model: str | None = None,
        thinking: bool = True,
        allowed_tools: list[str] | None = None,
        disallowed_tools: list[str] | None = None,
    ) -> ClaudeSDKClient:
        """Create a client for persistent routine sessions.

        Resumes from session_id if provided (continuing the lineage),
        else starts fresh. No fork_session — persistent sessions are
        standalone lineages, not branches of the main session.
        """
        opts = self.options
        if session_id:
            opts = replace(opts, resume=session_id)
        if model:
            opts = replace(opts, model=model)
        thinking_tokens = 10000 if thinking else None
        opts = replace(opts, max_thinking_tokens=thinking_tokens)
        opts = _apply_tool_restrictions(opts, allowed_tools, disallowed_tools)
        client = ClaudeSDKClient(opts)
        await client.connect()
        return client
```

Add `mcp__discord__compact_session` to `allowed_tools` in `Agent.__init__` (after `mcp__discord__exit_fork`):

```python
                "mcp__discord__compact_session",
```

**Step 3: Commit**

```
feat: create_persistent_client method and compact_session tool allowlist
```

---

### Task 5: `compact_session` MCP Tool

**Files:**
- Modify: `src/ollim_bot/agent_tools.py` (add tool before `require_report_hook`)
- Modify: `src/ollim_bot/agent_tools.py:544-555` (register in `agent_server`)
- Test: `tests/test_agent_tools.py`

The tool uses **deferred compaction**: it stores the compact instructions in a contextvar, and `run_agent_background` executes the actual compaction after the agent's run completes. This is necessary because MCP tools run inside the SDK's `receive_response()` loop and cannot call `client.query()` mid-turn.

**Step 1: Write failing tests**

```python
# In tests/test_agent_tools.py, add at the end:

from ollim_bot.forks import (
    get_persistent_routine_id,
    init_compact_request,
    pop_compact_request,
    set_persistent_routine_id,
)

# Unwrap the tool handler
_compact = compact_session.handler


# --- compact_session ---


def test_compact_session_blocked_outside_persistent():
    set_persistent_routine_id(None)

    result = _run(_compact({"instructions": "preserve everything"}))

    assert "Error" in result["content"][0]["text"]
    assert "persistent routine" in result["content"][0]["text"]


def test_compact_session_sets_request():
    set_persistent_routine_id("routine-abc")
    init_compact_request()

    result = _run(_compact({"instructions": "preserve price levels"}))

    assert "scheduled" in result["content"][0]["text"].lower()
    assert pop_compact_request() == "preserve price levels"
    set_persistent_routine_id(None)
```

Also add to the imports at the top of the file:

```python
from ollim_bot.agent_tools import (
    ...,
    compact_session,
)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_agent_tools.py -v -k "compact_session"`
Expected: FAIL — `compact_session` doesn't exist

**Step 3: Implement**

In `src/ollim_bot/agent_tools.py`, add imports at top:

```python
from ollim_bot.forks import (
    ...,
    get_persistent_routine_id,
    set_compact_request,
)
```

Add the tool before `require_report_hook` (before line 516):

```python
@tool(
    "compact_session",
    "Compact the current persistent session's context. Only available in "
    "persistent routine sessions. Call when context is getting large, with "
    "instructions for what to preserve and what to discard. Compaction runs "
    "after you finish responding.",
    {
        "type": "object",
        "properties": {
            "instructions": {
                "type": "string",
                "description": "What to preserve and what to discard during compaction",
            },
        },
        "required": ["instructions"],
    },
)
async def compact_session(args: dict[str, Any]) -> dict[str, Any]:
    routine_id = get_persistent_routine_id()
    if routine_id is None:
        return {
            "content": [
                {
                    "type": "text",
                    "text": "Error: compact_session is only available in persistent routine sessions",
                }
            ]
        }
    set_compact_request(args["instructions"])
    return {
        "content": [
            {
                "type": "text",
                "text": "Compaction scheduled — will run after you finish responding.",
            }
        ]
    }
```

Register in `agent_server` (add to tools list):

```python
agent_server = create_sdk_mcp_server(
    "discord",
    tools=[
        discord_embed,
        ping_user,
        follow_up_chain,
        save_context,
        report_updates,
        enter_fork,
        exit_fork,
        compact_session,
    ],
)
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_agent_tools.py -v -k "compact_session"`
Expected: ALL PASS

**Step 5: Commit**

```
feat: compact_session MCP tool (deferred compaction)
```

---

### Task 6: `run_agent_background` — Persistent Session Integration

**Files:**
- Modify: `src/ollim_bot/forks.py:361-448` (`run_agent_background`)
- Test: `tests/test_forks.py`

**Step 1: Write failing tests**

```python
# In tests/test_forks.py, add at the end:

from ollim_bot.sessions import (
    load_persistent_session,
    save_persistent_session,
)


# --- Persistent session in run_agent_background ---


def test_bg_fork_persistent_saves_session_id(monkeypatch, data_dir):
    """Persistent mode saves returned session ID to routine session file."""
    owner = AsyncMock()
    owner.create_dm = AsyncMock(return_value=AsyncMock())

    agent = AsyncMock()
    agent.lock = MagicMock(return_value=asyncio.Lock())

    client = AsyncMock()
    agent.create_persistent_client = AsyncMock(return_value=client)
    agent.run_on_client = AsyncMock(return_value="persistent-session-123")

    _run(
        run_agent_background(
            owner,
            agent,
            "[routine-bg:test] do stuff",
            persistent_routine_id="routine-abc",
        )
    )

    assert load_persistent_session("routine-abc") == "persistent-session-123"
    agent.create_persistent_client.assert_awaited_once()
    client.disconnect.assert_awaited()


def test_bg_fork_persistent_resumes_existing_session(monkeypatch, data_dir):
    """Persistent mode resumes from stored session ID."""
    save_persistent_session("routine-abc", "existing-session-456")

    owner = AsyncMock()
    owner.create_dm = AsyncMock(return_value=AsyncMock())

    agent = AsyncMock()
    agent.lock = MagicMock(return_value=asyncio.Lock())

    client = AsyncMock()
    agent.create_persistent_client = AsyncMock(return_value=client)
    agent.run_on_client = AsyncMock(return_value="new-session-789")

    _run(
        run_agent_background(
            owner,
            agent,
            "[routine-bg:test] do stuff",
            persistent_routine_id="routine-abc",
            persistent_session_id="existing-session-456",
        )
    )

    # Should pass existing session to create_persistent_client
    call_kwargs = agent.create_persistent_client.call_args
    assert call_kwargs[0][0] == "existing-session-456"
    # Should save new session ID
    assert load_persistent_session("routine-abc") == "new-session-789"


def test_bg_fork_persistent_skip_guard(monkeypatch, data_dir):
    """Second fire of same persistent routine is skipped."""
    from ollim_bot.forks import mark_persistent_active, mark_persistent_inactive

    mark_persistent_active("routine-abc")

    owner = AsyncMock()
    owner.create_dm = AsyncMock(return_value=AsyncMock())

    agent = AsyncMock()
    agent.lock = MagicMock(return_value=asyncio.Lock())

    _run(
        run_agent_background(
            owner,
            agent,
            "[routine-bg:test] do stuff",
            persistent_routine_id="routine-abc",
        )
    )

    # Should not have created any client
    agent.create_persistent_client.assert_not_awaited()
    agent.create_forked_client.assert_not_awaited()
    agent.create_isolated_client.assert_not_awaited()

    mark_persistent_inactive("routine-abc")


def test_bg_fork_persistent_deferred_compact(monkeypatch, data_dir):
    """When compact_session was called, compaction runs after agent finishes."""
    from ollim_bot.forks import init_compact_request, set_compact_request

    owner = AsyncMock()
    owner.create_dm = AsyncMock(return_value=AsyncMock())

    agent = AsyncMock()
    agent.lock = MagicMock(return_value=asyncio.Lock())

    client = AsyncMock()
    agent.create_persistent_client = AsyncMock(return_value=client)

    async def fake_run(c, prompt, **kwargs):
        # Simulate agent calling compact_session tool mid-run
        set_compact_request("preserve price levels")
        return "pre-compact-session"

    agent.run_on_client = AsyncMock(side_effect=fake_run)

    # Mock the compact response
    from claude_agent_sdk import ResultMessage

    async def fake_receive():
        yield ResultMessage(
            session_id="post-compact-session",
            result="Compacted.",
            num_turns=5,
            duration_ms=1000,
            duration_api_ms=800,
            is_error=False,
            total_cost_usd=0.0,
        )

    client.receive_response = fake_receive

    _run(
        run_agent_background(
            owner,
            agent,
            "[routine-bg:test] do stuff",
            persistent_routine_id="routine-abc",
        )
    )

    # Compact should have been called on the client
    client.query.assert_awaited_with("/compact preserve price levels")
    # Session ID should be the post-compact one
    assert load_persistent_session("routine-abc") == "post-compact-session"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_forks.py -v -k "persistent"`
Expected: FAIL — `persistent_routine_id` parameter doesn't exist

**Step 3: Implement**

In `src/ollim_bot/forks.py`, modify `run_agent_background` signature and body.

Add imports at top:

```python
from claude_agent_sdk import ResultMessage
```

Update the function signature (add new params):

```python
async def run_agent_background(
    owner: discord.User,
    agent: Agent,
    prompt: str,
    *,
    model: str | None = None,
    thinking: bool = True,
    isolated: bool = False,
    bg_config: BgForkConfig | None = None,
    persistent_session_id: str | None = None,
    persistent_routine_id: str | None = None,
) -> None:
```

Add skip guard and persistent setup after `start_message_collector()`:

```python
    if persistent_routine_id:
        if is_persistent_active(persistent_routine_id):
            log.warning(
                "Persistent routine %s still running, skipping", persistent_routine_id
            )
            cancel_message_collector()
            set_in_fork(False)
            set_busy(False)
            return
        mark_persistent_active(persistent_routine_id)
        set_persistent_routine_id(persistent_routine_id)
        init_compact_request()
```

Replace the client creation block with three-way branch:

```python
            if persistent_routine_id:
                _COMPACT_TOOL = "mcp__discord__compact_session"
                if allowed and _COMPACT_TOOL not in allowed:
                    allowed = [*allowed, _COMPACT_TOOL]
                client = await agent.create_persistent_client(
                    persistent_session_id,
                    model=model,
                    thinking=thinking,
                    allowed_tools=allowed,
                    disallowed_tools=blocked,
                )
            elif isolated:
                client = await agent.create_isolated_client(...)
            else:
                client = await agent.create_forked_client(...)
```

After `run_on_client`, add deferred compact + session save:

```python
                # Deferred compaction (compact_session tool sets the request)
                compact_instructions = pop_compact_request()
                if compact_instructions and persistent_routine_id:
                    await client.query(f"/compact {compact_instructions}")
                    async for msg in client.receive_response():
                        if isinstance(msg, ResultMessage):
                            fork_session_id = msg.session_id

                # Save persistent session ID
                if persistent_routine_id:
                    from ollim_bot.sessions import save_persistent_session

                    save_persistent_session(persistent_routine_id, fork_session_id)
```

In the `finally` block, add persistent cleanup:

```python
        if persistent_routine_id:
            mark_persistent_inactive(persistent_routine_id)
            set_persistent_routine_id(None)
```

Update `log_session_event` call to use `"persistent_bg"` when persistent:

```python
                event_type = (
                    "persistent_bg" if persistent_routine_id
                    else "isolated_bg" if isolated
                    else "bg_fork"
                )
                log_session_event(
                    fork_session_id,
                    event_type,
                    parent_session_id=None if (isolated or persistent_routine_id) else main_session_id,
                )
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_forks.py -v`
Expected: ALL PASS

**Step 5: Commit**

```
feat: persistent session support in run_agent_background
```

---

### Task 7: Preamble + Scheduler Integration

**Files:**
- Modify: `src/ollim_bot/scheduling/preamble.py:197-326` (`build_bg_preamble`)
- Modify: `src/ollim_bot/scheduling/scheduler.py:88-138` (`_fire` in `_register_routine`)
- Modify: `src/ollim_bot/scheduling/scheduler.py:230-249` (`sync_all` cleanup)
- Test: `tests/test_scheduler_prompts.py`

**Step 1: Write failing tests**

```python
# In tests/test_scheduler_prompts.py, add:

from ollim_bot.scheduling.preamble import build_bg_preamble


def test_bg_preamble_persistent_session_section():
    preamble = build_bg_preamble([], persistent=True)

    assert "persistent" in preamble.lower()
    assert "compact_session" in preamble


def test_bg_preamble_no_persistent_section_by_default():
    preamble = build_bg_preamble([])

    assert "compact_session" not in preamble
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_scheduler_prompts.py -v -k "persistent"`
Expected: FAIL — `persistent` parameter doesn't exist

**Step 3: Implement preamble**

In `src/ollim_bot/scheduling/preamble.py`, add `persistent` parameter to `build_bg_preamble`:

```python
def build_bg_preamble(
    schedule: list[ScheduleEntry],
    *,
    busy: bool = False,
    bg_config: BgForkConfig | None = None,
    persistent: bool = False,
) -> str:
```

Add persistent section at the start of the returned string (before `ping_section`):

```python
    persistent_section = (
        "SESSION: Persistent — your context carries across fires. "
        "You have a `compact_session` tool to compress context when it grows large.\n\n"
        if persistent
        else ""
    )

    return f"{persistent_section}{ping_section}{update_section}..."
```

**Step 4: Implement scheduler**

In `src/ollim_bot/scheduling/scheduler.py`, modify `_fire()` inside `_register_routine`:

Add import:
```python
from ollim_bot.sessions import delete_persistent_session, load_persistent_session
```

In `_fire()`, before calling `run_agent_background`:

```python
        persistent_session_id = None
        persistent_routine_id = None
        if routine.session == "persistent":
            persistent_routine_id = routine.id
            persistent_session_id = load_persistent_session(routine.id)
```

Pass to `build_routine_prompt` and `run_agent_background`:

```python
        prompt = build_routine_prompt(
            routine,
            ...,
            persistent=routine.session == "persistent",
        )
        ...
        await run_agent_background(
            ...,
            persistent_session_id=persistent_session_id,
            persistent_routine_id=persistent_routine_id,
        )
```

Update `build_routine_prompt` in `preamble.py` to accept and pass `persistent`:

```python
def build_routine_prompt(
    routine: Routine,
    *,
    reminders: list[Reminder],
    routines: list[Routine],
    busy: bool = False,
    bg_config: BgForkConfig | None = None,
    persistent: bool = False,
) -> str:
    if routine.background:
        schedule = build_upcoming_schedule(routines, reminders, current_id=routine.id)
        preamble = build_bg_preamble(schedule, busy=busy, bg_config=bg_config, persistent=persistent)
        return f"[routine-bg:{routine.id}] {preamble}{routine.message}"
    return f"[routine:{routine.id}] {routine.message}"
```

In `sync_all()`, add session file cleanup when a routine is removed:

```python
        for stale_id in _registered_routines - current_routine_ids:
            job = scheduler.get_job(f"routine_{stale_id}")
            if job:
                job.remove()
            _registered_routines.discard(stale_id)
            delete_persistent_session(stale_id)  # no-op if not persistent
```

**Step 5: Run all tests**

Run: `uv run pytest -v`
Expected: ALL PASS

**Step 6: Commit**

```
feat: persistent session preamble and scheduler integration
```

---

### Task 8: Full Integration Verification

**Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: ALL PASS

**Step 2: Verify no file size regressions**

Run: `wc -l src/ollim_bot/forks.py src/ollim_bot/agent_tools.py src/ollim_bot/agent.py`

Note current sizes. If any exceed ~500 lines, flag for future split (not in scope).

**Step 3: Update feature brainstorm**

Mark "Persistent Routine Sessions" as implemented in `docs/feature-brainstorm.md`.

**Step 4: Final commit**

```
docs: mark persistent routine sessions as implemented
```
