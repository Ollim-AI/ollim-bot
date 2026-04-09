"""Tests for reflections.py — prompt building, path generation, and fork integration."""

import asyncio
import contextlib
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from ollim_bot.fork_state import BgForkTracking
from ollim_bot.forks import run_agent_background
from ollim_bot.reflections import build_reflection_prompt, reflection_path
from ollim_bot.scheduling.reminders import Reminder
from ollim_bot.scheduling.routines import Routine

_TS = datetime(2026, 4, 8, 7, 2, 0, tzinfo=UTC)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --- reflection_path ---


def test_reflection_path_filesystem_safe(data_dir):
    ts = datetime(2026, 4, 8, 7, 2, 0, tzinfo=UTC)

    result = reflection_path("morning-checkin", ts)

    assert result.name == "2026-04-08T07-02-00Z.md"
    assert result.parent.name == "morning-checkin"
    assert "reflections" in str(result)


# --- build_reflection_prompt ---


def test_build_reflection_prompt_success(data_dir):
    target = reflection_path("abc123", _TS)
    prompt = build_reflection_prompt(
        "[routine-bg:abc123]",
        "abc123",
        "triage email, check calendar",
        target,
        _TS,
        report_message="3 tasks overdue",
    )

    assert "abc123" in prompt
    assert "triage email, check calendar" in prompt
    assert "completed" in prompt
    assert "3 tasks overdue" in prompt


def test_build_reflection_prompt_timeout(data_dir):
    target = reflection_path("abc123", _TS)
    prompt = build_reflection_prompt(
        "[routine-bg:abc123]",
        "abc123",
        "morning routine",
        target,
        _TS,
        timed_out=True,
        timeout_seconds=600,
    )

    assert "timed out after 10 minutes" in prompt


def test_build_reflection_prompt_failure(data_dir):
    target = reflection_path("abc123", _TS)
    prompt = build_reflection_prompt(
        "[routine-bg:abc123]",
        "abc123",
        "morning routine",
        target,
        _TS,
        error_info="CLIConnectionError: connection lost",
    )

    assert "CLIConnectionError: connection lost" in prompt
    assert "failed:" in prompt


def test_build_reflection_prompt_no_report(data_dir):
    target = reflection_path("abc123", _TS)
    prompt = build_reflection_prompt("[routine-bg:abc123]", "abc123", "morning routine", target, _TS)

    assert "No report filed." in prompt


# --- Dataclass reflect field ---


def test_routine_reflect_field_defaults_true():
    routine = Routine.new(message="test", cron="0 9 * * *")

    assert routine.reflect is True


def test_routine_reflect_false_roundtrip(data_dir):
    from ollim_bot.scheduling.routines import append_routine, list_routines

    r = Routine.new(message="test", cron="0 9 * * *", reflect=False)
    append_routine(r)

    result = list_routines()

    assert len(result) == 1
    assert result[0].reflect is False


def test_reminder_reflect_field_defaults_true():
    reminder = Reminder.new(message="test", delay_minutes=5)

    assert reminder.reflect is True


def test_webhook_reflect_field_roundtrip(data_dir):
    from ollim_bot.webhook import list_webhooks

    webhooks_dir = data_dir / "webhooks"
    webhooks_dir.mkdir()
    (webhooks_dir / "test-hook.md").write_text(
        "---\n"
        'id: "test-hook"\n'
        "reflect: false\n"
        "fields:\n"
        "  type: object\n"
        "  properties:\n"
        "    repo:\n"
        "      type: string\n"
        "---\n"
        "CI result for {repo}.\n"
    )

    specs = list_webhooks()

    assert len(specs) == 1
    assert specs[0].reflect is False


# --- BgForkTracking.report_message ---


def test_bg_tracking_report_message_default_none():
    tracking = BgForkTracking()

    assert tracking.report_message is None


# --- Fork integration ---


def _make_agent(*, run_side_effect=None):
    """Build a mock agent matching the pattern used in test_forks.py."""
    from ollim_bot.channel import init_channel

    channel = AsyncMock()
    channel.send = AsyncMock()
    init_channel(channel)

    agent = AsyncMock()
    agent.lock = MagicMock(return_value=asyncio.Lock())

    client = AsyncMock()
    agent.create_forked_client = AsyncMock(return_value=client)
    agent.create_isolated_client = AsyncMock(return_value=client)

    if run_side_effect:
        agent.run_on_client = AsyncMock(side_effect=run_side_effect)
    else:
        agent.run_on_client = AsyncMock(return_value="fork-session-id")

    return agent


