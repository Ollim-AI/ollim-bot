"""Tests for agent_streaming — streaming response consumer (TDD: RED phase).

These tests define the contract for stream_response() and build_image_query()
before the implementation exists.
"""

from __future__ import annotations

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    CLIConnectionError,
    ResultMessage,
    SystemMessage,
    TextBlock,
)
from claude_agent_sdk.types import StreamEvent

from ollim_bot.agent_streaming import build_image_query, stream_response
from ollim_bot.streamer import StreamStatus

# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------


class FakeClient:
    """Duck-typed ClaudeSDKClient for testing stream_response.

    Each positional arg is a "pass" — a list of SDK messages yielded by one
    receive_response() call.  Exceptions in the list are raised mid-iteration.
    """

    def __init__(self, *passes: list) -> None:
        self._passes = list(passes)
        self._pass_idx = 0
        self.query_calls: list = []
        self.interrupted = False

    async def query(self, message) -> None:
        self.query_calls.append(message)

    def receive_response(self):
        events = self._passes[self._pass_idx]
        self._pass_idx += 1

        async def _gen():
            for e in events:
                if isinstance(e, BaseException):
                    raise e
                yield e

        return _gen()

    async def interrupt(self) -> None:
        self.interrupted = True


def _result(session_id: str = "s1", *, result: str | None = None) -> ResultMessage:
    return ResultMessage(
        subtype="result",
        duration_ms=0,
        duration_api_ms=0,
        is_error=False,
        num_turns=1,
        session_id=session_id,
        result=result,
    )


def _stream_event(session_id: str = "s1", *, text: str = "x") -> StreamEvent:
    return StreamEvent(
        uuid="u1",
        session_id=session_id,
        event={"type": "content_block_delta", "delta": {"text": text}},
    )


def _stream(client: FakeClient, message: str, **kwargs):
    return stream_response(client, message, **kwargs)  # type: ignore[arg-type]


async def _collect(gen) -> list:
    return [item async for item in gen]


# ---------------------------------------------------------------------------
# stream_response — text streaming
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_text_via_stream_events():
    """StreamEvent with text_delta → text yielded."""
    client = FakeClient(
        [
            _stream_event(text="hello"),
            _stream_event(text=" world"),
            _result(),
        ]
    )

    items = await _collect(_stream(client, "hi"))

    text = "".join(i for i in items if isinstance(i, str))
    assert "hello" in text
    assert " world" in text


@pytest.mark.asyncio
async def test_fallback_to_assistant_message():
    """No StreamEvent → falls back to AssistantMessage text blocks."""
    client = FakeClient(
        [
            AssistantMessage(content=[TextBlock(text="fallback")], model="claude-sonnet-4-6"),
            _result(),
        ]
    )

    items = await _collect(_stream(client, "hi"))

    assert "fallback" in items


@pytest.mark.asyncio
async def test_fallback_to_result_text():
    """No StreamEvent or AssistantMessage → ResultMessage.result."""
    client = FakeClient(
        [
            _result(result="result text"),
        ]
    )

    items = await _collect(_stream(client, "hi"))

    assert items == ["result text"]


@pytest.mark.asyncio
async def test_no_output_when_empty():
    """ResultMessage with no .result → nothing yielded."""
    client = FakeClient([_result()])

    items = await _collect(_stream(client, "hi"))

    assert items == []


# ---------------------------------------------------------------------------
# stream_response — auto-compaction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_compaction_resends_query():
    """compact_boundary → compact_start status + client.query called again."""
    client = FakeClient(
        # First pass: compact boundary
        [
            SystemMessage(subtype="compact_boundary", data={"compact_metadata": {}}),
            _result(),
        ],
        # Second pass: normal response after compaction
        [
            _stream_event(text="after compact"),
            _result(),
        ],
    )

    items = await _collect(_stream(client, "hi"))

    statuses = [i for i in items if isinstance(i, StreamStatus) and i.kind == "compact_start"]
    assert len(statuses) == 1
    assert len(client.query_calls) == 2  # initial + re-send


