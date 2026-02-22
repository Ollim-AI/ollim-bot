# Reply-to-Fork Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replying to a bg fork message starts an interactive fork that resumes from that bg fork's session, with pending updates prepended.

**Architecture:** Add a message collector (contextvar-based) and a persistent message-to-session mapping in `sessions.py`. The streamer and MCP tools call `track_message()` after sending. `bot.py` checks `message.reference` on every incoming message and either starts a fork-from-reply or prepends the quoted content.

**Tech Stack:** Python, discord.py, contextvars, JSON file persistence

---

### Task 1: Add fork message tracking to `sessions.py`

**Files:**
- Modify: `src/ollim_bot/sessions.py`
- Test: `tests/test_sessions.py`

**Step 1: Write the failing tests**

Add to `tests/test_sessions.py`:

```python
from ollim_bot.sessions import (
    flush_message_collector,
    lookup_fork_session,
    start_message_collector,
    track_message,
)


@pytest.fixture()
def fork_messages(tmp_path, monkeypatch):
    path = tmp_path / "fork_messages.json"
    monkeypatch.setattr(sessions_mod, "FORK_MESSAGES_FILE", path)
    return path


def test_track_message_noop_without_collector(fork_messages):
    track_message(111)

    assert not fork_messages.exists()


def test_collector_roundtrip(fork_messages):
    start_message_collector()
    track_message(100)
    track_message(200)
    flush_message_collector("fork-abc", "parent-xyz")

    assert lookup_fork_session(100) == "fork-abc"
    assert lookup_fork_session(200) == "fork-abc"


def test_lookup_unknown_returns_none(fork_messages):
    assert lookup_fork_session(999) is None


def test_flush_clears_collector(fork_messages):
    start_message_collector()
    track_message(100)
    flush_message_collector("fork-abc", "parent-xyz")

    start_message_collector()
    flush_message_collector("fork-def", "parent-xyz")

    assert lookup_fork_session(100) == "fork-abc"


def test_expired_records_pruned(fork_messages, monkeypatch):
    import time

    old_ts = time.time() - (8 * 24 * 3600)
    fork_messages.write_text(
        json.dumps([
            {
                "message_id": 100,
                "fork_session_id": "old-fork",
                "parent_session_id": "old-parent",
                "ts": old_ts,
            }
        ])
    )

    assert lookup_fork_session(100) is None
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sessions.py -v -k "track_message or collector or lookup or expired_records_pruned"`
Expected: ImportError — functions don't exist yet

**Step 3: Implement fork message tracking in `sessions.py`**

Add to `src/ollim_bot/sessions.py`:

```python
import json
import time
from contextvars import ContextVar
from typing import TypedDict

FORK_MESSAGES_FILE = Path.home() / ".ollim-bot" / "fork_messages.json"
_MAX_AGE = 7 * 24 * 3600  # 7 days

_msg_collector: ContextVar[list[int] | None] = ContextVar("_msg_collector", default=None)


class _ForkMessageRecord(TypedDict):
    message_id: int
    fork_session_id: str
    parent_session_id: str | None
    ts: float


def start_message_collector() -> None:
    """Initialize a contextvar list to collect Discord message IDs during a bg fork."""
    _msg_collector.set([])


def track_message(message_id: int) -> None:
    """Append a Discord message ID to the active collector. No-op if no collector."""
    collector = _msg_collector.get()
    if collector is not None:
        collector.append(message_id)


def flush_message_collector(
    fork_session_id: str, parent_session_id: str | None
) -> None:
    """Write collected message IDs to fork_messages.json and clear the collector."""
    collector = _msg_collector.get()
    _msg_collector.set(None)
    if not collector:
        return
    records = _read_fork_messages()
    ts = time.time()
    for mid in collector:
        records.append(
            _ForkMessageRecord(
                message_id=mid,
                fork_session_id=fork_session_id,
                parent_session_id=parent_session_id,
                ts=ts,
            )
        )
    _write_fork_messages(records)


def lookup_fork_session(message_id: int) -> str | None:
    """Return the fork session ID for a Discord message, or None."""
    for record in _read_fork_messages():
        if record["message_id"] == message_id:
            return record["fork_session_id"]
    return None


def _read_fork_messages() -> list[_ForkMessageRecord]:
    if not FORK_MESSAGES_FILE.exists():
        return []
    data: list[_ForkMessageRecord] = json.loads(FORK_MESSAGES_FILE.read_text())
    cutoff = time.time() - _MAX_AGE
    return [r for r in data if r["ts"] > cutoff]


def _write_fork_messages(records: list[_ForkMessageRecord]) -> None:
    FORK_MESSAGES_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=FORK_MESSAGES_FILE.parent, suffix=".tmp")
    os.write(fd, json.dumps(records).encode())
    os.close(fd)
    os.replace(tmp, FORK_MESSAGES_FILE)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sessions.py -v`
