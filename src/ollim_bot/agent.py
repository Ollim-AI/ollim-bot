"""Claude Agent SDK wrapper -- the brain of the bot."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator
from dataclasses import replace
from datetime import datetime
from typing import Literal

from claude_agent_sdk import (
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

from ollim_bot import runtime_config, tool_policy
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
from ollim_bot.skills import build_skill_index
from ollim_bot.storage import DATA_DIR
from ollim_bot.streamer import StreamParser, StreamStatus
from ollim_bot.subagents import build_agent_definitions, load_subagent_specs

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
) -> ClaudeAgentOptions:
    """Apply per-job tool restrictions to agent options."""
    if allowed is not None:
        tools = allowed if _HELP_TOOL in allowed else [_HELP_TOOL, *allowed]
        return replace(opts, allowed_tools=tools)
    return opts


class Agent:
    def __init__(self) -> None:
        skill_index = build_skill_index()
        system_prompt = f"{SYSTEM_PROMPT}\n\n{skill_index}" if skill_index else SYSTEM_PROMPT
        self.options = ClaudeAgentOptions(
            cwd=DATA_DIR,
            include_partial_messages=True,
            can_use_tool=handle_tool_permission,
            system_prompt=system_prompt,
            mcp_servers={
                "discord": agent_server,
                "docs": {"type": "http", "url": "https://docs.ollim.ai/mcp"},
            },
            allowed_tools=tool_policy.build_superset(tool_policy.collect_all_tool_sets()),
            permission_mode="default",
            hooks={"Stop": [HookMatcher(hooks=[require_report_hook])]},
            agents=build_agent_definitions(load_subagent_specs()),
        )
        tool_policy.scan_all()

        cfg = runtime_config.load()
        if cfg.model_main:
            self.options = replace(self.options, model=cfg.model_main)
        if cfg.thinking_main:
            self.options = replace(self.options, max_thinking_tokens=cfg.max_thinking_tokens)

        self._client: ClaudeSDKClient | None = None
        self._fork_client: ClaudeSDKClient | None = None
        self._fork_session_id: str | None = None
        self._lock = asyncio.Lock()
        self._bg_tasks: set[asyncio.Task[None]] = set()

    @property
    def in_fork(self) -> bool:
        return self._fork_client is not None

    def lock(self) -> asyncio.Lock:
        return self._lock

    async def interrupt(self) -> None:
        cancel_pending()
        client = self._fork_client or self._client
        if client:
            # Fire-and-forget: the lock already gates the next message, so we
            # don't need to block on the subprocess acknowledging the interrupt.
            # Awaiting it delays the new message when the subprocess is slow to
            # respond (mid-tool, mid-API-call).
            async def _interrupt():
                with contextlib.suppress(CLIConnectionError):
                    await client.interrupt()

            task = asyncio.create_task(_interrupt())
            self._bg_tasks.add(task)
            task.add_done_callback(self._bg_tasks.discard)

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
        tokens = runtime_config.load().max_thinking_tokens if enabled else None
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

    async def apply_config(self, key: str) -> None:
        """Apply a config change to live clients where possible."""
        from ollim_bot import permissions

        cfg = runtime_config.load()
        if key == "model_main":
            self.options = replace(self.options, model=cfg.model_main)
            if self._client and cfg.model_main:
                await self._client.set_model(cfg.model_main)
        elif key == "model_fork":
            model = cfg.model_fork or cfg.model_main
            if self._fork_client and model:
                await self._fork_client.set_model(model)
        elif key == "thinking_main":
            tokens = cfg.max_thinking_tokens if cfg.thinking_main else None
            self.options = replace(self.options, max_thinking_tokens=tokens)
        elif key in ("thinking_fork", "bg_fork_timeout", "fork_idle_timeout"):
            pass  # takes effect on next fork
        elif key == "max_thinking_tokens":
            if self.options.max_thinking_tokens is not None:
                self.options = replace(self.options, max_thinking_tokens=cfg.max_thinking_tokens)
        elif key == "permission_mode":
            permissions.set_dont_ask(cfg.permission_mode == "dontAsk")
            mode = "default" if cfg.permission_mode == "dontAsk" else cfg.permission_mode
            await self.set_permission_mode(mode)

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

    async def enter_interactive_fork(
        self, *, idle_timeout: int | None = None, resume_session_id: str | None = None
    ) -> None:
        """Create an interactive fork client and switch routing to it."""
        cfg = runtime_config.load()
        if idle_timeout is None:
            idle_timeout = cfg.fork_idle_timeout
        model = cfg.model_fork or cfg.model_main
        self._fork_client = await self.create_forked_client(
            session_id=resume_session_id,
            fork=resume_session_id is None,
            thinking=cfg.thinking_fork,
            model=model,
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
        model: str | None = None,
        allowed_tools: list[str] | None = None,
    ) -> ClaudeSDKClient:
        """Create a disposable client that forks from a given or current session.

        fork=False resumes the session directly without branching. Use when the
        target is a completed bg fork session that may not support re-forking.
        thinking=None inherits from main session; True/False overrides.
        model=None inherits from main session options.
        """
        sid = session_id or load_session_id()
        if sid:
            opts = replace(self.options, resume=sid, fork_session=fork)
        else:
            opts = self.options
        if model:
            opts = replace(opts, model=model)
        if thinking is not None:
            tokens = runtime_config.load().max_thinking_tokens if thinking else None
            opts = replace(opts, max_thinking_tokens=tokens)
        opts = _apply_tool_restrictions(opts, allowed_tools)
        client = ClaudeSDKClient(opts)
        await client.connect()
        return client

    async def create_isolated_client(
        self,
        *,
        model: str | None = None,
        thinking: bool = True,
        allowed_tools: list[str] | None = None,
    ) -> ClaudeSDKClient:
        """Create a standalone client with no conversation history."""
        opts = self.options
        if model:
            opts = replace(opts, model=model)
        thinking_tokens = runtime_config.load().max_thinking_tokens if thinking else None
        opts = replace(opts, max_thinking_tokens=thinking_tokens)
        opts = _apply_tool_restrictions(opts, allowed_tools)
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

    async def _resolve_client(self, message: str) -> tuple[ClaudeSDKClient, str]:
        """Pick the active client (fork or main) and prepend context."""
        if self._fork_client is not None:
            message = await _prepend_context(message, clear=False)
            return self._fork_client, message
        message = await _prepend_context(message)
        client = await self._get_client()
        return client, message

    def _save_result_session(self, client: ClaudeSDKClient, msg: ResultMessage, *, log_fork_event: bool) -> None:
        """Save session ID from a ResultMessage.

        log_fork_event=True logs the interactive_fork event here (used by
        non-streaming paths where no StreamEvent captures it first).
        """
        if self._fork_client is not None and client is self._fork_client:
            if self._fork_session_id is None:
                self._fork_session_id = msg.session_id
                if log_fork_event:
                    log_session_event(
                        msg.session_id,
                        "interactive_fork",
                        parent_session_id=load_session_id(),
                    )
        elif self._client is client:
            save_session_id(msg.session_id)

    async def stream_chat(
        self,
        message: str,
        *,
        images: list[dict[str, str]] | None = None,
    ) -> AsyncGenerator[str | StreamStatus, None]:
        """Yield text deltas and StreamStatus signals for live progress display.

        Falls back to AssistantMessage text blocks if no StreamEvent arrives,
        then to ResultMessage.result. Saves session ID on completion.

        Detects mid-turn auto-compaction (context overflow) and transparently
        retries ``receive_response()`` so the post-compaction response streams
        through normally.
        """
        client, message = await self._resolve_client(message)

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
        fork_interrupted = False
        parser = StreamParser()
        compacted = False
        compact_tokens: int | None = None

        async def _consume(response):
            """Process messages from one receive_response() call."""
            nonlocal streamed, fork_interrupted, result_text, compacted, compact_tokens

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
                        if (
                            self._fork_client is not None
                            and client is self._fork_client
                            and self._fork_session_id is None
                        ):
                            self._fork_session_id = msg.session_id
                            log_session_event(
                                msg.session_id,
                                "interactive_fork",
                                parent_session_id=load_session_id(),
                            )

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
                        self._save_result_session(client, msg, log_fork_event=False)
            except CLIConnectionError:
                if not fork_interrupted:
                    raise

            # Drain any active status (e.g. tool as last action in a pure-tool turn)
            async for item in parser.drain():
                streamed = True
                yield item

        # First pass
        async for item in _consume(client.receive_response()):
            yield item

        # Auto-compaction: when context overflows mid-turn, the SDK emits
        # SystemMessage(subtype="compact_boundary") then ends the stream
        # with no content.  No new query() is needed — just call
        # receive_response() again.  MCP tools from the orphaned response
        # still execute in the SDK's _read_messages background task.
        # compact_metadata.pre_tokens gives the pre-compaction token count.
        if compacted:
            log.info("consuming post-compaction response")
            label = "Auto-compacting"
            if compact_tokens is not None:
                label += f" {compact_tokens / 1000:.0f}k tokens"
            yield StreamStatus(kind="compact_start", label=label, compact_tokens=compact_tokens)
            try:
                async with asyncio.timeout(120):
                    async for item in _consume(client.receive_response()):
                        yield item
            except TimeoutError:
                log.error("post-compaction response timed out after 120s")

        if not streamed:
            if fallback_parts:
                yield "\n".join(fallback_parts)
            elif result_text:
                yield result_text
