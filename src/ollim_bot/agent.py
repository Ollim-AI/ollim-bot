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
    CLIConnectionError,
    ResultMessage,
    SystemMessage,
    TextBlock,
)
from claude_agent_sdk.types import StreamEvent

from ollim_bot.discord_tools import (
    discord_server,
    peek_pending_updates,
    pop_pending_updates,
)
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


def _prepend_context(message: str, *, clear: bool = True) -> str:
    """Prepend timestamp and any pending background updates to a user message.

    clear=True (default): pops updates (main session clears the file).
    clear=False: peeks updates (fork reads without clearing).
    """
    ts = _timestamp()
    updates = pop_pending_updates() if clear else peek_pending_updates()
    if updates:
        header = "RECENT BACKGROUND UPDATES:\n" + "\n".join(f"- {u}" for u in updates)
        return f"{ts} {header}\n\n{message}"
    return f"{ts} {message}" if message else ts


class Agent:
    def __init__(self) -> None:
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
                "mcp__discord__save_context",
                "mcp__discord__report_updates",
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
        self._client: ClaudeSDKClient | None = None
        self._lock = asyncio.Lock()

    def lock(self) -> asyncio.Lock:
        return self._lock

    async def interrupt(self) -> None:
        if self._client:
            await self._client.interrupt()

    async def clear(self) -> None:
        await self._drop_client()
        delete_session_id()

    async def set_model(self, model: ModelName) -> None:
        """Updates shared options (affects future connections) and switches any live client in-place."""
        self.options = replace(self.options, model=model)
        if self._client:
            await self._client.set_model(model)

    async def _drop_client(self) -> None:
        """Teardown: interrupt + disconnect.

        Suppresses CLIConnectionError (subprocess may have exited) and
        RuntimeError (anyio forbids exiting a cancel scope from a
        different task than the one that entered it -- happens when the
        caller's task differs from the task that called connect()).
        """
        client = self._client
        self._client = None
        if not client:
            return
        with contextlib.suppress(CLIConnectionError):
            await client.interrupt()
        with contextlib.suppress(RuntimeError):
            await client.disconnect()

    async def swap_client(self, client: ClaudeSDKClient, session_id: str) -> None:
        """Promote a forked client to the main client, replacing the old one."""
        old = self._client
        self._client = client
        save_session_id(session_id)
        if old:
            with contextlib.suppress(CLIConnectionError):
                await old.interrupt()
            with contextlib.suppress(RuntimeError):
                await old.disconnect()

    async def create_forked_client(self) -> ClaudeSDKClient:
        """Create a disposable client that forks the current session.

        Not stored in self._client -- the caller disconnects it after use.
        """
        session_id = load_session_id()
        if session_id:
            opts = replace(self.options, resume=session_id, fork_session=True)
        else:
            opts = self.options
        client = ClaudeSDKClient(opts)
        await client.connect()
        return client

    async def run_on_client(self, client: ClaudeSDKClient, message: str) -> str:
        """Send a message on an explicit client, discard output, return session_id."""
        message = _prepend_context(message, clear=False)
        await client.query(message)

        session_id: str | None = None
        async for msg in client.receive_response():
            if isinstance(msg, ResultMessage):
                session_id = msg.session_id

        assert session_id is not None, "No ResultMessage received from forked client"
        return session_id

    async def slash(self, command: str) -> str:
        """Route a slash command and collect the response text.

        Returns the most informative response found: system message text,
        then assistant text, then result fallback, then cost, then "done.".
        """
        client = await self._get_client()
        await client.query(command)

        parts: list[str] = []
        result_text: str | None = None
        cost: float | None = None
        async for msg in client.receive_response():
            if isinstance(msg, SystemMessage):
                # System messages carry slash command output (e.g. /cost)
                data = msg.data
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
                if self._client is client:
                    save_session_id(msg.session_id)

        if parts:
            return "\n".join(parts)
        if result_text:
            return result_text
        if cost is not None:
            return f"session cost: ${cost:.4f}"
        return "done."

    async def _get_client(self) -> ClaudeSDKClient:
        if self._client is None:
            session_id = load_session_id()
            opts = (
                replace(self.options, resume=session_id) if session_id else self.options
            )
            client = ClaudeSDKClient(opts)
            await client.connect()
            self._client = client
        return self._client

    async def stream_chat(
        self,
        message: str,
        *,
        images: list[dict[str, str]] | None = None,
    ) -> AsyncGenerator[str, None]:
        """Yield text deltas, emitting ``-# *using {name}*`` markers on tool use.

        Falls back to AssistantMessage text blocks if no StreamEvent arrives,
        then to ResultMessage.result. Saves session ID on completion.
        """
        message = _prepend_context(message)
        client = await self._get_client()

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
                    text = event["delta"].get("text", "")
                    if text:
                        streamed = True
                        yield text

                elif etype == "content_block_start":
                    block = event["content_block"]
                    if block["type"] == "tool_use":
                        name = block["name"]
                        streamed = True
                        yield f"\n-# *using {name}*\n"

            elif isinstance(msg, AssistantMessage) and not streamed:
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        fallback_parts.append(block.text)
            elif isinstance(msg, ResultMessage):
                if msg.result:
                    result_text = msg.result
                if self._client is client:
                    save_session_id(msg.session_id)

        if not streamed:
            if fallback_parts:
                yield "\n".join(fallback_parts)
            elif result_text:
                yield result_text

    async def chat(self, message: str) -> str:
        """Non-streaming counterpart of stream_chat; accumulates full response.

        Falls back to ResultMessage.result when no AssistantMessage text blocks
        are found.
        """
        message = _prepend_context(message)
        client = await self._get_client()
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
                if self._client is client:
                    save_session_id(msg.session_id)

        # result is a summary Claude writes when it has no assistant turn (e.g. pure tool runs)
        if not parts and result_text:
            parts.append(result_text)

        return "\n".join(parts) or "hmm, I didn't have a response for that."