Expected: All pass

**Step 5: Commit**

```bash
git add src/ollim_bot/sessions.py tests/test_sessions.py
git commit -m "feat: add fork message tracking to sessions"
```

---

### Task 2: Call `track_message` from streamer and MCP tools

**Files:**
- Modify: `src/ollim_bot/streamer.py`
- Modify: `src/ollim_bot/agent_tools.py`

**Step 1: Add `track_message` calls to `streamer.py`**

In `stream_to_channel`, after every `channel.send()` that creates or replaces `msg`, call `track_message(msg.id)`:

```python
from ollim_bot.sessions import track_message
```

In the `flush` function, after `msg = await channel.send(chunk[:MAX_MSG_LEN])` (line ~43), add:
```python
            track_message(msg.id)
```

And after `msg = await channel.send(remaining[:MAX_MSG_LEN])` (line ~57, the overflow send), add:
```python
                track_message(msg.id)
```

Also after the final empty-response fallback `await channel.send(...)` (line ~94):
```python
        track_message(msg.id)
```
(Assign the send result to `msg` first.)

**Step 2: Add `track_message` calls to `agent_tools.py`**

In `discord_embed`, capture the message from `channel.send()` (line ~155):
```python
    msg = await channel.send(embed=embed, view=view)
    track_message(msg.id)
```

In `ping_user`, capture the message from `channel.send()` (line ~190):
```python
    msg = await channel.send(f"[bg] {args['message']}")
    track_message(msg.id)
```

Import at top:
```python
from ollim_bot.sessions import track_message
```

**Step 3: Run full tests**

Run: `uv run pytest -v`
Expected: All pass

**Step 4: Commit**

```bash
git add src/ollim_bot/streamer.py src/ollim_bot/agent_tools.py
git commit -m "feat: call track_message from streamer and MCP tools"
```

---

### Task 3: Call collector lifecycle from `run_agent_background`

**Files:**
- Modify: `src/ollim_bot/forks.py`

**Step 1: Add collector calls to `run_agent_background`**

In `forks.py`, import:
```python
from ollim_bot.sessions import (
    flush_message_collector,
    load_session_id,
    log_session_event,
    start_message_collector,
)
```

Remove the existing local import of `load_session_id` and `log_session_event` from inside the function body.

In `run_agent_background`, add `start_message_collector()` after `set_in_fork(True)`, and `flush_message_collector(fork_session_id, main_session_id)` after `log_session_event`:

```python
    set_in_fork(True)
    start_message_collector()

    try:
        client = await agent.create_forked_client()
        try:
            fork_session_id = await agent.run_on_client(client, prompt)
            log_session_event(
                fork_session_id,
                "bg_fork",
                parent_session_id=main_session_id,
            )
            flush_message_collector(fork_session_id, main_session_id)
        finally:
            await client.disconnect()
    finally:
        set_in_fork(False)
```

**Step 2: Run full tests**

Run: `uv run pytest -v`
Expected: All pass

**Step 3: Commit**

```bash
git add src/ollim_bot/forks.py
git commit -m "feat: wire message collector into run_agent_background"
```

---

### Task 4: Add `resume_session_id` parameter to `agent.py`

**Files:**
- Modify: `src/ollim_bot/agent.py`

**Step 1: Add `resume_session_id` parameter to `enter_interactive_fork`**

