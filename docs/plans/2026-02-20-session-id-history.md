# Session ID History Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Track all session lifecycle events in an append-only JSONL log so session IDs are never lost.

**Architecture:** Add `SessionEvent` dataclass and `log_session_event()` to `sessions.py`. Hook into `save_session_id()` for created/compacted detection, `swap_client()` and `clear()` in `agent.py` for swapped/cleared, `stream_chat()` for interactive fork ID capture, and `run_agent_background()` in `forks.py` for bg fork logging. Uses existing `storage.append_jsonl()` for writes.

**Tech Stack:** Python dataclasses, `storage.append_jsonl()`, `Literal` types

**Design doc:** `docs/plans/2026-02-20-session-id-history-design.md`

**@python-principles** applies to all code in this plan.

---

### Task 1: SessionEvent dataclass and log_session_event()

**Files:**
- Modify: `src/ollim_bot/sessions.py`
- Test: `tests/test_sessions.py` (create)

**Step 1: Write the failing tests**

Create `tests/test_sessions.py`. Tests use `tmp_path` and `monkeypatch` to redirect
file paths (matching `conftest.py` pattern from `test_storage.py`).

```python
"""Tests for sessions.py — session persistence and history logging."""

import json

import ollim_bot.sessions as sessions_mod
from ollim_bot.sessions import (
    HISTORY_FILE,
    SessionEvent,
    log_session_event,
)


def test_session_event_is_frozen():
    event = SessionEvent(session_id="abc", event="created", timestamp="2026-01-01T00:00:00")

    try:
        event.session_id = "xyz"
        assert False, "Should have raised FrozenInstanceError"
    except AttributeError:
        pass


def test_log_session_event_creates_file(tmp_path, monkeypatch):
    history = tmp_path / "session_history.jsonl"
    monkeypatch.setattr(sessions_mod, "HISTORY_FILE", history)

    log_session_event("abc123", "created")

    lines = history.read_text().strip().splitlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["session_id"] == "abc123"
    assert data["event"] == "created"
    assert data["parent_session_id"] is None
    assert "timestamp" in data


def test_log_session_event_with_parent(tmp_path, monkeypatch):
    history = tmp_path / "session_history.jsonl"
    monkeypatch.setattr(sessions_mod, "HISTORY_FILE", history)

    log_session_event("new-id", "compacted", parent_session_id="old-id")

    data = json.loads(history.read_text().strip())
    assert data["session_id"] == "new-id"
    assert data["event"] == "compacted"
    assert data["parent_session_id"] == "old-id"


def test_log_session_event_appends(tmp_path, monkeypatch):
    history = tmp_path / "session_history.jsonl"
    monkeypatch.setattr(sessions_mod, "HISTORY_FILE", history)

    log_session_event("a", "created")
    log_session_event("b", "compacted", parent_session_id="a")

    lines = history.read_text().strip().splitlines()
    assert len(lines) == 2
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sessions.py -v`
Expected: FAIL — `HISTORY_FILE`, `SessionEvent`, `log_session_event` don't exist

**Step 3: Write minimal implementation**

Add to `src/ollim_bot/sessions.py`:

```python
"""Persist Agent SDK session ID so conversations survive bot restarts."""

import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from ollim_bot.storage import append_jsonl

SESSIONS_FILE = Path.home() / ".ollim-bot" / "sessions.json"
HISTORY_FILE = Path.home() / ".ollim-bot" / "session_history.jsonl"

SessionEventType = Literal[
    "created",
    "compacted",
    "swapped",
    "cleared",
    "interactive_fork",
    "bg_fork",
]

_TZ = ZoneInfo("America/Los_Angeles")


@dataclass(frozen=True)
class SessionEvent:
    session_id: str
    event: SessionEventType
    timestamp: str
    parent_session_id: str | None = None


def log_session_event(
    session_id: str,
    event: SessionEventType,
    *,
    parent_session_id: str | None = None,
) -> None:
    ts = datetime.now(_TZ).isoformat()
    entry = SessionEvent(
        session_id=session_id,
        event=event,
        timestamp=ts,
        parent_session_id=parent_session_id,
    )
    append_jsonl(HISTORY_FILE, entry, f"session {event}: {session_id[:8]}")


def load_session_id() -> str | None:
    if not SESSIONS_FILE.exists():
        return None
    text = SESSIONS_FILE.read_text().strip()
    if not text or text.startswith("{"):
        return None
    return text


def save_session_id(session_id: str) -> None:
    """Atomic write -- safe to call mid-stream without corrupting concurrent reads."""
    SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=SESSIONS_FILE.parent, suffix=".tmp")
    os.write(fd, session_id.encode())
    os.close(fd)
    os.replace(tmp, SESSIONS_FILE)


def delete_session_id() -> None:
    SESSIONS_FILE.unlink(missing_ok=True)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sessions.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/ollim_bot/sessions.py tests/test_sessions.py
git commit -m "feat: add SessionEvent dataclass and log_session_event()"
```

