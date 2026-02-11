"""Claude Agent SDK wrapper -- the brain of the bot."""

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import replace

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
from ollim_bot.prompts import GMAIL_READER_PROMPT, SYSTEM_PROMPT
from ollim_bot.sessions import delete_session_id, load_session_id, save_session_id


class Agent:
    """Wraps the Claude Agent SDK with persistent per-user sessions.

    Each user gets a ClaudeSDKClient that maintains conversation context
    indefinitely. Auto-compaction is handled by Claude Code CLI when
    the context window fills up.
    """

    def __init__(self):
        self.options = ClaudeAgentOptions(
            include_partial_messages=True,
            system_prompt=SYSTEM_PROMPT,
            mcp_servers={"discord": discord_server},
            allowed_tools=[
                "Bash(ollim-bot tasks *)",
                "Bash(ollim-bot cal *)",
                "Bash(ollim-bot schedule *)",
                "Bash(ollim-bot gmail *)",
                "Bash(ollim-bot help)",
                "Bash(claude-history *)",
                "mcp__discord__discord_embed",
                "Task",
            ],
            permission_mode="dontAsk",
            agents={
                "gmail-reader": AgentDefinition(
                    description="Email triage specialist. Reads Gmail, sorts through noise, surfaces important emails with suggested follow-up tasks.",
                    prompt=GMAIL_READER_PROMPT,
                    tools=["Bash(ollim-bot gmail *)"],
                    model="sonnet",
                ),
            },
        )
        self._clients: dict[str, ClaudeSDKClient] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def lock(self, user_id: str) -> asyncio.Lock:
        """Per-user lock to serialize access to the shared ClaudeSDKClient."""
        if user_id not in self._locks:
            self._locks[user_id] = asyncio.Lock()
        return self._locks[user_id]

    async def interrupt(self, user_id: str) -> None:
        """Interrupt the current response for a user."""
        client = self._clients.get(user_id)
        if client:
            await client.interrupt()

    async def clear(self, user_id: str) -> None:
        """Reset conversation -- disconnect client and remove persisted session."""
        await self._drop_client(user_id)
        delete_session_id(user_id)

    async def set_model(self, user_id: str, model: str) -> None:
        """Switch model by reconnecting with updated options."""
        self.options = replace(self.options, model=model)
        await self._drop_client(user_id)

    async def _drop_client(self, user_id: str) -> None:
        """Interrupt and remove a user's client.

        We intentionally skip disconnect() -- anyio forbids calling it from
        a different task context, and awaiting it in the same task can hang.
        The CLI subprocess is cleaned up when the object is garbage collected.
        """
        client = self._clients.pop(user_id, None)
        if not client:
            return
        await client.interrupt()

    async def slash(self, user_id: str, command: str) -> str:
        """Send a slash command to the SDK and return the result."""
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
            opts = replace(self.options, resume=session_id) if session_id else self.options
            client = ClaudeSDKClient(opts)
            await client.connect()
            self._clients[user_id] = client
        return self._clients[user_id]

    async def stream_chat(
        self, message: str, user_id: str
    ) -> AsyncGenerator[str, None]:
        """Yield text deltas as they stream in from Claude."""
        client = await self._get_client(user_id)
        await client.query(message)

        streamed = False
        fallback_parts: list[str] = []
        result_text: str | None = None

        async for msg in client.receive_response():
            if isinstance(msg, StreamEvent):
                event = msg.event
                etype = event.get("type")

                if etype == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        text = delta.get("text", "")
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

        # Use ResultMessage.result only as fallback when no text blocks found
        if not parts and result_text:
            parts.append(result_text)

        return "\n".join(parts) or "hmm, I didn't have a response for that."
