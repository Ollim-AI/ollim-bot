"""Tests for context usage warning in stream_to_channel."""

from collections.abc import AsyncGenerator

import pytest
from conftest import FakeChannel

from ollim_bot.streamer import StreamStatus, stream_to_channel


async def _stream(ch: FakeChannel, deltas: AsyncGenerator[str | StreamStatus, None]) -> None:
    await stream_to_channel(ch, deltas)  # type: ignore[arg-type]


async def _gen(*items: str | StreamStatus) -> AsyncGenerator[str | StreamStatus, None]:
    for item in items:
        yield item


@pytest.mark.asyncio
async def test_context_warning_shown_at_60_pct():
    """Warning annotation appears after response text when at 60%+."""
    ch = FakeChannel()

    await _stream(
        ch,
        _gen(
            "response text",
            StreamStatus(kind="context_warning", input_tokens=124_000, context_pct=62),
        ),
    )

    # Status promoted to text + warning annotation
    assert len(ch.messages) == 2
    assert ch.messages[0].content == "response text"
    assert "context: 62%" in ch.messages[1].content
    assert "124k" in ch.messages[1].content
    assert "consider /compact" in ch.messages[1].content


@pytest.mark.asyncio
async def test_context_warning_not_shown_below_threshold():
    """No warning when context_warning is not yielded (below threshold)."""
    ch = FakeChannel()

    await _stream(ch, _gen("response text"))

    # Only status promoted to text — no warning
    assert len(ch.messages) == 1
    assert ch.messages[0].content == "response text"


@pytest.mark.asyncio
async def test_context_warning_escalates_at_80_pct():
    """Warning text changes at 80%+ threshold."""
    ch = FakeChannel()

    await _stream(
        ch,
        _gen(
            "response text",
            StreamStatus(kind="context_warning", input_tokens=162_000, context_pct=81),
        ),
    )

    warning = ch.messages[1]
    assert "context: 81%" in warning.content
    assert "162k" in warning.content
    assert "compaction soon" in warning.content
    assert "/compact recommended" in warning.content


@pytest.mark.asyncio
async def test_context_warning_not_shown_after_compaction():
    """Warning not shown when response includes compaction (post-compact context is small)."""
    ch = FakeChannel()

    await _stream(
        ch,
        _gen(
            StreamStatus(kind="compact_start", label="Auto-compacting 160k tokens", compact_tokens=160_000),
            "post-compaction response",
            # No context_warning yielded — stream_response skips it when compacted=True
        ),
    )

    # Compaction annotation + response — no warning
    contents = [m.content for m in ch.messages]
    assert any("auto-compacted" in c for c in contents)
    assert not any("consider /compact" in c for c in contents)
    assert not any("compaction soon" in c for c in contents)
