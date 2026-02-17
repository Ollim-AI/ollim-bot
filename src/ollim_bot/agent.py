"""Claude Agent SDK wrapper -- the brain of the bot."""

import asyncio
import contextlib
from collections.abc import AsyncGenerator
from dataclasses import replace
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from claude_agent_sdk import (
    AgentDefinition,
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
)
from claude_agent_sdk.types import StreamEvent

from ollim_bot.discord_tools import discord_server
from ollim_bot.prompts import (
    GMAIL_READER_PROMPT,
    HISTORY_REVIEWER_PROMPT,
    RESPONSIVENESS_REVIEWER_PROMPT,
    SYSTEM_PROMPT,
)
from ollim_bot.sessions import (
    SESSIONS_FILE,
    delete_session_id,
    load_session_id,
    save_session_id,
)

ModelName = Literal["opus", "sonnet", "haiku"]


def _timestamp() -> str:
    now = datetime.now(ZoneInfo("America/Los_Angeles"))
    return now.strftime("[%Y-%m-%d %a %I:%M %p PT]")


class Agent:
    def __init__(self):
        self.options = ClaudeAgentOptions(
            cwd=SESSIONS_FILE.parent,
            include_partial_messages=True,
            system_prompt=SYSTEM_PROMPT,
            mcp_servers={"discord": discord_server},
            allowed_tools=[
                "Bash(ollim-bot tasks *)",
                "Bash(ollim-bot cal *)",
                "Bash(ollim-bot routine *)",
                "Bash(ollim-bot reminder *)",
                "Bash(ollim-bot gmail *)",
                "Bash(ollim-bot help)",
                "Bash(claude-history *)",
                "mcp__discord__discord_embed",
                "mcp__discord__ping_user",
                "mcp__discord__follow_up_chain",
                "Task",
            ],
            permission_mode="default",
            agents={
                "gmail-reader": AgentDefinition(
                    description="Email triage specialist. Reads Gmail, sorts through noise, surfaces important emails with suggested follow-up tasks.",
                    prompt=GMAIL_READER_PROMPT,
                    tools=["Bash(ollim-bot gmail *)"],
                    model="sonnet",
                ),
                "history-reviewer": AgentDefinition(
                    description="Session history reviewer. Scans recent Claude Code sessions for unfinished work, untracked tasks, and loose threads that need follow-up.",
                    prompt=HISTORY_REVIEWER_PROMPT,
                    tools=["Bash(claude-history *)"],
                    model="sonnet",
                ),
                "responsiveness-reviewer": AgentDefinition(
                    description="Reminder responsiveness analyst. Correlates reminder firings with user responses to measure engagement and suggest schedule optimizations.",
                    prompt=RESPONSIVENESS_REVIEWER_PROMPT,
                    tools=[
                        "Bash(claude-history *)",
                        "Bash(ollim-bot routine *)",
                        "Bash(ollim-bot reminder *)",
                    ],
                    model="sonnet",
                ),
            },
        )
        self._clients: dict[str, ClaudeSDKClient] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def lock(self, user_id: str) -> asyncio.Lock:
        """Lazily created on first access; cached for the lifetime of the agent."""
        return self._locks.setdefault(user_id, asyncio.Lock())

    async def interrupt(self, user_id: str) -> None:
        client = self._clients.get(user_id)
        if client:
            await client.interrupt()

    async def clear(self, user_id: str) -> None:
        await self._drop_client(user_id)
        delete_session_id(user_id)

    async def set_model(self, user_id: str, model: ModelName) -> None:
        """Updates shared options (affects future connections) and switches any live client in-place."""
        self.options = replace(self.options, model=model)
        client = self._clients.get(user_id)
        if client:
            await client.set_model(model)

    async def _drop_client(self, user_id: str) -> None:
        """Suppresses disconnect errors -- anyio prohibits cross-task cancellation."""
        client = self._clients.pop(user_id, None)
        if not client:
            return
        await client.interrupt()
        with contextlib.suppress(Exception):
            await client.disconnect()

    async def slash(self, user_id: str, command: str) -> str:
        """Route a slash command and collect the response text.

        Returns the most informative response found: system message text,
        then assistant text, then result fallback, then cost, then "done.".
        """
        client = await self._get_client(user_id)
        await client.query(command)

        parts: list[str] = []
        result_text: str | None = None
        cost: float | None = None
        async for msg in client.receive_response():
            if isinstance(msg, SystemMessage):
                # System messages carry slash command output (e.g. /cost)
                data = msg.data or {}
                if text := data.get("text") or data.get("message"):
                    parts.append(text)
            elif isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        parts.append(block.text)
            elif isinstance(msg, ResultMessage):
                if msg.result:
                    result_text = msg.result
                cost = msg.total_cost_usd
                if self._clients.get(user_id) is client:
                    save_session_id(user_id, msg.session_id)

        if parts:
            return "\n".join(parts)
        if result_text:
            return result_text
        if cost is not None:
            return f"session cost: ${cost:.4f}"
        return "done."

    async def _get_client(self, user_id: str) -> ClaudeSDKClient:
        if user_id not in self._clients:
            session_id = load_session_id(user_id)
            opts = (
                replace(self.options, resume=session_id) if session_id else self.options
            )
            client = ClaudeSDKClient(opts)
            await client.connect()
            self._clients[user_id] = client
        return self._clients[user_id]

    async def stream_chat(
        self,
        message: str,
        user_id: str,
        *,
        images: list[dict[str, str]] | None = None,
    ) -> AsyncGenerator[str, None]:
        """Yield text deltas, emitting ``-# *using {name}*`` markers on tool use.

        Falls back to AssistantMessage text blocks if no StreamEvent arrives,
        then to ResultMessage.result. Saves session ID on completion.
        """
        message = f"{_timestamp()} {message}" if message else _timestamp()
        client = await self._get_client(user_id)

        if images:
            # SDK has no ImageBlock type -- images go through the raw
            # streaming dict interface (AsyncIterable[dict]).  Content
            # blocks use the Anthropic Messages API image format.
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

            # query() accepts AsyncIterable[dict] -- yield a full user
            # message envelope so the SDK forwards it as-is.
            async def _user_message():
                yield {
                    "type": "user",
                    "message": {"role": "user", "content": blocks},
                    "parent_tool_use_id": None,
                }

            await client.query(_user_message())
        else:
            await client.query(message)

        streamed = False
        fallback_parts: list[str] = []
        result_text: str | None = None

        async for msg in client.receive_response():
            if isinstance(msg, StreamEvent):
                event = msg.event
                etype = event.get("type")

                if etype == "content_block_delta":
                    text = event.get("delta", {}).get("text", "")
                    if text:
                        streamed = True
                        yield text

                elif etype == "content_block_start":
                    block = event.get("content_block", {})
                    if block.get("type") == "tool_use":
                        name = block.get("name", "tool")
                        streamed = True
                        yield f"\n-# *using {name}*\n"

            elif isinstance(msg, AssistantMessage) and not streamed:
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        fallback_parts.append(block.text)
            elif isinstance(msg, ResultMessage):
                if msg.result:
                    result_text = msg.result
                if self._clients.get(user_id) is client:
                    save_session_id(user_id, msg.session_id)

        if not streamed:
            if fallback_parts:
                yield "\n".join(fallback_parts)
            elif result_text:
                yield result_text

    async def chat(self, message: str, user_id: str) -> str:
        """Non-streaming counterpart of stream_chat; accumulates full response.

        Falls back to ResultMessage.result when no AssistantMessage text blocks
        are found.
        """
        message = f"{_timestamp()} {message}" if message else _timestamp()
        client = await self._get_client(user_id)
        await client.query(message)

        parts: list[str] = []
        result_text: str | None = None
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        parts.append(block.text)
            elif isinstance(msg, ResultMessage):
                if msg.result:
                    result_text = msg.result
                if self._clients.get(user_id) is client:
                    save_session_id(user_id, msg.session_id)

        # result is a summary Claude writes when it has no assistant turn (e.g. pure tool runs)
        if not parts and result_text:
            parts.append(result_text)

        return "\n".join(parts) or "hmm, I didn't have a response for that."
