# ollim-bot
# Copyright (C) 2025-2026 Julius Frost
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""Tests for eval/counterfactual.py — session rewind and intervention helpers."""

from __future__ import annotations

import json

import pytest

import ollim_bot.eval.counterfactual as cf_mod
from ollim_bot.eval.counterfactual import (
    Intervention,
    _build_options,
    _build_system_prompt,
    _extract_last_uuid,
    _scan_user_uuids,
    extract_original_response,
    find_session_file,
    truncate_session,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _record(
    *,
    type_: str,
    uuid: str,
    parent_uuid: str | None = None,
    session_id: str = "sess-001",
    content: str | list | None = None,
    usage: dict | None = None,
) -> str:
    """Build a JSONL line for a conversation record."""
    message: dict = {"role": "user" if type_ == "user" else "assistant"}
    if content is not None:
        message["content"] = content
    else:
        message["content"] = ""
    if usage:
        message["usage"] = usage
    record: dict = {
        "type": type_,
        "uuid": uuid,
        "sessionId": session_id,
        "message": message,
    }
    if parent_uuid:
        record["parentUuid"] = parent_uuid
    return json.dumps(record, separators=(",", ":"))


def _write_session(path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# find_session_file
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_projects(tmp_path, monkeypatch):
    """Set up a fake Claude projects directory with one session file."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    monkeypatch.setattr(cf_mod, "get_project_dir", lambda _cwd: project_dir)
    return tmp_path, project_dir


def test_find_session_file_exact_match(fake_projects):
    cwd, project_dir = fake_projects
    session_file = project_dir / "abc12345-full-uuid.jsonl"
    session_file.write_text("")

    result = find_session_file("abc12345", cwd)

    assert result == session_file


def test_find_session_file_prefix_match(fake_projects):
    cwd, project_dir = fake_projects
    session_file = project_dir / "deadbeef-1234-5678-9abc-def012345678.jsonl"
    session_file.write_text("")

    result = find_session_file("deadbeef", cwd)

    assert result == session_file


def test_find_session_file_not_found(fake_projects):
    cwd, _project_dir = fake_projects

    with pytest.raises(FileNotFoundError, match="No session file matching"):
        find_session_file("nonexistent", cwd)


def test_find_session_file_no_project_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cf_mod, "get_project_dir", lambda _cwd: None)

    with pytest.raises(FileNotFoundError, match="No Claude project directory"):
        find_session_file("abc", tmp_path)


# ---------------------------------------------------------------------------
# _extract_last_uuid
# ---------------------------------------------------------------------------


def test_extract_last_uuid_finds_last_occurrence():
    line = '{"uuid":"first-uuid","message":{"uuid":"nested-uuid"},"uuid":"top-level-uuid"}'

    result = _extract_last_uuid(line)

    assert result == "top-level-uuid"


def test_extract_last_uuid_single_uuid():
    line = '{"type":"user","uuid":"only-one"}'

    result = _extract_last_uuid(line)

    assert result == "only-one"


def test_extract_last_uuid_missing():
    line = '{"type":"user","id":"no-uuid-field"}'

    result = _extract_last_uuid(line)

    assert result is None


# ---------------------------------------------------------------------------
# _scan_user_uuids
# ---------------------------------------------------------------------------


def test_scan_user_uuids_caps_at_limit(tmp_path):
    filepath = tmp_path / "session.jsonl"
    lines = [_record(type_="user", uuid=f"user-{i}") for i in range(20)]
    _write_session(filepath, lines)

    result = _scan_user_uuids(filepath, limit=3)

    assert len(result) == 3
    assert result == ["user-0", "user-1", "user-2"]


def test_scan_user_uuids_skips_tool_result(tmp_path):
    filepath = tmp_path / "session.jsonl"
    # A tool_result record has both "type":"user" and "type":"tool_result" in content
    tool_result_record = {
        "type": "user",
        "uuid": "tr-uuid",
        "sessionId": "sess",
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "tu-1", "content": "ok"}],
        },
    }
    lines = [
        json.dumps(tool_result_record, separators=(",", ":")),
        _record(type_="user", uuid="real-user"),
    ]
    _write_session(filepath, lines)

    result = _scan_user_uuids(filepath, limit=10)

    assert result == ["real-user"]


def test_scan_user_uuids_skips_assistant_records(tmp_path):
    filepath = tmp_path / "session.jsonl"
    lines = [
        _record(type_="user", uuid="u1"),
        _record(type_="assistant", uuid="a1", parent_uuid="u1"),
        _record(type_="user", uuid="u2"),
    ]
    _write_session(filepath, lines)

    result = _scan_user_uuids(filepath, limit=10)

    assert result == ["u1", "u2"]


