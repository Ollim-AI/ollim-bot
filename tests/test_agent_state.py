"""Unit tests for Agent state transitions and lifecycle helpers in agent.py."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from claude_agent_sdk import ClaudeAgentOptions, CLIConnectionError

from ollim_bot.agent import _with_thinking
from ollim_bot.fork_state import ForkExitAction
from ollim_bot.runtime_config import BYPASS_PERMISSIONS


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Shared mocking for Agent construction
# ---------------------------------------------------------------------------


def _make_agent():
    """Construct an Agent with all heavy imports mocked."""
    with (
        patch("ollim_bot.prompts.build_system_prompt", return_value="test prompt"),
        patch("ollim_bot.tool_policy.build_main_tools", return_value=["Read", "Write"]),
        patch("ollim_bot.tool_policy.scan_all", return_value=[]),
        patch("ollim_bot.subagents.load_agent_tool_sets", return_value={}),
        patch("ollim_bot.agent_tools.build_agent_server", return_value={"type": "stdio", "command": "echo"}),
        patch("ollim_bot.agent_tools.require_report_hook", MagicMock()),
        patch("ollim_bot.hooks.auto_commit_hook", MagicMock()),
        patch("ollim_bot.hooks.state_dir_guard", MagicMock()),
    ):
        from ollim_bot.agent import Agent

        return Agent()


@pytest.fixture()
def agent():
    return _make_agent()


# ---------------------------------------------------------------------------
# Module-level helper: _with_thinking
# ---------------------------------------------------------------------------


class TestWithThinking:
    def test_off(self):
        result = _with_thinking(ClaudeAgentOptions(), "off")
        assert result.thinking == {"type": "disabled"}

    def test_adaptive(self):
        result = _with_thinking(ClaudeAgentOptions(), "adaptive")
        assert result.thinking == {"type": "adaptive"}

    def test_budget(self):
        result = _with_thinking(ClaudeAgentOptions(), "8000")
        assert result.thinking == {"type": "enabled", "budget_tokens": 8000}


# ---------------------------------------------------------------------------
# Agent construction
# ---------------------------------------------------------------------------


class TestAgentInit:
    def test_initial_state(self, agent):
        assert agent._client is None
        assert agent._fork_client is None
        assert agent._fork_session_id is None
        assert agent._compacting is False


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestProperties:
    def test_in_fork_false(self, agent):
        assert agent.in_fork is False

    def test_in_fork_true(self, agent):
        agent._fork_client = AsyncMock()
        assert agent.in_fork is True

    def test_fork_session_id(self, agent):
        assert agent.fork_session_id is None
        agent._fork_session_id = "sess-123"
        assert agent.fork_session_id == "sess-123"

    def test_is_compacting(self, agent):
        assert agent.is_compacting is False
        agent._compacting = True
        assert agent.is_compacting is True


# ---------------------------------------------------------------------------
# Session capture helpers
# ---------------------------------------------------------------------------


class TestSessionCapture:
    def test_try_capture_first_call_sets(self, agent):
        with patch("ollim_bot.agent.log_session_event"), patch("ollim_bot.agent.load_session_id", return_value=None):
            _run(agent._try_capture_fork_session("fork-1"))
        assert agent._fork_session_id == "fork-1"

    def test_try_capture_idempotent(self, agent):
        with patch("ollim_bot.agent.log_session_event"), patch("ollim_bot.agent.load_session_id", return_value=None):
            _run(agent._try_capture_fork_session("fork-1"))
            _run(agent._try_capture_fork_session("fork-2"))
        assert agent._fork_session_id == "fork-1"

    def test_capture_fork_session_returns_callback_for_fork_client(self, agent):
        mock_client = AsyncMock()
        agent._fork_client = mock_client
        cb = agent._capture_fork_session(mock_client)
        # Bound methods are recreated each access, so compare the underlying function
        assert cb.__func__ is agent._try_capture_fork_session.__func__
        assert cb.__self__ is agent

    def test_capture_fork_session_returns_none_for_main_client(self, agent):
        agent._fork_client = AsyncMock()
        other_client = AsyncMock()
        assert agent._capture_fork_session(other_client) is None

    def test_capture_fork_session_returns_none_when_no_fork(self, agent):
        assert agent._capture_fork_session(AsyncMock()) is None


# ---------------------------------------------------------------------------
# Client lifecycle: _drop_client
# ---------------------------------------------------------------------------


class TestDropClient:
    def test_sets_none_before_interrupt(self, agent):
        """_client must be set to None BEFORE interrupt/disconnect calls."""
        call_order = []

        async def record_interrupt():
            call_order.append(("interrupt", agent._client))

        async def record_disconnect():
            call_order.append(("disconnect", agent._client))

        client = AsyncMock()
        client.interrupt = record_interrupt
        client.disconnect = record_disconnect
        agent._client = client

        _run(agent._drop_client())

        assert agent._client is None
        assert len(call_order) == 2
        assert call_order[0] == ("interrupt", None)
        assert call_order[1] == ("disconnect", None)

    def test_suppresses_cli_connection_error(self, agent):
        client = AsyncMock()
        client.interrupt.side_effect = CLIConnectionError("gone")
        agent._client = client

        _run(agent._drop_client())
        assert agent._client is None

    def test_suppresses_runtime_error(self, agent):
        client = AsyncMock()
        client.interrupt = AsyncMock()
        client.disconnect.side_effect = RuntimeError("cancel scope")
        agent._client = client

        _run(agent._drop_client())
        assert agent._client is None

    def test_noop_when_no_client(self, agent):
        _run(agent._drop_client())
        assert agent._client is None


# ---------------------------------------------------------------------------
# set_model
# ---------------------------------------------------------------------------


class TestSetModel:
    def test_updates_options(self, agent):
        _run(agent.set_model("opus"))
        assert agent.options.model == "opus"

    def test_propagates_to_live_client(self, agent):
        client = AsyncMock()
        agent._client = client
        _run(agent.set_model("haiku"))
        client.set_model.assert_awaited_once_with("haiku")

    def test_propagates_to_fork_client(self, agent):
        fork = AsyncMock()
        agent._fork_client = fork
        _run(agent.set_model("sonnet"))
        fork.set_model.assert_awaited_once_with("sonnet")


# ---------------------------------------------------------------------------
# set_thinking
# ---------------------------------------------------------------------------


class TestSetThinking:
    def test_updates_options_and_drops_main(self, agent):
        client = AsyncMock()
        agent._client = client
        _run(agent.set_thinking("adaptive"))
        assert agent.options.thinking == {"type": "adaptive"}
        assert agent._client is None

    def test_drops_fork_client(self, agent):
        fork = AsyncMock()
        agent._fork_client = fork
        agent._fork_session_id = "sess-f"

        with patch("ollim_bot.agent.cancel_pending"), patch("ollim_bot.agent.set_interactive_fork"):
            _run(agent.set_thinking("off"))

        assert agent._fork_client is None
        assert agent._fork_session_id is None
        fork.interrupt.assert_awaited_once()
        fork.disconnect.assert_awaited_once()


# ---------------------------------------------------------------------------
# set_permission_mode
# ---------------------------------------------------------------------------


class TestSetPermissionMode:
    def test_propagates_to_fork_client(self, agent):
        fork = AsyncMock()
        agent._fork_client = fork
        _run(agent.set_permission_mode("acceptEdits"))
        fork.set_permission_mode.assert_awaited_once_with("acceptEdits")

    def test_propagates_to_main_client(self, agent):
        client = AsyncMock()
        agent._client = client
        _run(agent.set_permission_mode("default"))
        client.set_permission_mode.assert_awaited_once_with("default")
        assert agent.options.permission_mode == "default"

    def test_updates_options_when_no_client(self, agent):
        _run(agent.set_permission_mode(BYPASS_PERMISSIONS))
        assert agent.options.permission_mode == BYPASS_PERMISSIONS


# ---------------------------------------------------------------------------
# swap_client
# ---------------------------------------------------------------------------


class TestSwapClient:
    def test_promotes_new_client(self, agent):
        old = AsyncMock()
        agent._client = old
        new = AsyncMock()

        with (
            patch("ollim_bot.agent.save_session_id"),
            patch("ollim_bot.agent.load_session_id", return_value="old-sess"),
            patch("ollim_bot.agent.log_session_event"),
            patch("ollim_bot.agent.set_swap_in_progress"),
        ):
            _run(agent.swap_client(new, "new-sess"))

        assert agent._client is new

    def test_drops_old_client(self, agent):
        old = AsyncMock()
        agent._client = old
        new = AsyncMock()

        with (
            patch("ollim_bot.agent.save_session_id"),
            patch("ollim_bot.agent.load_session_id", return_value=None),
            patch("ollim_bot.agent.log_session_event"),
            patch("ollim_bot.agent.set_swap_in_progress"),
        ):
            _run(agent.swap_client(new, "new-sess"))

        old.interrupt.assert_awaited_once()
        old.disconnect.assert_awaited_once()

    def test_sets_swap_in_progress_flag(self, agent):
        old = AsyncMock()
        agent._client = old
        new = AsyncMock()

        progress_values = []

        with (
            patch("ollim_bot.agent.save_session_id"),
            patch("ollim_bot.agent.load_session_id", return_value=None),
            patch("ollim_bot.agent.log_session_event"),
            patch("ollim_bot.agent.set_swap_in_progress", side_effect=lambda v: progress_values.append(v)),
        ):
            _run(agent.swap_client(new, "s"))

        assert progress_values == [True, False]


# ---------------------------------------------------------------------------
# Fork lifecycle
# ---------------------------------------------------------------------------


class TestEnterInteractiveFork:
    def test_creates_fork_client(self, agent):
        mock_forked = AsyncMock()
        with (
            patch.object(agent, "create_forked_client", new_callable=AsyncMock, return_value=mock_forked),
            patch("ollim_bot.agent.runtime_config.load") as mock_cfg,
            patch("ollim_bot.agent.set_interactive_fork"),
            patch("ollim_bot.agent.touch_activity"),
        ):
            mock_cfg.return_value = MagicMock(
                fork_idle_timeout=10, model_fork=None, model_main="sonnet", thinking_fork="adaptive"
            )
            _run(agent.enter_interactive_fork())

        assert agent._fork_client is mock_forked
        assert agent._fork_session_id is None


class TestExitInteractiveFork:
    def test_exit_disconnects_and_clears(self, agent):
        fork = AsyncMock()
        agent._fork_client = fork
        agent._fork_session_id = "fork-sess"

        with (
            patch("ollim_bot.agent.cancel_pending"),
            patch("ollim_bot.agent.set_dont_ask"),
            patch("ollim_bot.agent.runtime_config.load", return_value=MagicMock(permission_mode="dontAsk")),
            patch("ollim_bot.agent.set_interactive_fork"),
        ):
            result = _run(agent.exit_interactive_fork(ForkExitAction.EXIT))

        assert result is False
        assert agent._fork_client is None
        assert agent._fork_session_id is None
        fork.interrupt.assert_awaited_once()
        fork.disconnect.assert_awaited_once()

    def test_save_promotes_fork_to_main(self, agent):
        fork = AsyncMock()
        agent._fork_client = fork
        agent._fork_session_id = "fork-sess"

        with (
            patch("ollim_bot.agent.cancel_pending"),
            patch("ollim_bot.agent.set_dont_ask"),
            patch("ollim_bot.agent.runtime_config.load", return_value=MagicMock(permission_mode="dontAsk")),
            patch("ollim_bot.agent.set_interactive_fork"),
            patch.object(agent, "swap_client", new_callable=AsyncMock) as mock_swap,
        ):
            result = _run(agent.exit_interactive_fork(ForkExitAction.SAVE))

        assert result is True
        mock_swap.assert_awaited_once_with(fork, "fork-sess")
        assert agent._fork_client is None

    def test_returns_false_when_no_fork_client(self, agent):
        with (
            patch("ollim_bot.agent.cancel_pending"),
            patch("ollim_bot.agent.set_dont_ask"),
            patch("ollim_bot.agent.runtime_config.load", return_value=MagicMock(permission_mode="dontAsk")),
            patch("ollim_bot.agent.set_interactive_fork"),
        ):
            result = _run(agent.exit_interactive_fork(ForkExitAction.EXIT))

        assert result is False


# ---------------------------------------------------------------------------
# Haiku → Sonnet auto-upgrade
# ---------------------------------------------------------------------------


class TestHaikuUpgrade:
    def test_haiku_upgraded_when_context_exceeds_limit(self, agent):
        """create_forked_client upgrades haiku→sonnet when tokens > 200k."""
        agent._last_input_tokens = 250_000
        mock_cls = MagicMock()
        mock_cls.return_value.connect = AsyncMock()
        with patch("ollim_bot.agent.ClaudeSDKClient", mock_cls):
            _run(agent.create_forked_client(model="haiku"))

        assert agent._last_fork_upgraded is True
        opts = mock_cls.call_args[0][0]
        assert opts.model == "sonnet"

    def test_haiku_not_upgraded_when_context_below_limit(self, agent):
        """create_forked_client keeps haiku when tokens < 200k."""
        agent._last_input_tokens = 150_000
        client = AsyncMock()
        with patch("ollim_bot.agent.ClaudeSDKClient", return_value=client):
            client.connect = AsyncMock()
            _run(agent.create_forked_client(model="haiku"))

        assert agent._last_fork_upgraded is False

    def test_sonnet_not_upgraded_regardless_of_tokens(self, agent):
        """create_forked_client never upgrades sonnet."""
        agent._last_input_tokens = 500_000
        client = AsyncMock()
        with patch("ollim_bot.agent.ClaudeSDKClient", return_value=client):
            client.connect = AsyncMock()
            _run(agent.create_forked_client(model="sonnet"))

        assert agent._last_fork_upgraded is False

    def test_no_tokens_tracked_skips_upgrade(self, agent):
        """create_forked_client skips upgrade when no token data."""
        assert agent._last_input_tokens is None
        client = AsyncMock()
        with patch("ollim_bot.agent.ClaudeSDKClient", return_value=client):
            client.connect = AsyncMock()
            _run(agent.create_forked_client(model="haiku"))

        assert agent._last_fork_upgraded is False
