"""Tests for tool restriction helpers — per-job tool filtering on agent options."""

from claude_agent_sdk import ClaudeAgentOptions

from ollim_bot.fork_state import BgForkConfig, apply_ping_restrictions, apply_reporting_restrictions
from ollim_bot.tool_policy import _HELP_TOOL, apply_tool_restrictions


def _opts(allowed: list[str] | None = None) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(allowed_tools=allowed or ["Read", "Write", "Bash"])


def test_no_restrictions_returns_unchanged():
    opts = _opts()

    result = apply_tool_restrictions(opts, allowed=None)

    assert result is opts


def test_allowed_tools_overrides_list():
    opts = _opts(["Read", "Write", "Bash", "WebFetch"])

    result = apply_tool_restrictions(opts, allowed=["Bash(ollim-bot gmail *)"])

    assert _HELP_TOOL in result.allowed_tools
    assert "Bash(ollim-bot gmail *)" in result.allowed_tools
    assert len(result.allowed_tools) == 2


def test_allowed_tools_preserves_help_if_present():
    opts = _opts()

    result = apply_tool_restrictions(opts, allowed=[_HELP_TOOL, "Bash(ollim-bot tasks *)"])

    assert result.allowed_tools.count(_HELP_TOOL) == 1
    assert "Bash(ollim-bot tasks *)" in result.allowed_tools


# --- apply_ping_restrictions ---


def test_allow_ping_false_no_allowed_tools_returns_empty():
    """When allow_ping=False and allowed_tools is None, returns empty list."""
    config = BgForkConfig(allow_ping=False)

    result = apply_ping_restrictions(config)

    assert result.allowed_tools == []


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

    result = apply_ping_restrictions(config)

    assert result.allowed_tools == ["Read", "Write"]


def test_allow_ping_true_returns_config_unchanged():
    config = BgForkConfig(allow_ping=True, allowed_tools=["WebFetch"])

    result = apply_ping_restrictions(config)

    assert result is config


# --- apply_reporting_restrictions ---


def test_apply_reporting_restrictions_blocked_strips_reporting_tools():
    config = BgForkConfig(
        update_main_session="blocked",
        allowed_tools=["mcp__discord__report_updates", "mcp__discord__follow_up_chain", "Read"],
    )

    result = apply_reporting_restrictions(config)

    assert result.allowed_tools is not None
    assert "mcp__discord__report_updates" not in result.allowed_tools
    assert "mcp__discord__follow_up_chain" not in result.allowed_tools
    assert "Read" in result.allowed_tools


def test_apply_reporting_restrictions_not_blocked_unchanged():
    config = BgForkConfig(update_main_session="on_ping", allowed_tools=["Read"])

    result = apply_reporting_restrictions(config)

    assert result is config


def test_apply_reporting_restrictions_none_allowed_tools():
    config = BgForkConfig(update_main_session="blocked", allowed_tools=None)

    result = apply_reporting_restrictions(config)

    assert result.allowed_tools == []
