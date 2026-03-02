"""Tests for StreamParser — tool label rendering and denial marking."""

import pytest

from ollim_bot.permissions import _denied_labels, is_denied, reset
from ollim_bot.streamer import StreamParser, StreamStatus


def _block_start(block_type: str, **extra: object) -> dict:
    return {"type": "content_block_start", "content_block": {"type": block_type, **extra}}


def _block_stop() -> dict:
    return {"type": "content_block_stop"}


def _text_delta(text: str) -> dict:
    return {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}}


def _input_delta(json_fragment: str) -> dict:
    return {"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": json_fragment}}


async def _collect(parser: StreamParser, event: dict) -> list[str | StreamStatus]:
    return [item async for item in parser.feed(event)]


async def _drain(parser: StreamParser) -> list[str | StreamStatus]:
    return [item async for item in parser.drain()]


# --- Single tool label rendering ---


@pytest.mark.asyncio
async def test_tool_label_rendered_after_text_block_start():
    """Tool label appears when the next non-tool content block starts."""
    reset()
    parser = StreamParser()

    await _collect(parser, _block_start("tool_use", name="Read", id="1"))
    await _collect(parser, _input_delta('{"file_path": "/a/b/c.md"}'))
    items = await _collect(parser, _block_stop())

    assert any(isinstance(i, StreamStatus) and i.kind == "tool_start" for i in items)

    items = await _collect(parser, _block_start("text"))

    labels = [i for i in items if isinstance(i, str) and "Read" in i]
    assert len(labels) == 1
    assert "denied" not in labels[0]


@pytest.mark.asyncio
async def test_denied_tool_shows_strikethrough():
    """A denied tool label gets strikethrough and '— denied' suffix."""
    reset()
    _denied_labels.add("Read(b/c.md)")
    parser = StreamParser()

    await _collect(parser, _block_start("tool_use", name="Read", id="1"))
    await _collect(parser, _input_delta('{"file_path": "/a/b/c.md"}'))
    await _collect(parser, _block_stop())

    items = await _collect(parser, _block_start("text"))

    labels = [i for i in items if isinstance(i, str) and "Read" in i]
    assert len(labels) == 1
    assert "~~" in labels[0]
    assert "denied" in labels[0]


@pytest.mark.asyncio
async def test_drain_renders_pending_labels():
    """Labels are rendered on drain() at stream end."""
    reset()
    parser = StreamParser()

    await _collect(parser, _block_start("tool_use", name="Read", id="1"))
    await _collect(parser, _input_delta('{"file_path": "/a/b/c.md"}'))
    await _collect(parser, _block_stop())

    items = await _drain(parser)

    labels = [i for i in items if isinstance(i, str) and "Read" in i]
    assert len(labels) == 1


# --- Multi-tool deferred rendering ---


@pytest.mark.asyncio
async def test_multi_tool_labels_deferred_until_text():
    """Multiple tool labels are deferred and rendered together when text arrives."""
    reset()
    parser = StreamParser()

    # Tool A
    await _collect(parser, _block_start("tool_use", name="Read", id="1"))
    await _collect(parser, _input_delta('{"file_path": "/a/b/foo.md"}'))
    await _collect(parser, _block_stop())

    # Tool B — triggers drain(defer=True) so A's label is NOT rendered yet
    items_b_start = await _collect(parser, _block_start("tool_use", name="Write", id="2"))
    labels_early = [i for i in items_b_start if isinstance(i, str) and ("Read" in i or "Write" in i)]
    assert labels_early == [], "Labels should be deferred when another tool follows"

    await _collect(parser, _input_delta('{"file_path": "/a/b/bar.md", "content": "x"}'))
    await _collect(parser, _block_stop())

    # Text block — triggers drain(defer=False), renders both labels
    items = await _collect(parser, _block_start("text"))

    labels = [i for i in items if isinstance(i, str) and ("-#" in i)]
    assert len(labels) == 2
    assert any("Read" in lab for lab in labels)
    assert any("Write" in lab for lab in labels)


@pytest.mark.asyncio
async def test_multi_tool_denied_label_matched_correctly():
    """In a multi-tool turn, only the denied tool gets strikethrough."""
    reset()
    _denied_labels.add("Write(b/bar.md)")
    parser = StreamParser()

    # Tool A (allowed)
    await _collect(parser, _block_start("tool_use", name="Read", id="1"))
    await _collect(parser, _input_delta('{"file_path": "/a/b/foo.md"}'))
    await _collect(parser, _block_stop())

    # Tool B (denied)
    await _collect(parser, _block_start("tool_use", name="Write", id="2"))
    await _collect(parser, _input_delta('{"file_path": "/a/b/bar.md", "content": "x"}'))
    await _collect(parser, _block_stop())

    # Text block renders both
    items = await _collect(parser, _block_start("text"))
    labels = [i for i in items if isinstance(i, str) and "-#" in i]

    read_label = next(lab for lab in labels if "Read" in lab)
    write_label = next(lab for lab in labels if "Write" in lab)

    assert "denied" not in read_label
    assert "denied" in write_label
    assert "~~" in write_label


# --- is_denied consumes entry ---


def test_is_denied_consumes_label():
    reset()
    _denied_labels.add("Read(foo.md)")

    assert is_denied("Read(foo.md)") is True
    assert is_denied("Read(foo.md)") is False


def test_is_denied_returns_false_for_unknown():
    reset()

    assert is_denied("Read(foo.md)") is False
