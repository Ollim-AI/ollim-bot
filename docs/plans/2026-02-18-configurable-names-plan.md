# Configurable User & Bot Names — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace hardcoded "Julius" and bot display name with `OLLIM_USER_NAME` / `OLLIM_BOT_NAME` env vars so anyone can run the bot.

**Architecture:** New `config.py` reads env vars at import time, fails fast if missing. Prompts and other files import `USER_NAME`/`BOT_NAME` from config. Tests set env vars in conftest.

**Tech Stack:** python-dotenv (already installed), os.environ

---

### Task 1: Set env vars in test conftest

Tests will break once `config.py` exists and is imported (fail-fast on missing vars). Set the env vars before anything else imports config.

**Files:**
- Modify: `tests/conftest.py`

**Step 1: Add env var setup to conftest**

At the top of `tests/conftest.py`, before any ollim_bot imports can trigger, add:

```python
import os

os.environ.setdefault("OLLIM_USER_NAME", "TestUser")
os.environ.setdefault("OLLIM_BOT_NAME", "test-bot")
```

This must be at module level (not in a fixture) because `config.py` evaluates at import time. Use `setdefault` so real env vars aren't overwritten.

The full file becomes:

```python
"""Shared fixtures for ollim-bot tests."""

import os

os.environ.setdefault("OLLIM_USER_NAME", "TestUser")
os.environ.setdefault("OLLIM_BOT_NAME", "test-bot")

import pytest


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    """Redirect all data file paths to a temp directory."""
    import ollim_bot.inquiries as inquiries_mod
    import ollim_bot.scheduling.reminders as reminders_mod
    import ollim_bot.scheduling.routines as routines_mod
    import ollim_bot.storage as storage_mod

    monkeypatch.setattr(storage_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(routines_mod, "ROUTINES_DIR", tmp_path / "routines")
    monkeypatch.setattr(reminders_mod, "REMINDERS_DIR", tmp_path / "reminders")
    monkeypatch.setattr(inquiries_mod, "INQUIRIES_FILE", tmp_path / "inquiries.json")
    return tmp_path
```

**Step 2: Run existing tests to confirm nothing breaks**

