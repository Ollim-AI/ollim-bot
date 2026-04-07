"""Tests for StreamParser — tool label rendering, denial marking, and thinking suppression."""

import pytest

from ollim_bot.permissions import _denied_labels, _errored_labels, _surfaced_labels, is_denied, reset
from ollim_bot.streamer import StreamParser, StreamStatus


def _block_start(block_type: str, **extra: object) -> dict:
    return {"type": "content_block_start", "content_block": {"type": block_type, **extra}}


def _block_stop() -> dict:
    return {"type": "content_block_stop"}


def _text_delta(text: str) -> dict:
    return {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}}


def _thinking_delta(thinking: str) -> dict:
    return {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": thinking}}


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


@pytest.mark.asyncio
async def test_agent_tool_gets_descriptive_label():
    """Agent tool renders as 'agent_name(description)', not bare 'Agent'."""
    reset()
    parser = StreamParser()

    await _collect(parser, _block_start("tool_use", name="Agent", id="1"))
    await _collect(parser, _input_delta('{"name": "guide", "description": "search for docs"}'))
    await _collect(parser, _block_stop())

    items = await _collect(parser, _block_start("text"))

    labels = [i for i in items if isinstance(i, str) and "-#" in i]
    assert len(labels) == 1
    assert "guide(search for docs)" in labels[0]
    assert "Agent" not in labels[0]


# --- Multi-tool deferred rendering ---


@pytest.mark.asyncio
async def test_multi_tool_labels_rendered_progressively():
    """Tool labels render progressively — each flushes when the next tool starts."""
    reset()
    parser = StreamParser()

    # Tool A
    await _collect(parser, _block_start("tool_use", name="Read", id="1"))
    await _collect(parser, _input_delta('{"file_path": "/a/b/foo.md"}'))
    await _collect(parser, _block_stop())

    # Tool B — drain flushes A's label immediately
    items_b_start = await _collect(parser, _block_start("tool_use", name="Write", id="2"))
    labels_early = [i for i in items_b_start if isinstance(i, str) and "Read" in i]
    assert len(labels_early) == 1, "Tool A label should flush when Tool B starts"

    await _collect(parser, _input_delta('{"file_path": "/a/b/bar.md", "content": "x"}'))
    await _collect(parser, _block_stop())

    # Text block — only Tool B's label remains to flush
    items = await _collect(parser, _block_start("text"))

    labels = [i for i in items if isinstance(i, str) and "-#" in i]
    assert len(labels) == 1
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

    # Tool B (denied) — also flushes Tool A's label
    items_b = await _collect(parser, _block_start("tool_use", name="Write", id="2"))
    read_label = next(i for i in items_b if isinstance(i, str) and "Read" in i)
    assert "denied" not in read_label

    await _collect(parser, _input_delta('{"file_path": "/a/b/bar.md", "content": "x"}'))
    await _collect(parser, _block_stop())

    # Text block renders Tool B's label
    items = await _collect(parser, _block_start("text"))
    labels = [i for i in items if isinstance(i, str) and "-#" in i]

    write_label = next(lab for lab in labels if "Write" in lab)
    assert "denied" in write_label
    assert "~~" in write_label


@pytest.mark.asyncio
async def test_errored_tool_shows_strikethrough():
    """An errored tool label gets strikethrough and '— error' suffix."""
    reset()
    _errored_labels.add("Read(b/c.md)")
    parser = StreamParser()

    await _collect(parser, _block_start("tool_use", name="Read", id="1"))
    await _collect(parser, _input_delta('{"file_path": "/a/b/c.md"}'))
    await _collect(parser, _block_stop())

    items = await _collect(parser, _block_start("text"))

    labels = [i for i in items if isinstance(i, str) and "Read" in i]
    assert len(labels) == 1
    assert "~~" in labels[0]
    assert "error" in labels[0]
    assert "denied" not in labels[0]


@pytest.mark.asyncio
async def test_errored_label_does_not_shadow_denied():
    """A denied label takes precedence over errored — 'denied' shown, not 'error'."""
    reset()
    _denied_labels.add("Read(b/c.md)")
    _errored_labels.add("Read(b/c.md)")
    parser = StreamParser()

    await _collect(parser, _block_start("tool_use", name="Read", id="1"))
    await _collect(parser, _input_delta('{"file_path": "/a/b/c.md"}'))
    await _collect(parser, _block_stop())

    items = await _collect(parser, _block_start("text"))

    labels = [i for i in items if isinstance(i, str) and "Read" in i]
    assert len(labels) == 1
    assert "denied" in labels[0]
    assert "error" not in labels[0]


# --- is_denied consumes entry ---


def test_is_denied_consumes_label():
    reset()
    _denied_labels.add("Read(foo.md)")

    assert is_denied("Read(foo.md)") is True
    assert is_denied("Read(foo.md)") is False


def test_is_denied_returns_false_for_unknown():
    reset()

    assert is_denied("Read(foo.md)") is False


# --- Thinking block suppression ---


@pytest.mark.asyncio
async def test_thinking_block_yields_status_not_text():
    """Thinking blocks yield thinking_start/phase_end signals, never text content."""
    parser = StreamParser()

    items = await _collect(parser, _block_start("thinking"))
    assert items == [StreamStatus(kind="thinking_start")]

    items = await _collect(parser, _thinking_delta("Let me reason about this..."))
    assert items == []

    items = await _collect(parser, _thinking_delta("The answer should be..."))
    assert items == []

    items = await _collect(parser, _block_stop())
    assert items == [StreamStatus(kind="phase_end")]


@pytest.mark.asyncio
async def test_thinking_delta_with_text_field_still_hidden():
    """Even if a thinking delta has a 'text' field, it must not leak through."""
    parser = StreamParser()

    await _collect(parser, _block_start("thinking"))

    # Simulate a thinking delta that also carries a text field
    event = {
        "type": "content_block_delta",
        "delta": {"type": "thinking_delta", "thinking": "secret thought", "text": "secret thought"},
    }
    items = await _collect(parser, event)
    assert items == []

    await _collect(parser, _block_stop())


@pytest.mark.asyncio
async def test_redacted_thinking_block_yields_status():
    """Redacted thinking blocks are treated the same as regular thinking."""
    parser = StreamParser()

    items = await _collect(parser, _block_start("redacted_thinking"))
    assert items == [StreamStatus(kind="thinking_start")]

    event = {
        "type": "content_block_delta",
        "delta": {"type": "redacted_thinking_delta", "data": "opaque"},
    }
    items = await _collect(parser, event)
    assert items == []

    items = await _collect(parser, _block_stop())
    assert items == [StreamStatus(kind="phase_end")]


@pytest.mark.asyncio
async def test_interleaved_thinking_and_text():
    """Interleaved thinking/text blocks: thinking hidden, text shown."""
    parser = StreamParser()

    # Thinking block
    await _collect(parser, _block_start("thinking"))
    await _collect(parser, _thinking_delta("Planning my response..."))
    await _collect(parser, _block_stop())

    # Text block
    await _collect(parser, _block_start("text"))
    items = await _collect(parser, _text_delta("Hello!"))
    assert items == ["Hello!"]
    await _collect(parser, _block_stop())

    # Second thinking block
    await _collect(parser, _block_start("thinking"))
    await _collect(parser, _thinking_delta("Let me think more..."))
    await _collect(parser, _block_stop())

    # Second text block
    await _collect(parser, _block_start("text"))
    items = await _collect(parser, _text_delta("Here's more."))
    assert items == ["Here's more."]


# --- Surfaced label suppression ---


@pytest.mark.asyncio
async def test_surfaced_label_skipped_in_drain():
    """Labels already surfaced via interactive approval are not rendered."""
    reset()
    _surfaced_labels.add("Read(b/c.md)")
    parser = StreamParser()

    await _collect(parser, _block_start("tool_use", name="Read", id="1"))
    await _collect(parser, _input_delta('{"file_path": "/a/b/c.md"}'))
    await _collect(parser, _block_stop())

    items = await _collect(parser, _block_start("text"))

    labels = [i for i in items if isinstance(i, str) and "Read" in i]
    assert labels == []


@pytest.mark.asyncio
async def test_surfaced_and_denied_label_skipped():
    """Surfaced takes precedence over denied — label skipped entirely."""
    reset()
    _surfaced_labels.add("Read(b/c.md)")
    _denied_labels.add("Read(b/c.md)")
    parser = StreamParser()

    await _collect(parser, _block_start("tool_use", name="Read", id="1"))
    await _collect(parser, _input_delta('{"file_path": "/a/b/c.md"}'))
    await _collect(parser, _block_stop())

    items = await _collect(parser, _block_start("text"))

    labels = [i for i in items if isinstance(i, str) and "Read" in i]
    assert labels == []