@pytest.mark.asyncio
async def test_auto_compaction_includes_token_count():
    """compact_metadata.pre_tokens → StreamStatus.compact_tokens."""
    client = FakeClient(
        [
            SystemMessage(
                subtype="compact_boundary",
                data={"compact_metadata": {"pre_tokens": 50000}},
            ),
            _result(),
        ],
        [_result()],
    )

    items = await _collect(_stream(client, "hi"))

    statuses = [i for i in items if isinstance(i, StreamStatus)]
    assert statuses[0].compact_tokens == 50000


# ---------------------------------------------------------------------------
# stream_response — fork session capture
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fork_session_callback_called():
    """on_fork_session called once with session_id from first StreamEvent."""
    captured: list[str] = []
    client = FakeClient(
        [
            _stream_event(session_id="fork-123", text="a"),
            _stream_event(session_id="fork-123", text="b"),
            _result(session_id="fork-123"),
        ]
    )

    await _collect(_stream(client, "hi", on_fork_session=captured.append))

    assert captured == ["fork-123"]


@pytest.mark.asyncio
async def test_fork_session_none_no_crash():
    """on_fork_session=None + StreamEvent → no crash."""
    client = FakeClient([_stream_event(text="x"), _result()])

    items = await _collect(_stream(client, "hi", on_fork_session=None))

    assert any(isinstance(i, str) for i in items)


# ---------------------------------------------------------------------------
# stream_response — fork interrupt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fork_interrupt_triggers(monkeypatch):
    """enter_fork_requested() True → client.interrupt(), text skipped."""
    monkeypatch.setattr(
        "ollim_bot.agent_streaming.enter_fork_requested",
        lambda: True,
    )
    client = FakeClient(
        [
            _stream_event(text="should be skipped"),
            _stream_event(text="also skipped"),
            _result(),
        ]
    )

    items = await _collect(_stream(client, "hi"))

    assert client.interrupted
    text_items = [i for i in items if isinstance(i, str)]
    assert text_items == []


@pytest.mark.asyncio
async def test_cli_error_suppressed_on_fork_interrupt(monkeypatch):
    """interrupt() raises CLIConnectionError during fork interrupt → suppressed."""
    monkeypatch.setattr(
        "ollim_bot.agent_streaming.enter_fork_requested",
        lambda: True,
    )

    class _ErrorOnInterrupt(FakeClient):
        async def interrupt(self) -> None:
            self.interrupted = True
            raise CLIConnectionError("connection lost")

    client = _ErrorOnInterrupt([_stream_event(text="x"), _result()])

    # Should not raise
    items = await _collect(_stream(client, "hi"))

    assert client.interrupted
    assert not any(isinstance(i, str) for i in items)


@pytest.mark.asyncio
async def test_cli_error_propagated_without_interrupt():
    """CLIConnectionError during receive_response → propagates."""
    client = FakeClient([CLIConnectionError("connection lost")])

    with pytest.raises(CLIConnectionError):
        await _collect(_stream(client, "hi"))


# ---------------------------------------------------------------------------
# stream_response — on_result_session callback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_result_session_called():
    """on_result_session callback receives (client, ResultMessage) once."""
    calls: list[tuple] = []
    client = FakeClient(
        [
            _stream_event(text="x"),
            _result(session_id="s1", result="done"),
        ]
    )

    await _collect(_stream(client, "hi", on_result_session=lambda c, m: calls.append((c, m))))

    assert len(calls) == 1
    assert calls[0][0] is client
    assert calls[0][1].session_id == "s1"


# ---------------------------------------------------------------------------
# build_image_query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_image_query():
    """build_image_query returns proper SDK user message envelope."""
    gen = build_image_query(
        "describe this",
        [
            {"media_type": "image/png", "data": "abc123"},
        ],
    )

    items = [item async for item in gen]

    assert len(items) == 1
    envelope = items[0]
    assert envelope["type"] == "user"
    msg = envelope["message"]
    assert msg["role"] == "user"
    assert len(msg["content"]) == 2  # image + text
    assert msg["content"][0]["type"] == "image"
    assert msg["content"][0]["source"]["data"] == "abc123"
    assert msg["content"][1]["type"] == "text"
    assert msg["content"][1]["text"] == "describe this"