# ---------------------------------------------------------------------------
# truncate_session
# ---------------------------------------------------------------------------


def test_truncate_keeps_lines_before_rewind(tmp_path):
    filepath = tmp_path / "session.jsonl"
    lines = [
        _record(type_="user", uuid="u1", content="hello"),
        _record(type_="assistant", uuid="a1", parent_uuid="u1", content="hi"),
        _record(type_="user", uuid="u2", content="follow up"),
        _record(type_="assistant", uuid="a2", parent_uuid="u2", content="sure"),
    ]
    _write_session(filepath, lines)

    temp_path, message = truncate_session(filepath, "u2")

    assert message == "follow up"
    truncated_lines = temp_path.read_text().strip().splitlines()
    assert len(truncated_lines) == 2
    assert '"u1"' in truncated_lines[0]
    assert '"a1"' in truncated_lines[1]
    temp_path.unlink()


def test_truncate_uuid_not_found_raises(tmp_path):
    filepath = tmp_path / "session.jsonl"
    lines = [
        _record(type_="user", uuid="u1", content="hello"),
    ]
    _write_session(filepath, lines)

    with pytest.raises(ValueError, match="UUID 'missing' not found"):
        truncate_session(filepath, "missing")


def test_truncate_first_message_produces_empty_file(tmp_path):
    filepath = tmp_path / "session.jsonl"
    lines = [
        _record(type_="user", uuid="u1", content="first message"),
        _record(type_="assistant", uuid="a1", parent_uuid="u1", content="response"),
    ]
    _write_session(filepath, lines)

    temp_path, message = truncate_session(filepath, "u1")

    assert message == "first message"
    assert temp_path.read_text() == ""
    temp_path.unlink()


# ---------------------------------------------------------------------------
# extract_original_response
# ---------------------------------------------------------------------------


def test_extract_original_response_text_and_tools(tmp_path):
    filepath = tmp_path / "session.jsonl"
    assistant_content = [
        {"type": "text", "text": "Let me check that."},
        {"type": "tool_use", "id": "tu-1", "name": "Read", "input": {"path": "/foo"}},
        {"type": "text", "text": "Here is the answer."},
    ]
    lines = [
        _record(type_="user", uuid="u1", content="what is foo?"),
        _record(
            type_="assistant",
            uuid="a1",
            parent_uuid="u1",
            content=assistant_content,
            usage={"input_tokens": 100, "output_tokens": 50},
        ),
    ]
    _write_session(filepath, lines)

    result = extract_original_response(filepath, "u1")

    assert "Let me check that." in result.text
    assert "Here is the answer." in result.text
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["name"] == "Read"
    assert result.input_tokens == 100
    assert result.output_tokens == 50


def test_extract_original_response_no_tools(tmp_path):
    filepath = tmp_path / "session.jsonl"
    lines = [
        _record(type_="user", uuid="u1", content="hi"),
        _record(
            type_="assistant",
            uuid="a1",
            parent_uuid="u1",
            content=[{"type": "text", "text": "hello!"}],
        ),
    ]
    _write_session(filepath, lines)

    result = extract_original_response(filepath, "u1")

    assert result.text == "hello!"
    assert result.tool_calls == []
    assert result.input_tokens is None


# ---------------------------------------------------------------------------
# Intervention.__post_init__
# ---------------------------------------------------------------------------


def test_intervention_rejects_append_and_replace():
    with pytest.raises(ValueError, match="mutually exclusive"):
        Intervention(
            system_prompt_append="extra",
            system_prompt_replace="full replacement",
        )


def test_intervention_allows_append_alone():
    i = Intervention(system_prompt_append="extra")

    assert i.system_prompt_append == "extra"
    assert i.system_prompt_replace is None


def test_intervention_allows_replace_alone():
    i = Intervention(system_prompt_replace="full")

    assert i.system_prompt_replace == "full"
    assert i.system_prompt_append is None


# ---------------------------------------------------------------------------
# _build_system_prompt
# ---------------------------------------------------------------------------

_FAKE_BASE_PROMPT = "base system prompt"


@pytest.fixture()
def _patch_build_prompt(monkeypatch):
    monkeypatch.setattr(cf_mod, "build_system_prompt", lambda: _FAKE_BASE_PROMPT)


@pytest.mark.usefixtures("_patch_build_prompt")
def test_build_system_prompt_default_uses_preset():
    result = _build_system_prompt(None)

    assert isinstance(result, dict)  # SystemPromptPreset is a TypedDict
    assert result["type"] == "preset"
    assert result["preset"] == "claude_code"
    assert result["append"] == _FAKE_BASE_PROMPT