---

### Task 2: Auto-detect created and compacted in save_session_id()

**Files:**
- Modify: `src/ollim_bot/sessions.py`
- Test: `tests/test_sessions.py`

**Step 1: Write the failing tests**

Append to `tests/test_sessions.py`:

```python
from ollim_bot.sessions import (
    save_session_id,
    delete_session_id,
    load_session_id,
    set_swap_in_progress,
)


def test_save_session_id_logs_created_on_first_save(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions_mod, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(sessions_mod, "HISTORY_FILE", tmp_path / "history.jsonl")

    save_session_id("first-session")

    lines = (tmp_path / "history.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["event"] == "created"
    assert data["session_id"] == "first-session"
    assert data["parent_session_id"] is None


def test_save_session_id_no_event_on_same_id(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions_mod, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(sessions_mod, "HISTORY_FILE", tmp_path / "history.jsonl")
    (tmp_path / "sessions.json").write_text("same-id")

    save_session_id("same-id")

    assert not (tmp_path / "history.jsonl").exists()


def test_save_session_id_logs_compacted_on_id_change(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions_mod, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(sessions_mod, "HISTORY_FILE", tmp_path / "history.jsonl")
    (tmp_path / "sessions.json").write_text("old-id")

    save_session_id("new-id")

    lines = (tmp_path / "history.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["event"] == "compacted"
    assert data["session_id"] == "new-id"
    assert data["parent_session_id"] == "old-id"


def test_save_session_id_skips_log_during_swap(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions_mod, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(sessions_mod, "HISTORY_FILE", tmp_path / "history.jsonl")
    (tmp_path / "sessions.json").write_text("old-id")

    set_swap_in_progress(True)
    try:
        save_session_id("new-id")
    finally:
        set_swap_in_progress(False)

    assert not (tmp_path / "history.jsonl").exists()


def test_delete_then_save_logs_created(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions_mod, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(sessions_mod, "HISTORY_FILE", tmp_path / "history.jsonl")
    (tmp_path / "sessions.json").write_text("old-id")
    delete_session_id()

    save_session_id("brand-new")

    lines = (tmp_path / "history.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["event"] == "created"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sessions.py -v -k "save_session_id or delete_then"`
Expected: FAIL — `set_swap_in_progress` doesn't exist, `save_session_id` doesn't log

**Step 3: Implement detection logic in save_session_id()**

Update `save_session_id()` and add `set_swap_in_progress()` in `sessions.py`:

