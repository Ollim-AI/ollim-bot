"""Tests for _apply_tool_restrictions — per-job tool filtering on agent options."""

from claude_agent_sdk import ClaudeAgentOptions

from ollim_bot.agent import _HELP_TOOL, _apply_tool_restrictions


def _opts(allowed: list[str] | None = None) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(allowed_tools=allowed or ["Read", "Write", "Bash"])


def test_no_restrictions_returns_unchanged():
    opts = _opts()

    result = _apply_tool_restrictions(opts, allowed=None, blocked=None)

    assert result is opts


def test_allowed_tools_overrides_list():
    opts = _opts(["Read", "Write", "Bash", "WebFetch"])

    result = _apply_tool_restrictions(
        opts, allowed=["Bash(ollim-bot gmail *)"], blocked=None
    )

    assert _HELP_TOOL in result.allowed_tools
    assert "Bash(ollim-bot gmail *)" in result.allowed_tools
    assert len(result.allowed_tools) == 2


def test_allowed_tools_preserves_help_if_present():
    opts = _opts()

    result = _apply_tool_restrictions(
        opts, allowed=[_HELP_TOOL, "Bash(ollim-bot tasks *)"], blocked=None
    )

    assert result.allowed_tools.count(_HELP_TOOL) == 1
    assert "Bash(ollim-bot tasks *)" in result.allowed_tools


def test_disallowed_tools_sets_disallowed():
    opts = _opts()

    result = _apply_tool_restrictions(
        opts, allowed=None, blocked=["WebFetch", "WebSearch"]
    )

    assert result.disallowed_tools == ["WebFetch", "WebSearch"]
    assert result.allowed_tools == opts.allowed_tools
