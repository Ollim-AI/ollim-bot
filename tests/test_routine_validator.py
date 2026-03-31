"""Tests for the routine_validator PreToolUse hook in hooks.py."""

import asyncio
from typing import cast
from unittest.mock import patch

from claude_agent_sdk.types import HookContext, HookInput, PreToolUseHookInput

from ollim_bot.hooks import routine_validator, validate_routine

_CTX = cast(HookContext, {"signal": None})


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_input(file_path: str, content: str) -> HookInput:
    return cast(
        HookInput,
        PreToolUseHookInput(
            session_id="test",
            transcript_path="",
            cwd="/tmp",
            agent_id="test",
            agent_type="main",
            hook_event_name="PreToolUse",
            tool_name="Write",
            tool_input={"file_path": file_path, "content": content},
            tool_use_id="test",
        ),
    )


VALID_ROUTINE = """\
---
id: abc12345
cron: 0 9 * * *
description: Morning check-in
background: true
allowed-tools:
  - Read
  - Glob
---

Check the user's schedule and summarize.
"""


# --- Block tests ---


def test_block_no_frontmatter():
    blocks, _ = validate_routine("# Just a heading\nSome content")
    assert blocks
    assert "frontmatter" in blocks[0].lower()


def test_block_missing_id():
    content = "---\ncron: 0 9 * * *\ndescription: test\n---\nBody"
    blocks, _ = validate_routine(content)
    assert any("id" in b for b in blocks)


def test_block_missing_cron():
    content = "---\nid: abc12345\ndescription: test\n---\nBody"
    blocks, _ = validate_routine(content)
    assert any("cron" in b for b in blocks)


def test_block_invalid_cron_too_few_fields():
    content = "---\nid: abc12345\ncron: 0 9 *\n---\nBody"
    blocks, _ = validate_routine(content)
    assert any("cron" in b.lower() for b in blocks)


def test_block_invalid_cron_too_many_fields():
    content = "---\nid: abc12345\ncron: 0 9 * * * *\n---\nBody"
    blocks, _ = validate_routine(content)
    assert any("cron" in b.lower() for b in blocks)


def test_block_malformed_yaml():
    content = "---\nid: abc12345\nthis is not yaml\n---\nBody"
    blocks, _ = validate_routine(content)
    assert any("malformed" in b.lower() for b in blocks)


def test_block_unclosed_frontmatter():
    content = "---\nid: abc12345\ncron: 0 9 * * *\n"
    blocks, _ = validate_routine(content)
    assert any("unclosed" in b.lower() for b in blocks)


# --- Warning tests ---


def test_warn_missing_description():
    content = "---\nid: abc12345\ncron: 0 9 * * *\nbackground: true\n---\nBody"
    _, warnings = validate_routine(content)
    assert any("description" in w.lower() for w in warnings)


def test_warn_missing_background():
    content = "---\nid: abc12345\ncron: 0 9 * * *\ndescription: test\n---\nBody"
    _, warnings = validate_routine(content)
    assert any("background" in w.lower() for w in warnings)


def test_warn_unscoped_bash():
    content = "---\nid: abc12345\ncron: 0 9 * * *\ndescription: test\nbackground: true\nallowed-tools:\n  - Bash\n  - Read\n---\nBody"
    _, warnings = validate_routine(content)
    assert any("Bash" in w for w in warnings)


def test_warn_unscoped_write():
    content = (
        "---\nid: abc12345\ncron: 0 9 * * *\ndescription: test\nbackground: true\nallowed-tools:\n  - Write\n---\nBody"
    )
    _, warnings = validate_routine(content)
    assert any("Write" in w for w in warnings)


def test_warn_delegation_plus_shared_write():
    content = "---\nid: abc12345\ncron: 0 9 * * *\ndescription: test\nbackground: true\nallowed-tools:\n  - Agent\n  - Write\n---\nBody"
    _, warnings = validate_routine(content)
    assert any("delegation" in w.lower() for w in warnings)


def test_warn_underscore_keys():
    content = (
        "---\nid: abc12345\ncron: 0 9 * * *\ndescription: test\nbackground: true\nallowed_tools:\n  - Read\n---\nBody"
    )
    _, warnings = validate_routine(content)
    assert any("underscore" in w.lower() for w in warnings)


def test_warn_unknown_keys():
    content = "---\nid: abc12345\ncron: 0 9 * * *\ndescription: test\nbackground: true\nfoobar: true\n---\nBody"
    _, warnings = validate_routine(content)
    assert any("foobar" in w for w in warnings)


def test_warn_long_routine():
    body = "\n".join(f"Line {i}" for i in range(210))
    content = f"---\nid: abc12345\ncron: 0 9 * * *\ndescription: test\nbackground: true\n---\n{body}"
    _, warnings = validate_routine(content)
    assert any("lines" in w for w in warnings)


# --- Happy path tests ---


def test_valid_routine_no_issues():
    blocks, warnings = validate_routine(VALID_ROUTINE)
    assert not blocks
    assert not warnings


def test_valid_routine_scoped_tools():
    content = "---\nid: abc12345\ncron: 0 9 * * *\ndescription: test\nbackground: true\nallowed-tools:\n  - Write(./practice-log.md)\n  - Bash(ollim-bot tasks *)\n---\nBody"
    blocks, warnings = validate_routine(content)
    assert not blocks
    assert not any("Bash" in w or "Write" in w for w in warnings)


# --- Integration tests (full hook function) ---


def test_hook_ignores_non_routine_path():
    inp = _make_input("/home/user/some-file.md", "content")
    result = _run(routine_validator(inp, None, _CTX))
    assert result == {}


def test_hook_ignores_non_md_file():
    inp = _make_input("/home/user/.ollim-bot/routines/config.json", "{}")
    result = _run(routine_validator(inp, None, _CTX))
    assert result == {}


def test_hook_blocks_on_missing_id(data_dir):
    content = "---\ncron: 0 9 * * *\ndescription: test\n---\nBody"
    routines_dir = data_dir / "routines"
    routines_dir.mkdir(exist_ok=True)
    path = str(routines_dir / "test.md")
    inp = _make_input(path, content)
    with patch("ollim_bot.hooks.ROUTINES_DIR", routines_dir):
        result = _run(routine_validator(inp, None, _CTX))
    assert result.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


def test_hook_warns_with_additional_context(data_dir):
    content = "---\nid: abc12345\ncron: 0 9 * * *\n---\nBody"
    routines_dir = data_dir / "routines"
    routines_dir.mkdir(exist_ok=True)
    path = str(routines_dir / "test.md")
    inp = _make_input(path, content)
    with patch("ollim_bot.hooks.ROUTINES_DIR", routines_dir):
        result = _run(routine_validator(inp, None, _CTX))
    ctx = result.get("hookSpecificOutput", {}).get("additionalContext", "")
    assert "routine-validator" in ctx
    assert "warning" in ctx