```python
_swap_in_progress: bool = False


def set_swap_in_progress(active: bool) -> None:
    global _swap_in_progress
    _swap_in_progress = active


def save_session_id(session_id: str) -> None:
    """Atomic write -- safe to call mid-stream without corrupting concurrent reads.

    Detects created (no prior ID) and compacted (ID changed) events.
    Skipped when _swap_in_progress is set (swap_client logs its own event).
    """
    if not _swap_in_progress:
        current = load_session_id()
        if current is None:
            log_session_event(session_id, "created")
        elif current != session_id:
            log_session_event(session_id, "compacted", parent_session_id=current)

    SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=SESSIONS_FILE.parent, suffix=".tmp")
    os.write(fd, session_id.encode())
    os.close(fd)
    os.replace(tmp, SESSIONS_FILE)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sessions.py -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: All existing tests still pass

**Step 6: Commit**

```bash
git add src/ollim_bot/sessions.py tests/test_sessions.py
git commit -m "feat: auto-detect created/compacted events in save_session_id()"
```

---

### Task 3: Log swapped and cleared events from agent.py

**Files:**
- Modify: `src/ollim_bot/agent.py:149-154` (`clear()`)
- Modify: `src/ollim_bot/agent.py:191-200` (`swap_client()`)

**Step 1: Modify swap_client()**

In `agent.py`, `swap_client()` (line 191) currently calls `save_session_id(session_id)`.
Wrap it with the swap flag and log the event:

```python
async def swap_client(self, client: ClaudeSDKClient, session_id: str) -> None:
    """Promote a forked client to the main client, replacing the old one."""
    old = self._client
    old_session_id = load_session_id()
    self._client = client
    set_swap_in_progress(True)
    try:
        save_session_id(session_id)
    finally:
        set_swap_in_progress(False)
    log_session_event(session_id, "swapped", parent_session_id=old_session_id)
    if old:
        with contextlib.suppress(CLIConnectionError):
            await old.interrupt()
        with contextlib.suppress(RuntimeError):
            await old.disconnect()
```

Update the imports at the top of `agent.py` — add `log_session_event` and
`set_swap_in_progress` to the existing `from ollim_bot.sessions import ...` block:

```python
from ollim_bot.sessions import (
    SESSIONS_FILE,
    delete_session_id,
    load_session_id,
    log_session_event,
    save_session_id,
    set_swap_in_progress,
)
```

**Step 2: Modify clear()**

In `agent.py`, `clear()` (line 149) currently calls `delete_session_id()`.
Log the cleared event before deleting:

```python
async def clear(self) -> None:
    reset_permissions()
    if self._fork_client:
        await self.exit_interactive_fork(ForkExitAction.EXIT)
    current = load_session_id()
    if current:
        log_session_event(current, "cleared")
    await self._drop_client()
    delete_session_id()
```

**Step 3: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass (no test touches `swap_client`/`clear` directly — they require
the SDK client which isn't available in unit tests)

**Step 4: Commit**

```bash
git add src/ollim_bot/agent.py
git commit -m "feat: log swapped and cleared session events from agent.py"
```

---

### Task 4: Capture interactive fork session ID from StreamEvent

**Files:**
- Modify: `src/ollim_bot/agent.py:369-393` (`stream_chat` StreamEvent handler)

**Step 1: Add fork session ID capture in stream_chat()**

In the `stream_chat()` method, inside the `isinstance(msg, StreamEvent)` branch (line 370),
add session ID capture before the existing event handling. This captures the fork's session
ID from the first StreamEvent and logs the `interactive_fork` event:

```python
        async for msg in client.receive_response():
            if isinstance(msg, StreamEvent):
                # Capture fork session ID from first StreamEvent
                if (
                    self._fork_client is not None
                    and client is self._fork_client
                    and self._fork_session_id is None
                ):
                    self._fork_session_id = msg.session_id
                    main_id = load_session_id()
                    log_session_event(
                        msg.session_id,
                        "interactive_fork",
                        parent_session_id=main_id,
                    )

                event = msg.event
                etype = event.get("type")
                # ... rest unchanged
```

Also update the `ResultMessage` handler to avoid overwriting `_fork_session_id` when
it's already been set by StreamEvent. Change line 402-403 from:

```python
                if self._fork_client is not None and client is self._fork_client:
                    self._fork_session_id = msg.session_id
```

to:

```python
                if self._fork_client is not None and client is self._fork_client:
                    if self._fork_session_id is None:
                        self._fork_session_id = msg.session_id
```

Do the same in `chat()` (line 437-438) — guard the `_fork_session_id` assignment:

```python
                if self._fork_client is not None and client is self._fork_client:
                    if self._fork_session_id is None:
                        self._fork_session_id = msg.session_id
```

Note: `chat()` does not receive StreamEvents (no streaming), so the `interactive_fork`
log will happen from `ResultMessage` instead. Add the same logging there:

```python
                if self._fork_client is not None and client is self._fork_client:
                    if self._fork_session_id is None:
                        self._fork_session_id = msg.session_id
                        main_id = load_session_id()
                        log_session_event(
                            msg.session_id,
                            "interactive_fork",
                            parent_session_id=main_id,
                        )