```python
    async def enter_interactive_fork(
        self, *, idle_timeout: int = 10, resume_session_id: str | None = None
    ) -> None:
        """Create an interactive fork client and switch routing to it."""
        self._fork_client = await self.create_forked_client(
            session_id=resume_session_id
        )
        self._fork_session_id = None
        set_interactive_fork(True, idle_timeout=idle_timeout)
        touch_activity()
```

**Step 2: Add `session_id` parameter to `create_forked_client`**

```python
    async def create_forked_client(
        self, session_id: str | None = None
    ) -> ClaudeSDKClient:
        """Create a disposable client that forks from a given or current session."""
        sid = session_id or load_session_id()
        if sid:
            opts = replace(self.options, resume=sid, fork_session=True)
        else:
            opts = self.options
        client = ClaudeSDKClient(opts)
        await client.connect()
        return client
```

**Step 3: Run full tests**

Run: `uv run pytest -v`
Expected: All pass

**Step 4: Commit**

```bash
git add src/ollim_bot/agent.py
git commit -m "feat: accept resume_session_id in enter_interactive_fork"
```

---

### Task 5: Add `data_dir` fixture monkeypatching for `FORK_MESSAGES_FILE`

**Files:**
- Modify: `tests/conftest.py`

**Step 1: Add monkeypatch for FORK_MESSAGES_FILE**

In the `data_dir` fixture, after the existing `sessions_mod` monkeypatches:

```python
    monkeypatch.setattr(
        sessions_mod, "FORK_MESSAGES_FILE", tmp_path / "fork_messages.json"
    )
```

**Step 2: Run full tests**

Run: `uv run pytest -v`
Expected: All pass

**Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test: redirect FORK_MESSAGES_FILE in data_dir fixture"
```

---

### Task 6: Handle reply-to-fork in `bot.py`

**Files:**
- Modify: `src/ollim_bot/bot.py`

**Step 1: Add reply detection in `on_message`**

Import at top:
```python
from ollim_bot.sessions import lookup_fork_session
```

In `on_message`, after building `content` and `images` but before `add_reaction`, add reply handling:

```python
        # --- Reply handling ---
        ref = message.reference
        fork_session_id: str | None = None
        if ref and ref.message_id:
            fork_session_id = lookup_fork_session(ref.message_id)
            if fork_session_id and agent.in_fork:
                # Can't nest forks; treat as normal message
                fork_session_id = None
            if not fork_session_id and ref.message_id:
                # Not a fork reply — prepend quoted content for context
                try:
                    replied = ref.resolved or await message.channel.fetch_message(
                        ref.message_id
                    )
                    if replied and replied.content:
                        content = f"> {replied.content}\n\n{content}"
                except discord.NotFound:
                    pass
```

Then modify the `async with agent.lock()` block to handle fork-from-reply:

```python
        async with agent.lock():
            if fork_session_id:
                await agent.enter_interactive_fork(
                    resume_session_id=fork_session_id
                )
                await _send_fork_enter(message.channel, None)
            await _dispatch(message.channel, content, images=images or None)
            if in_interactive_fork():
                touch_activity()
                clear_prompted()
            await _check_fork_transitions(message.channel)
```

**Step 2: Run full tests**

Run: `uv run pytest -v`
Expected: All pass

**Step 3: Commit**

```bash
git add src/ollim_bot/bot.py
git commit -m "feat: start interactive fork when replying to bg fork message"
```

---

### Task 7: Update `CLAUDE.md` and memory

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Add reply-to-fork section to CLAUDE.md**

Under "## Interactive forks", add:

```markdown
## Reply-to-fork
- Replying to a bg fork message starts an interactive fork that resumes from that bg fork's session
- `sessions.py` tracks Discord message IDs → fork session IDs via `~/.ollim-bot/fork_messages.json` (7-day TTL)
- Collector API: `start_message_collector()` / `track_message(msg_id)` / `flush_message_collector()` — contextvar-scoped
- `streamer.py` and MCP tools (`ping_user`, `discord_embed`) call `track_message()` after sending
- `run_agent_background` calls `start_message_collector()` before and `flush_message_collector()` after
- `enter_interactive_fork(resume_session_id=)` overrides which session to fork from
- Replying to a non-fork bot message prepends the quoted content to the prompt
```

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add reply-to-fork section to CLAUDE.md"
```
