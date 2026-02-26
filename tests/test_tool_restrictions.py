"""Tests for tool restriction helpers — per-job tool filtering on agent options."""

from claude_agent_sdk import ClaudeAgentOptions

from ollim_bot.agent import _HELP_TOOL, _apply_tool_restrictions
from ollim_bot.forks import BgForkConfig
from ollim_bot.scheduling.scheduler import _PING_TOOLS, _apply_ping_restrictions


def _opts(allowed: list[str] | None = None) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(allowed_tools=allowed or ["Read", "Write", "Bash"])


def test_no_restrictions_returns_unchanged():
    opts = _opts()

    result = _apply_tool_restrictions(opts, allowed=None, blocked=None)

    assert result is opts


def test_allowed_tools_overrides_list():
    opts = _opts(["Read", "Write", "Bash", "WebFetch"])

    result = _apply_tool_restrictions(opts, allowed=["Bash(ollim-bot gmail *)"], blocked=None)

    assert _HELP_TOOL in result.allowed_tools
    assert "Bash(ollim-bot gmail *)" in result.allowed_tools
    assert len(result.allowed_tools) == 2


def test_allowed_tools_preserves_help_if_present():
    opts = _opts()

    result = _apply_tool_restrictions(opts, allowed=[_HELP_TOOL, "Bash(ollim-bot tasks *)"], blocked=None)

    assert result.allowed_tools.count(_HELP_TOOL) == 1
    assert "Bash(ollim-bot tasks *)" in result.allowed_tools


def test_disallowed_tools_sets_disallowed():
    opts = _opts()

    result = _apply_tool_restrictions(opts, allowed=None, blocked=["WebFetch", "WebSearch"])

    assert result.disallowed_tools == ["WebFetch", "WebSearch"]
    assert result.allowed_tools == opts.allowed_tools


# --- _apply_ping_restrictions ---


def test_allow_ping_false_adds_both_to_disallowed():
    config = BgForkConfig(allow_ping=False)

    result = _apply_ping_restrictions(config)

    assert result.disallowed_tools == _PING_TOOLS
    assert result.allowed_tools is None


def test_allow_ping_false_merges_with_existing_disallowed():
    config = BgForkConfig(allow_ping=False, disallowed_tools=["WebFetch", "mcp__discord__ping_user"])

    result = _apply_ping_restrictions(config)

    assert result.disallowed_tools is not None
    assert "WebFetch" in result.disallowed_tools
    assert "mcp__discord__ping_user" in result.disallowed_tools
    assert "mcp__discord__discord_embed" in result.disallowed_tools
    assert result.disallowed_tools.count("mcp__discord__ping_user") == 1


def test_allow_ping_false_filters_from_allowed_tools():
    config = BgForkConfig(
        allow_ping=False,
        allowed_tools=[
            "Read",
            "mcp__discord__ping_user",
            "mcp__discord__discord_embed",
            "Write",
        ],
    )

    result = _apply_ping_restrictions(config)

    assert result.allowed_tools == ["Read", "Write"]
    assert result.disallowed_tools is None


def test_allow_ping_true_returns_config_unchanged():
    config = BgForkConfig(allow_ping=True, disallowed_tools=["WebFetch"])

    result = _apply_ping_restrictions(config)

    assert result is config
