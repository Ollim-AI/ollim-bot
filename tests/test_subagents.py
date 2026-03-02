"""Tests for bundled subagent installation and tool-set extraction."""

from textwrap import dedent
from unittest.mock import patch

import ollim_bot.subagents as subagents_mod
from ollim_bot.subagents import _expand, _extract_tools, install_agents, load_agent_tool_sets

# --- _expand ---


def test_expand_replaces_user_name():
    result = _expand("Hello {USER_NAME}")

    assert "{USER_NAME}" not in result


def test_expand_replaces_bot_name():
    result = _expand("{BOT_NAME} says hi")

    assert "{BOT_NAME}" not in result


def test_expand_preserves_unknown_placeholders():
    result = _expand("Hello {UNKNOWN}")

    assert result == "Hello {UNKNOWN}"


# --- install_agents ---


def test_install_agents_copies_bundled_specs(tmp_path, monkeypatch):
    agents_dir = tmp_path / "agents"
    monkeypatch.setattr(subagents_mod, "_AGENTS_DIR", agents_dir)

    install_agents()

    installed = sorted(p.name for p in agents_dir.glob("*.md"))
    assert "guide.md" in installed
    assert "gmail-reader.md" in installed
    assert len(installed) == 5


def test_install_agents_expands_templates(tmp_path, monkeypatch):
    agents_dir = tmp_path / "agents"
    monkeypatch.setattr(subagents_mod, "_AGENTS_DIR", agents_dir)

    install_agents()

    for path in agents_dir.glob("*.md"):
        text = path.read_text()
        assert "{USER_NAME}" not in text
        assert "{BOT_NAME}" not in text


def test_install_agents_skips_existing(tmp_path, monkeypatch):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "guide.md").write_text("custom content")
    monkeypatch.setattr(subagents_mod, "_AGENTS_DIR", agents_dir)

    install_agents()

    assert (agents_dir / "guide.md").read_text() == "custom content"


def test_install_agents_creates_target_dir(tmp_path, monkeypatch):
    agents_dir = tmp_path / "nested" / "agents"
    monkeypatch.setattr(subagents_mod, "_AGENTS_DIR", agents_dir)

    install_agents()

    assert agents_dir.is_dir()
    assert any(agents_dir.glob("*.md"))


# --- _extract_tools ---


def test_extract_tools_valid(tmp_path):
    path = tmp_path / "test.md"
    path.write_text(
        dedent("""\
        ---
        name: test-agent
        description: "A test subagent"
        tools:
          - "Read(**.md)"
          - "Bash(ollim-bot help)"
        ---
        You are a test agent.
    """)
    )

    result = _extract_tools(path)

    assert result is not None
    name, tools = result
    assert name == "test-agent"
    assert tools == ["Read(**.md)", "Bash(ollim-bot help)"]


def test_extract_tools_comma_separated_string(tmp_path):
    path = tmp_path / "test.md"
    path.write_text("---\nname: t\ntools: Bash, Read, Grep\n---\nbody")

    result = _extract_tools(path)

    assert result is not None
    assert result[1] == ["Bash", "Read", "Grep"]


def test_extract_tools_no_tools_returns_none(tmp_path):
    path = tmp_path / "test.md"
    path.write_text("---\nname: t\ndescription: test\n---\nbody")

    assert _extract_tools(path) is None


def test_extract_tools_missing_frontmatter(tmp_path):
    path = tmp_path / "bad.md"
    path.write_text("no frontmatter here")

    assert _extract_tools(path) is None


def test_extract_tools_invalid_yaml(tmp_path):
    path = tmp_path / "bad.md"
    path.write_text("---\n{{{bad yaml\n---\nbody")

    assert _extract_tools(path) is None


def test_extract_tools_name_defaults_to_stem(tmp_path):
    path = tmp_path / "my-agent.md"
    path.write_text("---\ntools:\n  - Read\n---\nbody")

    result = _extract_tools(path)

    assert result is not None
    assert result[0] == "my-agent"


# --- load_agent_tool_sets ---


def test_load_agent_tool_sets_from_installed(tmp_path):
    agents_dir = tmp_path / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "guide.md").write_text("---\nname: guide\ntools:\n  - mcp__docs__*\n---\nbody")
    (agents_dir / "reader.md").write_text("---\nname: reader\ntools:\n  - Read\n---\nbody")

    with patch("ollim_bot.subagents._AGENTS_DIR", agents_dir):
        tool_sets = load_agent_tool_sets()

    assert tool_sets == {
        "subagent:guide": ["mcp__docs__*"],
        "subagent:reader": ["Read"],
    }


def test_load_agent_tool_sets_skips_no_tools(tmp_path):
    agents_dir = tmp_path / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "no-tools.md").write_text("---\nname: no-tools\ndescription: test\n---\nbody")

    with patch("ollim_bot.subagents._AGENTS_DIR", agents_dir):
        tool_sets = load_agent_tool_sets()

    assert tool_sets == {}


def test_load_agent_tool_sets_missing_dir(tmp_path):
    with patch("ollim_bot.subagents._AGENTS_DIR", tmp_path / "nonexistent"):
        tool_sets = load_agent_tool_sets()

    assert tool_sets == {}