@pytest.mark.usefixtures("_patch_build_prompt")
def test_build_system_prompt_append_adds_to_base():
    intervention = Intervention(system_prompt_append="extra instruction")

    result = _build_system_prompt(intervention)

    assert isinstance(result, dict)
    assert result["append"] == f"{_FAKE_BASE_PROMPT}\n\nextra instruction"


@pytest.mark.usefixtures("_patch_build_prompt")
def test_build_system_prompt_replace_returns_string():
    intervention = Intervention(system_prompt_replace="custom prompt")

    result = _build_system_prompt(intervention)

    assert result == "custom prompt"
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _build_options
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_patch_build_prompt")
def test_build_options_applies_model(tmp_path):
    opts = _build_options(Intervention(model="haiku"), tmp_path)

    assert opts.model == "haiku"


@pytest.mark.usefixtures("_patch_build_prompt")
def test_build_options_applies_disallowed_tools(tmp_path):
    opts = _build_options(Intervention(disallowed_tools=["Bash"]), tmp_path)

    assert opts.disallowed_tools == ["Bash"]


@pytest.mark.usefixtures("_patch_build_prompt")
def test_build_options_applies_allowed_tools(tmp_path):
    opts = _build_options(Intervention(allowed_tools=["Read"]), tmp_path)

    assert opts.allowed_tools == ["Read"]


@pytest.mark.usefixtures("_patch_build_prompt")
def test_build_options_applies_budget_and_turns(tmp_path):
    opts = _build_options(Intervention(max_turns=2, max_budget_usd=0.10), tmp_path)

    assert opts.max_turns == 2
    assert opts.max_budget_usd == 0.10


@pytest.mark.usefixtures("_patch_build_prompt")
def test_build_options_defaults_include_docs_mcp(tmp_path):
    opts = _build_options(None, tmp_path)

    assert isinstance(opts.mcp_servers, dict)
    assert "docs" in opts.mcp_servers


# ---------------------------------------------------------------------------
# truncate_session — compaction boundary
# ---------------------------------------------------------------------------


def test_truncate_preserves_compact_boundary(tmp_path):
    filepath = tmp_path / "session.jsonl"
    compact_record = json.dumps(
        {
            "type": "system",
            "subtype": "compact_boundary",
            "uuid": "cb-1",
            "sessionId": "sess-001",
        },
        separators=(",", ":"),
    )
    summary_record = json.dumps(
        {
            "type": "user",
            "uuid": "summary-1",
            "sessionId": "sess-001",
            "isCompactSummary": True,
            "message": {"role": "user", "content": "Summary of prior conversation."},
        },
        separators=(",", ":"),
    )
    lines = [
        compact_record,
        summary_record,
        _record(type_="assistant", uuid="a1", parent_uuid="summary-1", content="ok"),
        _record(type_="user", uuid="u2", content="new question"),
    ]
    _write_session(filepath, lines)

    temp_path, message = truncate_session(filepath, "u2")

    assert message == "new question"
    truncated = temp_path.read_text().strip().splitlines()
    assert len(truncated) == 3
    assert "compact_boundary" in truncated[0]
    assert "isCompactSummary" in truncated[1]
    temp_path.unlink()


# ---------------------------------------------------------------------------
# truncate_session — cleanup and placement
# ---------------------------------------------------------------------------


def test_truncate_cleans_temp_on_uuid_not_found(tmp_path):
    filepath = tmp_path / "session.jsonl"
    _write_session(filepath, [_record(type_="user", uuid="u1", content="hi")])

    with pytest.raises(ValueError):
        truncate_session(filepath, "nonexistent")

    # No orphaned temp files should remain
    remaining = list(tmp_path.glob("*.jsonl"))
    assert remaining == [filepath]


def test_truncate_temp_in_same_directory(tmp_path):
    subdir = tmp_path / "projects"
    subdir.mkdir()
    filepath = subdir / "session.jsonl"
    lines = [
        _record(type_="user", uuid="u1", content="first"),
        _record(type_="user", uuid="u2", content="second"),
    ]
    _write_session(filepath, lines)

    temp_path, _ = truncate_session(filepath, "u2")

    assert temp_path.parent == subdir
    temp_path.unlink()


# ---------------------------------------------------------------------------
# Intervention.message_override
# ---------------------------------------------------------------------------


def test_message_override_stored():
    i = Intervention(message_override="different question")

    assert i.message_override == "different question"
