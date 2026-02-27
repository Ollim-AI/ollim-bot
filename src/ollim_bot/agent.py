"""Claude Agent SDK wrapper -- the brain of the bot."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator
from dataclasses import replace
from datetime import datetime
from typing import Literal

from claude_agent_sdk import (
    AgentDefinition,
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    CLIConnectionError,
    HookMatcher,
    ResultMessage,
    SystemMessage,
    TextBlock,
)
from claude_agent_sdk.types import StreamEvent

from ollim_bot.agent_tools import agent_server, require_report_hook
from ollim_bot.config import TZ as _TZ
from ollim_bot.forks import (
    ForkExitAction,
    enter_fork_requested,
    peek_pending_updates,
    pop_exit_action,
    pop_pending_updates,
    set_interactive_fork,
    touch_activity,
)
from ollim_bot.formatting import format_tool_label
from ollim_bot.permissions import (
    cancel_pending,
    handle_tool_permission,
)
from ollim_bot.permissions import (
    reset as reset_permissions,
)
from ollim_bot.prompts import SYSTEM_PROMPT
from ollim_bot.sessions import (
    delete_session_id,
    load_session_id,
    log_session_event,
    save_session_id,
    session_start_time,
    set_swap_in_progress,
)
from ollim_bot.storage import DATA_DIR
from ollim_bot.subagent_prompts import (
    GMAIL_READER_PROMPT,
    HISTORY_REVIEWER_PROMPT,
    RESPONSIVENESS_REVIEWER_PROMPT,
)

log = logging.getLogger(__name__)

ModelName = Literal["opus", "sonnet", "haiku"]


def _format_duration(seconds: float) -> str:
    """Format seconds as '3h 12m', '45m', or '< 1m'."""
    minutes = int(seconds // 60)
    if minutes < 1:
        return "< 1m"
    hours, mins = divmod(minutes, 60)
    if hours:
        return f"{hours}h {mins}m" if mins else f"{hours}h"
    return f"{mins}m"


def _format_compact_stats(result: ResultMessage | None, pre_tokens: int | None) -> str:
    """Format compaction result as productivity stats."""
    parts: list[str] = []
    if result:
        parts.append(f"{result.num_turns} turns")
    start = session_start_time()
    if start:
        age = (datetime.now(_TZ) - start).total_seconds()
        parts.append(_format_duration(age))
    if pre_tokens is not None:
        k = pre_tokens / 1000
        parts.append(f"{k:.0f}k tokens compacted")
    return " · ".join(parts)


def _timestamp() -> str:
    return datetime.now(_TZ).strftime("[%Y-%m-%d %a %I:%M %p PT]")


def _relative_time(iso_ts: str) -> str:
    """Format an ISO timestamp as relative time (e.g. '2h ago')."""
    delta = datetime.now(_TZ) - datetime.fromisoformat(iso_ts)
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


async def _prepend_context(message: str, *, clear: bool = True) -> str:
    """Prepend timestamp and any pending background updates to a user message.

    clear=True (default): pops updates (main session clears the file).
    clear=False: peeks updates (fork reads without clearing).
    """
    ts = _timestamp()
    updates = (await pop_pending_updates()) if clear else peek_pending_updates()
    if updates:
        lines = [f"- ({_relative_time(u.ts)}) {u.message}" for u in updates]
        header = "RECENT BACKGROUND UPDATES:\n" + "\n".join(lines)
        assembled = f"{ts} {header}\n\n{message}"
    else:
        assembled = f"{ts} {message}" if message else ts
    log.debug("assembled context: %.500s", assembled)
    return assembled


_HELP_TOOL = "Bash(ollim-bot help)"


def _apply_tool_restrictions(
    opts: ClaudeAgentOptions,
    allowed: list[str] | None,
    blocked: list[str] | None,
) -> ClaudeAgentOptions:
    """Apply per-job tool restrictions to agent options."""
    if allowed is not None:
        tools = allowed if _HELP_TOOL in allowed else [_HELP_TOOL, *allowed]
        return replace(opts, allowed_tools=tools)
    if blocked is not None:
        return replace(opts, disallowed_tools=blocked)
    return opts


class Agent:
    def __init__(self) -> None:
        self.options = ClaudeAgentOptions(
            cwd=DATA_DIR,
            include_partial_messages=True,
            can_use_tool=handle_tool_permission,
            system_prompt=SYSTEM_PROMPT,
            mcp_servers={
                "discord": agent_server,
                "docs": {"type": "http", "url": "https://docs.ollim.ai/mcp"},
            },
            allowed_tools=[
                "Bash(ollim-bot tasks *)",
                "Bash(ollim-bot cal *)",
                "Bash(ollim-bot reminder *)",
                "Bash(ollim-bot gmail *)",
                "Bash(ollim-bot help)",
                "Bash(claude-history *)",
                "Read(**.md)",
                "Write(**.md)",
                "Edit(**.md)",
                "Glob(**.md)",
                "Grep(**.md)",
                "WebFetch",
                "WebSearch",
                "mcp__discord__discord_embed",
                "mcp__discord__ping_user",
                "mcp__discord__follow_up_chain",
                "mcp__discord__save_context",
                "mcp__discord__report_updates",
                "mcp__discord__enter_fork",
                "mcp__discord__exit_fork",
                "mcp__discord__compact_session",
                "mcp__docs__*",
                "Task",
            ],
            permission_mode="default",
            hooks={"Stop": [HookMatcher(hooks=[require_report_hook])]},
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
        self._fork_client: ClaudeSDKClient | None = None
        self._fork_session_id: str | None = None
        self._lock = asyncio.Lock()

    @property
    def in_fork(self) -> bool:
        return self._fork_client is not None

    def lock(self) -> asyncio.Lock:
        return self._lock

    async def interrupt(self) -> None:
        cancel_pending()
        if self._client:
            await self._client.interrupt()

    async def clear(self) -> None:
        reset_permissions()
        if self._fork_client:
            await self.exit_interactive_fork(ForkExitAction.EXIT)
        current = load_session_id()
        if current:
            log_session_event(current, "cleared")
        await self._drop_client()
        delete_session_id()

    async def set_model(self, model: ModelName) -> None:
        """Updates shared options (affects future connections) and switches any live client in-place."""
        self.options = replace(self.options, model=model)
        if self._client:
            await self._client.set_model(model)
        if self._fork_client:
            await self._fork_client.set_model(model)

    async def set_thinking(self, enabled: bool) -> None:
        """Toggle extended thinking. Drops clients to apply (no live setter)."""
        tokens = 10000 if enabled else None
        self.options = replace(self.options, max_thinking_tokens=tokens)
        await self._drop_client()
        if self._fork_client:
            cancel_pending()
            fork = self._fork_client
            self._fork_client = None
            self._fork_session_id = None
            set_interactive_fork(False)
            with contextlib.suppress(CLIConnectionError):
                await fork.interrupt()
            with contextlib.suppress(RuntimeError):
                await fork.disconnect()

    async def set_permission_mode(self, mode: str) -> None:
        """Switch SDK permission mode. Fork-scoped when in interactive fork."""
        if self._fork_client:
            await self._fork_client.set_permission_mode(mode)
        elif self._client:
            await self._client.set_permission_mode(mode)
            self.options = replace(self.options, permission_mode=mode)
        else:
            self.options = replace(self.options, permission_mode=mode)

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

    async def swap_client(self, client: ClaudeSDKClient, session_id: str) -> None:  # duplicate-ok
        """Promote a forked client to the main client, replacing the old one."""
        old = self._client
        old_session_id = load_session_id()
        self._client = client
        set_swap_in_progress(True)
        try:
            save_session_id(session_id)
        finally:
            set_swap_in_progress(False)
        log_session_event(session_id, "swapped", parent_session_id=old_session_id)
        if old:
            with contextlib.suppress(CLIConnectionError):
                await old.interrupt()
            with contextlib.suppress(RuntimeError):
                await old.disconnect()

    async def enter_interactive_fork(self, *, idle_timeout: int = 10, resume_session_id: str | None = None) -> None:
        """Create an interactive fork client and switch routing to it."""
        self._fork_client = await self.create_forked_client(
            session_id=resume_session_id,
            fork=resume_session_id is None,
            thinking=True,
        )
        self._fork_session_id = None
        set_interactive_fork(True, idle_timeout=idle_timeout)
        touch_activity()

    async def exit_interactive_fork(self, action: ForkExitAction) -> None:
        """Exit interactive fork: promote (SAVE), report (REPORT), or discard (EXIT)."""
        cancel_pending()
        client = self._fork_client
        session_id = self._fork_session_id
        self._fork_client = None
        self._fork_session_id = None
        set_interactive_fork(False)

        if client is None:
            return

        if action is ForkExitAction.SAVE and session_id is not None:
            await self.swap_client(client, session_id)
        else:
            with contextlib.suppress(CLIConnectionError):
                await client.interrupt()
            with contextlib.suppress(RuntimeError):
                await client.disconnect()

    async def pop_fork_exit(self) -> tuple[ForkExitAction, str | None] | None:
        """Pop pending exit action, exit the fork, return (action, summary) or None."""
        action = pop_exit_action()
        if action is ForkExitAction.NONE:
            return None
        updates = peek_pending_updates()
        summary = updates[-1].message if action is ForkExitAction.REPORT and updates else None
        await self.exit_interactive_fork(action)
        return action, summary

    async def create_forked_client(
        self,
        session_id: str | None = None,
        *,
        fork: bool = True,
        thinking: bool | None = None,
        allowed_tools: list[str] | None = None,
        disallowed_tools: list[str] | None = None,
    ) -> ClaudeSDKClient:
        """Create a disposable client that forks from a given or current session.

        fork=False resumes the session directly without branching. Use when the
        target is a completed bg fork session that may not support re-forking.
        thinking=None inherits from main session; True/False overrides.
        """
        sid = session_id or load_session_id()
        if sid:
            opts = replace(self.options, resume=sid, fork_session=fork)
        else:
            opts = self.options
        if thinking is not None:
            tokens = 10000 if thinking else None
            opts = replace(opts, max_thinking_tokens=tokens)
        opts = _apply_tool_restrictions(opts, allowed_tools, disallowed_tools)
        client = ClaudeSDKClient(opts)
        await client.connect()
        return client

    async def create_isolated_client(
        self,
        *,
        model: str | None = None,
        thinking: bool = True,
        allowed_tools: list[str] | None = None,
        disallowed_tools: list[str] | None = None,
    ) -> ClaudeSDKClient:
        """Create a standalone client with no conversation history."""
        opts = self.options
        if model:
            opts = replace(opts, model=model)
        thinking_tokens = 10000 if thinking else None
        opts = replace(opts, max_thinking_tokens=thinking_tokens)
        opts = _apply_tool_restrictions(opts, allowed_tools, disallowed_tools)
        client = ClaudeSDKClient(opts)
        await client.connect()
        return client

    async def create_persistent_client(
        self,
        session_id: str | None = None,
        *,
        model: str | None = None,
        thinking: bool = True,
        allowed_tools: list[str] | None = None,
        disallowed_tools: list[str] | None = None,
    ) -> ClaudeSDKClient:
        """Create a client for persistent routine sessions.

        Resumes from session_id if provided (continuing the lineage),
        else starts fresh. No fork_session — persistent sessions are
        standalone lineages, not branches of the main session.
        """
        opts = self.options
        if session_id:
            opts = replace(opts, resume=session_id)
        if model:
            opts = replace(opts, model=model)
        thinking_tokens = 10000 if thinking else None
        opts = replace(opts, max_thinking_tokens=thinking_tokens)
        opts = _apply_tool_restrictions(opts, allowed_tools, disallowed_tools)
        client = ClaudeSDKClient(opts)
        await client.connect()
        return client

    async def run_on_client(self, client: ClaudeSDKClient, message: str, *, prepend_updates: bool = True) -> str:
        """Send a message on an explicit client, discard output, return session_id."""
        if prepend_updates:
            message = await _prepend_context(message, clear=False)
        else:
            message = f"{_timestamp()} {message}"
        log.debug("run_on_client prompt: %.500s", message)
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
        then assistant text, then result fallback, then "done.".
        """
        client = await self._get_client()
        parts, _ = await self._run_slash(client, command)
        return "\n".join(parts) if parts else "done."

    async def compact(self, instructions: str | None = None) -> str:
        """Run /compact and return productivity stats."""
        client = await self._get_client()
        cmd = f"/compact {instructions}" if instructions else "/compact"
        await client.query(cmd)

        pre_tokens: int | None = None
        result_msg: ResultMessage | None = None
        compacted = False
        async for msg in client.receive_response():
            if isinstance(msg, SystemMessage):
                if msg.subtype == "compact_boundary":
                    meta = msg.data.get("compact_metadata", {})
                    pre_tokens = meta.get("pre_tokens")
                    compacted = True
            elif isinstance(msg, ResultMessage):
                result_msg = msg
                if self._client is client:
                    save_session_id(msg.session_id)
                    if compacted:
                        log_session_event(msg.session_id, "compacted")

        return _format_compact_stats(result_msg, pre_tokens)

    async def _run_slash(self, client: ClaudeSDKClient, command: str) -> tuple[list[str], ResultMessage | None]:
        """Send a slash command, return (text parts, ResultMessage)."""
        await client.query(command)

        parts: list[str] = []
        result_msg: ResultMessage | None = None
        async for msg in client.receive_response():
            if isinstance(msg, SystemMessage):
                data = msg.data
                if text := data.get("text") or data.get("message"):
                    parts.append(text)
            elif isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        parts.append(block.text)
            elif isinstance(msg, ResultMessage):
                result_msg = msg
                if msg.result:
                    parts.append(msg.result)
                if self._client is client:
                    save_session_id(msg.session_id)

        return parts, result_msg

    async def _get_client(self) -> ClaudeSDKClient:
        if self._client is None:
            session_id = load_session_id()
            opts = replace(self.options, resume=session_id) if session_id else self.options
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
        """Yield text deltas, emitting ``-# *Tool(args)*`` markers on tool use.

        Falls back to AssistantMessage text blocks if no StreamEvent arrives,
        then to ResultMessage.result. Saves session ID on completion.
        """
        if self._fork_client is not None:
            client = self._fork_client
            message = await _prepend_context(message, clear=False)
        else:
            message = await _prepend_context(message)
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
        tool_name: str | None = None
        tool_input_buf = ""
        fork_interrupted = False

        try:
            async for msg in client.receive_response():
                if isinstance(msg, StreamEvent):
                    # Interrupt once when enter_fork tool fires; suppress
                    # remaining StreamEvents but let the loop end naturally
                    # so ResultMessage still saves the session ID.
                    if not fork_interrupted and enter_fork_requested():
                        fork_interrupted = True
                        with contextlib.suppress(CLIConnectionError):
                            await client.interrupt()
                        continue
                    if fork_interrupted:
                        continue

                    # Capture fork session ID from first StreamEvent
                    if self._fork_client is not None and client is self._fork_client and self._fork_session_id is None:
                        self._fork_session_id = msg.session_id
                        log_session_event(
                            msg.session_id,
                            "interactive_fork",
                            parent_session_id=load_session_id(),
                        )

                    event = msg.event
                    etype = event.get("type")

                    if etype == "content_block_start":
                        block = event["content_block"]
                        if block["type"] == "tool_use":
                            tool_name = block["name"]
                            tool_input_buf = ""

                    elif etype == "content_block_delta":
                        delta = event["delta"]
                        if delta.get("type") == "input_json_delta":
                            tool_input_buf += delta.get("partial_json", "")
                        elif text := delta.get("text", ""):
                            streamed = True
                            yield text

                    elif etype == "content_block_stop":
                        if tool_name is not None:
                            label = format_tool_label(tool_name, tool_input_buf)
                            streamed = True
                            yield f"\n-# *{label}*\n"
                            tool_name = None

                elif isinstance(msg, AssistantMessage) and not streamed:
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            fallback_parts.append(block.text)
                elif isinstance(msg, ResultMessage):
                    if msg.result:
                        result_text = msg.result
                    if self._fork_client is not None and client is self._fork_client:
                        if self._fork_session_id is None:
                            self._fork_session_id = msg.session_id
                    elif self._client is client:
                        save_session_id(msg.session_id)
        except CLIConnectionError:
            if not fork_interrupted:
                raise

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
        if self._fork_client is not None:
            client = self._fork_client
            message = await _prepend_context(message, clear=False)
        else:
            message = await _prepend_context(message)
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
                if self._fork_client is not None and client is self._fork_client:
                    if self._fork_session_id is None:
                        self._fork_session_id = msg.session_id
                        log_session_event(
                            msg.session_id,
                            "interactive_fork",
                            parent_session_id=load_session_id(),
                        )
                elif self._client is client:
                    save_session_id(msg.session_id)

        # result is a summary Claude writes when it has no assistant turn (e.g. pure tool runs)
        if not parts and result_text:
            parts.append(result_text)

        return "\n".join(parts) or "hmm, I didn't have a response for that."