Run: `uv run pytest -v`
Expected: All existing tests PASS (env vars set but config.py doesn't exist yet — no effect).

**Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "Set OLLIM_USER_NAME and OLLIM_BOT_NAME env vars in test conftest"
```

---

### Task 2: Create config.py with fail-fast env loading

**Files:**
- Create: `src/ollim_bot/config.py`
- Test: `tests/test_config.py`

**Step 1: Write the failing test**

Create `tests/test_config.py`:

```python
"""Tests for config module."""

import importlib
import os

import pytest


def test_missing_user_name_exits(monkeypatch):
    monkeypatch.delenv("OLLIM_USER_NAME", raising=False)
    monkeypatch.setenv("OLLIM_BOT_NAME", "test-bot")

    import ollim_bot.config as config_mod

    with pytest.raises(SystemExit, match="OLLIM_USER_NAME"):
        importlib.reload(config_mod)


def test_missing_bot_name_exits(monkeypatch):
    monkeypatch.setenv("OLLIM_USER_NAME", "TestUser")
    monkeypatch.delenv("OLLIM_BOT_NAME", raising=False)

    import ollim_bot.config as config_mod

    with pytest.raises(SystemExit, match="OLLIM_BOT_NAME"):
        importlib.reload(config_mod)


def test_valid_config_loads(monkeypatch):
    monkeypatch.setenv("OLLIM_USER_NAME", "Alice")
    monkeypatch.setenv("OLLIM_BOT_NAME", "my-bot")

    import ollim_bot.config as config_mod

    importlib.reload(config_mod)
    assert config_mod.USER_NAME == "Alice"
    assert config_mod.BOT_NAME == "my-bot"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ollim_bot.config'`

**Step 3: Write the implementation**

Create `src/ollim_bot/config.py`:

```python
"""User-configurable names loaded from environment variables."""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

_REQUIRED = ("OLLIM_USER_NAME", "OLLIM_BOT_NAME")
_missing = [var for var in _REQUIRED if not os.environ.get(var)]
if _missing:
    print(f"Missing required env vars: {', '.join(_missing)}", file=sys.stderr)
    print("Set them in .env or your environment.", file=sys.stderr)
    raise SystemExit(1)

USER_NAME: str = os.environ["OLLIM_USER_NAME"]
BOT_NAME: str = os.environ["OLLIM_BOT_NAME"]
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: All 3 tests PASS.

**Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests PASS (conftest sets the env vars, config.py isn't imported by anything yet).

**Step 6: Commit**

```bash
git add src/ollim_bot/config.py tests/test_config.py
git commit -m "Add config module with fail-fast env var loading"
```

---

### Task 3: Update prompts.py to use config values

This is the largest change — ~25 "Julius" replacements.

**Files:**
- Modify: `src/ollim_bot/prompts.py`

**Step 1: Add config import and convert SYSTEM_PROMPT**

Add `from ollim_bot.config import USER_NAME` at the top of `prompts.py`.

Replace every literal `Julius` with `{USER_NAME}` in an f-string. The prompt strings change from `"""..."""` to `f"""..."""`.

Occurrences in `SYSTEM_PROMPT` (lines 4, 11, 15, 50, 95, 111, 117, 139, 152, 193, 207, 213, 214):
- `"Julius's personal"` → `f"{USER_NAME}'s personal"`
- `"When Julius tells you"` → `f"When {USER_NAME} tells you"`
- `"When Julius asks"` → `f"When {USER_NAME} asks"`
- `"When Julius mentions"` → `f"When {USER_NAME} mentions"`
- `"Skip if Julius is mid-conversation"` → `f"Skip if {USER_NAME} is mid-conversation"`
- `"nudge Julius"` → `f"nudge {USER_NAME}"`
- `"managed by Julius"` → `f"managed by {USER_NAME}"`
- `"did Julius finish"` → `f"did {USER_NAME} finish"`
- `"relay important items to Julius"` → `f"relay important items to {USER_NAME}"`
- `"anything Julius asks about"` → `f"anything {USER_NAME} asks about"`
- `"Julius can also use"` → `f"{USER_NAME} can also use"`
- `"If Julius doesn't respond"` → `f"If {USER_NAME} doesn't respond"`
- `"so Julius can choose"` → `f"so {USER_NAME} can choose"`

**Step 2: Convert HISTORY_REVIEWER_PROMPT**

Occurrences (lines 231, 261, 270, 274):
- `"Julius's session history reviewer"` → `f"{USER_NAME}'s session history reviewer"`
- `"what Julius was working on"` → `f"what {USER_NAME} was working on"`
- `"Julius needs to act"` → `f"{USER_NAME} needs to act"`
- `"Questions Julius asked"` → `f"Questions {USER_NAME} asked"`

**Step 3: Convert GMAIL_READER_PROMPT**

Occurrences (lines 294, 295, 307, 308, 327):
- `"Julius's email triage assistant"` → `f"{USER_NAME}'s email triage assistant"`
- `"require Julius to DO something"` → `f"require {USER_NAME} to DO something"`
- `"Julius must do something"` → `f"{USER_NAME} must do something"`
- `"wrote to Julius directly"` → `f"wrote to {USER_NAME} directly"`
- `"what Julius needs to do"` → `f"what {USER_NAME} needs to do"`

**Step 4: Convert RESPONSIVENESS_REVIEWER_PROMPT**

Occurrences (lines 335, 336, 366, 379):
- `"Julius's reminder responsiveness analyst"` → `f"{USER_NAME}'s reminder responsiveness analyst"`
- `"reach Julius"` → `f"reach {USER_NAME}"`
- `"Julius responded afterward"` → `f"{USER_NAME} responded afterward"`
- `"does Julius respond better"` → `f"does {USER_NAME} respond better"`

**Step 5: Run tests**

Run: `uv run pytest -v`
Expected: All tests PASS.

**Step 6: Commit**

```bash
git add src/ollim_bot/prompts.py
git commit -m "Replace hardcoded Julius in prompts with configurable USER_NAME"
```

---

### Task 4: Update bot.py, scheduler.py, views.py, agent_tools.py

**Files:**
- Modify: `src/ollim_bot/bot.py:218,247`
- Modify: `src/ollim_bot/scheduling/scheduler.py:285`
- Modify: `src/ollim_bot/views.py:149`
- Modify: `src/ollim_bot/agent_tools.py:113-114`

**Step 1: Update bot.py**

Add `from ollim_bot.config import BOT_NAME, USER_NAME` at the top imports.

Line 218: Change `f"ollim-bot online as {bot.user}"` to `f"{BOT_NAME} online as {bot.user}"`

Line 247: Change `"hey julius, ollim-bot is online. what's on your plate today?"` to `f"hey {USER_NAME.lower()}, {BOT_NAME} is online. what's on your plate today?"`

**Step 2: Update scheduler.py**

Add `from ollim_bot.config import USER_NAME` at the top imports.

Line 285: Change `"If Julius is still engaged, ask them what they'd like to do."` to `f"If {USER_NAME} is still engaged, ask them what they'd like to do."`

**Step 3: Update views.py**

Add `from ollim_bot.config import USER_NAME` at the top imports.

Line 149: Change `"[system] Julius clicked Report to exit this fork. "` to `f"[system] {USER_NAME} clicked Report to exit this fork. "`

**Step 4: Update agent_tools.py**

Add `from ollim_bot.config import USER_NAME` at the top imports.

Lines 113-114: Change `"Send a plain text message to Julius. Use in background mode when something "` to `f"Send a plain text message to {USER_NAME}. Use in background mode when something "`

Note: The `@tool` decorator receives the description string at decoration time (module import). Since `USER_NAME` is a module-level constant loaded at import, this works — the f-string evaluates when the module is first imported.

**Step 5: Run tests**

Run: `uv run pytest -v`
Expected: All tests PASS.

**Step 6: Commit**

```bash
git add src/ollim_bot/bot.py src/ollim_bot/scheduling/scheduler.py src/ollim_bot/views.py src/ollim_bot/agent_tools.py
git commit -m "Replace hardcoded names in bot, scheduler, views, and agent_tools"
```

---

### Task 5: Update .env.example and main.py

**Files:**
- Modify: `.env.example`
- Modify: `src/ollim_bot/main.py:101-103`

**Step 1: Add new vars to .env.example**

Append to `.env.example`:
```
OLLIM_USER_NAME=
OLLIM_BOT_NAME=
```

**Step 2: Remove redundant DISCORD_TOKEN check from main.py**

`main.py` currently checks for `DISCORD_TOKEN` after `load_dotenv`. Keep this check — it's separate from config.py. No change needed here.

Actually — consider moving `DISCORD_TOKEN` into `config.py` too for consistency. But that's out of scope. Leave main.py as-is.

**Step 3: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests PASS.

**Step 4: Commit**

```bash
git add .env.example
git commit -m "Add OLLIM_USER_NAME and OLLIM_BOT_NAME to .env.example"
```

---

### Task 6: Add env vars to real .env and smoke test

**Files:**
- Modify: `.env` (add `OLLIM_USER_NAME=Julius` and `OLLIM_BOT_NAME=ollim-bot`)

**Step 1: Add vars to .env**

Add to `.env`:
```
OLLIM_USER_NAME=Julius
OLLIM_BOT_NAME=ollim-bot
```

**Step 2: Smoke test — verify bot starts**

Run: `timeout 10 uv run ollim-bot 2>&1 || true`
Expected: Should print `ollim-bot online as ...` (or connection error if no network — the point is it doesn't crash on missing env vars).

**Step 3: Run full test suite one final time**

Run: `uv run pytest --cov=ollim_bot -v`
Expected: All tests PASS with good coverage on config.py.

**Step 4: Final commit (no .env — it's gitignored)**

No commit needed for `.env` (gitignored). This task is manual setup only.
