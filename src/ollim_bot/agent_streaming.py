"""Streaming response consumer — extracted from Agent.stream_chat.

Free function that handles the SDK message loop, auto-compaction retry,
fork interrupt, and fallback tiers.  Zero knowledge of Agent.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncGenerator, Callable

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeSDKClient,
    CLIConnectionError,
    ResultMessage,
    SystemMessage,
    TextBlock,
)
from claude_agent_sdk.types import StreamEvent

from ollim_bot.fork_state import enter_fork_requested
from ollim_bot.streamer import StreamParser, StreamStatus

log = logging.getLogger(__name__)


def build_image_query(message: str, images: list[dict[str, str]]) -> AsyncGenerator[dict, None]:
    """Build an SDK-compatible image query envelope.

    Returns an async generator yielding a single user-message dict with
    base64 image blocks.  Suitable for ``client.query()``.
    """
    blocks: list[dict] = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": img["media_type"],
                "data": img["data"],
            },
        }
        for img in images
    ]
    if message:
        blocks.append({"type": "text", "text": message})

    async def _gen():
        yield {
            "type": "user",
            "message": {"role": "user", "content": blocks},
            "parent_tool_use_id": None,
        }

    return _gen()


async def stream_response(
    client: ClaudeSDKClient,
    message: str,
    *,
    images: list[dict[str, str]] | None = None,
    on_fork_session: Callable[[str], None] | None = None,
    on_result_session: Callable[[ClaudeSDKClient, ResultMessage], None] | None = None,
) -> AsyncGenerator[str | StreamStatus, None]:
    """Stream a single agent response, yielding text deltas and status signals.

    Handles auto-compaction transparently: when the SDK emits a
    ``compact_boundary`` SystemMessage, yields ``StreamStatus(kind="compact_start")``
    and re-sends the query against the freshly compacted context.

    Falls back through three tiers: StreamEvent → AssistantMessage → ResultMessage.
    """
    if images:
        await client.query(build_image_query(message, images))
    else:
        await client.query(message)

    streamed = False
    fallback_parts: list[str] = []
    result_text: str | None = None
    fork_interrupted = False
    parser = StreamParser()
    compacted = False
    compact_tokens: int | None = None

    fork_session_notified = False

    async def _consume(response):
        """Process messages from one receive_response() call."""
        nonlocal streamed, fork_interrupted, result_text, compacted, compact_tokens, fork_session_notified

        try:
            async for msg in response:
                if isinstance(msg, SystemMessage):
                    if msg.subtype == "compact_boundary":
                        compacted = True
                        meta = msg.data.get("compact_metadata", {})
                        compact_tokens = meta.get("pre_tokens")
                        log.warning("auto-compaction detected mid-turn")
                    continue

                if isinstance(msg, StreamEvent):
                    if not fork_interrupted and enter_fork_requested():
                        fork_interrupted = True
                        with contextlib.suppress(CLIConnectionError):
                            await client.interrupt()
                        continue
                    if fork_interrupted:
                        continue

                    if on_fork_session is not None and not fork_session_notified:
                        fork_session_notified = True
                        on_fork_session(msg.session_id)

                    async for item in parser.feed(msg.event):
                        streamed = True
                        yield item

                elif isinstance(msg, AssistantMessage) and not streamed:
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            fallback_parts.append(block.text)
                elif isinstance(msg, ResultMessage):
                    if msg.result:
                        result_text = msg.result
                    if on_result_session is not None:
                        on_result_session(client, msg)
        except CLIConnectionError:
            if not fork_interrupted:
                raise

        async for item in parser.drain():
            streamed = True
            yield item

    # First pass
    async for item in _consume(client.receive_response()):
        yield item

    # Auto-compaction: SDK emits compact_boundary then waits for a new query.
    # Re-send the message so the agent responds against compacted context.
    if compacted:
        log.info("re-sending query after auto-compaction")
        label = "Auto-compacting"
        if compact_tokens is not None:
            label += f" {compact_tokens / 1000:.0f}k tokens"
        yield StreamStatus(kind="compact_start", label=label, compact_tokens=compact_tokens)
        await client.query(message)
        async for item in _consume(client.receive_response()):
            yield item

    if not streamed:
        if fallback_parts:
            yield "\n".join(fallback_parts)
        elif result_text:
            yield result_text
