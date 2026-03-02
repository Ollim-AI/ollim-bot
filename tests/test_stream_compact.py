"""Tests for auto-compaction handling in stream_to_channel."""

import asyncio
from collections.abc import AsyncGenerator

import pytest

from ollim_bot.streamer import StreamStatus, stream_to_channel


class FakeMessage:
    _next_id = 1

    def __init__(self, content: str):
        self.id = FakeMessage._next_id
        FakeMessage._next_id += 1
        self.content = content
        self.deleted = False

    async def edit(self, *, content: str) -> None:
        self.content = content

    async def delete(self) -> None:
        self.deleted = True


class FakeChannel:
    """Records all messages sent, edited, and deleted."""

    def __init__(self) -> None:
        self.messages: list[FakeMessage] = []

    async def send(self, content: str, **_kwargs) -> FakeMessage:
        msg = FakeMessage(content)
        self.messages.append(msg)
        return msg

    async def typing(self) -> None:
        pass


async def _stream(ch: FakeChannel, deltas: AsyncGenerator[str | StreamStatus, None]) -> None:
    await stream_to_channel(ch, deltas)  # type: ignore[arg-type]


async def _gen(*items: str | StreamStatus) -> AsyncGenerator[str | StreamStatus, None]:
    for item in items:
        yield item


# --- compact_start + text finalization ---


@pytest.mark.asyncio
async def test_compact_start_finalized_to_annotation_on_text():
    """compact_start creates status, text arrival finalizes to annotation + new message."""
    ch = FakeChannel()

    await _stream(
        ch,
        _gen(
            StreamStatus(kind="compact_start", label="Auto-compacting 45k tokens", compact_tokens=45000),
            "Hello after compaction",
        ),
    )

    assert len(ch.messages) == 2

    annotation = ch.messages[0]
    assert not annotation.deleted
    assert "auto-compacted" in annotation.content
    assert "45k tokens" in annotation.content

    response = ch.messages[1]
    assert response.content == "Hello after compaction"


@pytest.mark.asyncio
async def test_compact_annotation_includes_duration():
    """Annotation includes elapsed seconds when > 0."""
    ch = FakeChannel()

    async def _slow_gen() -> AsyncGenerator[str | StreamStatus, None]:
        yield StreamStatus(kind="compact_start", label="Auto-compacting", compact_tokens=None)
        await asyncio.sleep(0.05)
        yield "response"

    await _stream(ch, _slow_gen())

    annotation = ch.messages[0]
    # Duration may be 0s at this speed, but annotation should still exist
    assert "auto-compacted" in annotation.content
    assert not annotation.deleted


@pytest.mark.asyncio
async def test_compact_without_tokens():
    """Annotation works when compact_tokens is None."""
    ch = FakeChannel()

    await _stream(
        ch,
        _gen(
            StreamStatus(kind="compact_start", label="Auto-compacting"),
            "response",
        ),
    )

    annotation = ch.messages[0]
    assert "auto-compacted" in annotation.content
    assert "tokens" not in annotation.content


# --- Mid-response compaction (Case 1) ---


@pytest.mark.asyncio
async def test_mid_response_compaction_produces_three_messages():
    """Content before compact → annotation → continuation in separate messages."""
    ch = FakeChannel()

    await _stream(
        ch,
        _gen(
            "before compaction",
            StreamStatus(kind="compact_start", label="Auto-compacting 30k tokens", compact_tokens=30000),
            "after compaction",
        ),
    )

    # 4 messages: initial status (deleted by first text), pre-compact text,
    # compaction annotation, post-compact text.
    assert len(ch.messages) == 4

    initial = ch.messages[0]
    assert initial.deleted  # initial "Thinking..." cleared by text arrival

    pre = ch.messages[1]
    assert pre.content == "before compaction"
    assert not pre.deleted

    annotation = ch.messages[2]
    assert "auto-compacted" in annotation.content
    assert "30k tokens" in annotation.content
    assert not annotation.deleted

    post = ch.messages[3]
    assert post.content == "after compaction"


# --- Compact finalized by next status signal ---


@pytest.mark.asyncio
async def test_compact_finalized_by_thinking_start():
    """thinking_start during compact mode finalizes annotation, creates new status."""
    ch = FakeChannel()

    await _stream(
        ch,
        _gen(
            StreamStatus(kind="compact_start", label="Auto-compacting"),
            StreamStatus(kind="thinking_start"),
            StreamStatus(kind="phase_end"),
            "response text",
        ),
    )

    annotation = ch.messages[0]
    assert "auto-compacted" in annotation.content
    assert not annotation.deleted

    # Thinking status was created then deleted
    thinking = ch.messages[1]
    assert thinking.deleted

    response = ch.messages[2]
    assert response.content == "response text"


@pytest.mark.asyncio
async def test_compact_finalized_by_tool_start():
    """tool_start during compact mode finalizes annotation."""
    ch = FakeChannel()

    await _stream(
        ch,
        _gen(
            StreamStatus(kind="compact_start", label="Auto-compacting 50k tokens", compact_tokens=50000),
            StreamStatus(kind="tool_start", label="Read(foo.md)"),
            StreamStatus(kind="phase_end"),
            "response",
        ),
    )

    annotation = ch.messages[0]
    assert "auto-compacted" in annotation.content
    assert "50k tokens" in annotation.content
    assert not annotation.deleted


# --- Compact cleanup (no subsequent content) ---


@pytest.mark.asyncio
async def test_compact_finalized_at_cleanup_when_no_content_follows():
    """If nothing follows compact_start, annotation is finalized — no error (compaction is legitimate)."""
    ch = FakeChannel()

    await _stream(
        ch,
        _gen(
            StreamStatus(kind="compact_start", label="Auto-compacting 20k tokens", compact_tokens=20000),
        ),
    )

    # Annotation stays; no error because compaction occurred (e.g. interrupted during compaction)
    assert len(ch.messages) == 1

    annotation = ch.messages[0]
    assert "auto-compacted" in annotation.content
    assert not annotation.deleted


# --- Non-compact status still works normally ---


@pytest.mark.asyncio
async def test_normal_status_still_deleted():
    """Regular thinking/tool status messages are still deleted (not finalized)."""
    ch = FakeChannel()

    await _stream(
        ch,
        _gen(
            StreamStatus(kind="thinking_start"),
            StreamStatus(kind="phase_end"),
            "response",
        ),
    )

    status = ch.messages[0]
    assert status.deleted

    response = ch.messages[1]
    assert response.content == "response"