```

**Step 2: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass

**Step 3: Commit**

```bash
git add src/ollim_bot/agent.py
git commit -m "feat: capture interactive fork session ID from first StreamEvent"
```

---

### Task 5: Log bg_fork events from run_agent_background()

**Files:**
- Modify: `src/ollim_bot/forks.py:213-244` (`run_agent_background()`)

**Step 1: Add bg_fork logging**

In `run_agent_background()`, `run_on_client()` returns the fork's session ID.
Log the event after the call. Import `log_session_event` and `load_session_id`:

```python
async def run_agent_background(
    owner: discord.User,
    agent: Agent,
    prompt: str,
    *,
    skip_if_busy: bool,
) -> None:
    """Run agent on a disposable forked session — no lock needed.

    Contextvars scope channel and in_fork state to this task, so bg forks
    run concurrently without stomping on main session or other forks.
    """
    from ollim_bot.agent_tools import set_fork_channel
    from ollim_bot.sessions import load_session_id, log_session_event

    if skip_if_busy and agent.lock().locked():
        return

    dm = await owner.create_dm()
    set_fork_channel(dm)
    main_session_id = load_session_id()
    set_in_fork(True)

    try:
        client = await agent.create_forked_client()
        try:
            fork_session_id = await agent.run_on_client(client, prompt)
            log_session_event(
                fork_session_id,
                "bg_fork",
                parent_session_id=main_session_id,
            )
        finally:
            await client.disconnect()
    finally:
        set_in_fork(False)
```

Note: `main_session_id` is captured before the fork runs. This is correct because
the main session ID shouldn't change during a bg fork (bg forks don't hold the lock,
but `save_session_id` only changes the ID on the main path).

**Step 2: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass

**Step 3: Commit**

```bash
git add src/ollim_bot/forks.py
git commit -m "feat: log bg_fork session events from run_agent_background()"
```

---

### Task 6: Update conftest.py data_dir fixture

**Files:**
- Modify: `tests/conftest.py`

The `data_dir` fixture redirects `DATA_DIR` and module-specific paths to `tmp_path`.
Add `SESSIONS_FILE` and `HISTORY_FILE` to prevent tests from writing to the real
`~/.ollim-bot/` directory.

**Step 1: Update conftest.py**

```python
@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    """Redirect all data file paths to a temp directory."""
    import ollim_bot.inquiries as inquiries_mod
    import ollim_bot.scheduling.reminders as reminders_mod
    import ollim_bot.scheduling.routines as routines_mod
    import ollim_bot.sessions as sessions_mod
    import ollim_bot.storage as storage_mod

    monkeypatch.setattr(storage_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(routines_mod, "ROUTINES_DIR", tmp_path / "routines")
    monkeypatch.setattr(reminders_mod, "REMINDERS_DIR", tmp_path / "reminders")
    monkeypatch.setattr(inquiries_mod, "INQUIRIES_FILE", tmp_path / "inquiries.json")
    monkeypatch.setattr(sessions_mod, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(sessions_mod, "HISTORY_FILE", tmp_path / "session_history.jsonl")
    return tmp_path
```

**Step 2: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass

**Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "feat: redirect session files in data_dir fixture"
```

---

### Task 7: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Add session history to Architecture section**

Add after the `sessions.py` line in the Architecture section:

```
- `sessions.py` -- Persists Agent SDK session ID (plain string file) + session history JSONL log (lifecycle events)
```

Remove the old `sessions.py` line.

**Step 2: Add session history section**

Add a new section after "Discord embeds & buttons":

```markdown
## Session history
- `~/.ollim-bot/session_history.jsonl` -- append-only log of session lifecycle events
- Events: `created`, `compacted`, `swapped`, `cleared`, `interactive_fork`, `bg_fork`
- `save_session_id()` auto-detects `created` (no prior ID) and `compacted` (ID changed)
- `_swap_in_progress` flag prevents `save_session_id()` from logging `compacted` during `swap_client()`
- Fork session IDs captured from first `StreamEvent` (interactive) or `ResultMessage` (bg)
- Uses `storage.append_jsonl()` for writes (git auto-commit)
```

**Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add session history section to CLAUDE.md"
```