def test_bg_fork_spawns_reflection_on_success(monkeypatch, data_dir):
    import ollim_bot.runtime_config as runtime_config

    monkeypatch.setattr(runtime_config, "load", lambda: runtime_config.RuntimeConfig())

    agent = _make_agent()

    with patch("ollim_bot.forks.run_reflection_fork", new_callable=AsyncMock) as mock_reflect:
        _run(
            run_agent_background(
                agent,
                "[routine-bg:test] do stuff",
                reflect=True,
                description="test routine",
            )
        )

    mock_reflect.assert_awaited_once()
    call_kwargs = mock_reflect.call_args
    assert call_kwargs[0][1] == "[routine-bg:test]"  # tag
    assert call_kwargs[0][2] == "test"  # item_id
    assert call_kwargs[0][3] == "test routine"  # description


def test_bg_fork_spawns_reflection_on_timeout(monkeypatch, data_dir):
    import ollim_bot.runtime_config as runtime_config

    monkeypatch.setattr(runtime_config, "load", lambda: runtime_config.RuntimeConfig(bg_fork_timeout=0))

    async def hang_forever(*args, **kwargs):
        await asyncio.sleep(3600)

    agent = _make_agent(run_side_effect=hang_forever)

    with patch("ollim_bot.forks.run_reflection_fork", new_callable=AsyncMock) as mock_reflect:
        _run(
            run_agent_background(
                agent,
                "[routine-bg:test] do stuff",
                reflect=True,
                description="test routine",
            )
        )

    mock_reflect.assert_awaited_once()
    _, kwargs = mock_reflect.call_args
    assert kwargs["timed_out"] is True


def test_bg_fork_spawns_reflection_on_exception(monkeypatch, data_dir):
    import ollim_bot.runtime_config as runtime_config

    monkeypatch.setattr(runtime_config, "load", lambda: runtime_config.RuntimeConfig())

    async def raise_error(*args, **kwargs):
        raise ConnectionError("connection lost")

    agent = _make_agent(run_side_effect=raise_error)

    with (
        patch("ollim_bot.forks.run_reflection_fork", new_callable=AsyncMock) as mock_reflect,
        contextlib.suppress(ConnectionError),
    ):
        _run(
            run_agent_background(
                agent,
                "[routine-bg:test] do stuff",
                reflect=True,
                description="test routine",
            )
        )

    mock_reflect.assert_awaited_once()
    _, kwargs = mock_reflect.call_args
    assert "ConnectionError" in kwargs["error_info"]


def test_bg_fork_skips_reflection_when_disabled(monkeypatch, data_dir):
    import ollim_bot.runtime_config as runtime_config

    monkeypatch.setattr(runtime_config, "load", lambda: runtime_config.RuntimeConfig())

    agent = _make_agent()

    with patch("ollim_bot.forks.run_reflection_fork", new_callable=AsyncMock) as mock_reflect:
        _run(
            run_agent_background(
                agent,
                "[routine-bg:test] do stuff",
                reflect=False,
            )
        )

    mock_reflect.assert_not_awaited()


def test_reflection_failure_does_not_propagate(monkeypatch, data_dir):
    import ollim_bot.runtime_config as runtime_config

    monkeypatch.setattr(runtime_config, "load", lambda: runtime_config.RuntimeConfig())

    agent = _make_agent()

    async def reflection_explodes(*args, **kwargs):
        raise RuntimeError("reflection boom")

    with patch("ollim_bot.forks.run_reflection_fork", new_callable=AsyncMock) as mock_reflect:
        mock_reflect.side_effect = reflection_explodes
        _run(
            run_agent_background(
                agent,
                "[routine-bg:test] do stuff",
                reflect=True,
                description="test",
            )
        )

    # No exception raised — bg fork completed normally


def test_reflection_cancelled_error_does_not_propagate(monkeypatch, data_dir):
    import ollim_bot.runtime_config as runtime_config

    monkeypatch.setattr(runtime_config, "load", lambda: runtime_config.RuntimeConfig())

    agent = _make_agent()

    async def reflection_cancelled(*args, **kwargs):
        raise asyncio.CancelledError()

    with patch("ollim_bot.forks.run_reflection_fork", new_callable=AsyncMock) as mock_reflect:
        mock_reflect.side_effect = reflection_cancelled
        _run(
            run_agent_background(
                agent,
                "[routine-bg:test] do stuff",
                reflect=True,
                description="test",
            )
        )

    # No exception raised — CancelledError suppressed
