"""Claude Agent SDK wrapper -- the brain of the bot."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator, Callable
from dataclasses import replace

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

from ollim_bot import runtime_config, tool_policy
from ollim_bot.agent_context import (
    ModelName,
    format_compact_stats,
    prepend_context,
    timestamp,
)
from ollim_bot.agent_context import (
    thinking as _thinking,
)
from ollim_bot.agent_streaming import stream_response
from ollim_bot.agent_tools import agent_server, require_report_hook
from ollim_bot.channel import get_channel
from ollim_bot.fork_state import (
    ForkExitAction,
    pop_exit_action,
    set_interactive_fork,
    touch_activity,
)
from ollim_bot.forks import peek_pending_updates
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
    set_swap_in_progress,
)
from ollim_bot.skills import list_skills
from ollim_bot.storage import DATA_DIR
from ollim_bot.streamer import StreamStatus

log = logging.getLogger(__name__)


class Agent:
    def __init__(self) -> None:
        all_skills = list_skills()
        tool_sets = tool_policy.collect_all_tool_sets(skills=all_skills)
        tool_policy.scan_all(tool_sets)
        self.options = ClaudeAgentOptions(
            cwd=DATA_DIR,
            include_partial_messages=True,
            can_use_tool=handle_tool_permission,
            system_prompt=SYSTEM_PROMPT,
            setting_sources=["project"],
            mcp_servers={
                "discord": agent_server,
                "docs": {"type": "http", "url": "https://docs.ollim.ai/mcp"},
            },
            allowed_tools=tool_policy.build_superset(tool_sets),
            permission_mode="default",
            hooks={"Stop": [HookMatcher(hooks=[require_report_hook])]},
        )

        cfg = runtime_config.load()
        if cfg.model_main:
            self.options = replace(self.options, model=cfg.model_main)
        if cfg.thinking_main:
            self.options = replace(self.options, thinking=_thinking(True, cfg.max_thinking_tokens))

        self._client: ClaudeSDKClient | None = None
        self._fork_client: ClaudeSDKClient | None = None
        self._fork_session_id: str | None = None
        self._lock = asyncio.Lock()
        self._compacting = False
        self._bg_tasks: set[asyncio.Task[None]] = set()

    @property
    def in_fork(self) -> bool:
        return self._fork_client is not None

    @property
    def is_compacting(self) -> bool:
        return self._compacting

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
        self.options = replace(self.options, thinking=_thinking(enabled, runtime_config.load().max_thinking_tokens))
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
            self.options = replace(self.options, thinking=_thinking(cfg.thinking_main, cfg.max_thinking_tokens))
        elif key in (
            "thinking_fork",
            "bg_fork_timeout",
            "fork_idle_timeout",
            "auto_update",
            "auto_update_interval",
            "auto_update_hour",
        ):
            pass  # takes effect on next cycle / next fork
        elif key == "max_thinking_tokens":
            cur = self.options.thinking
            if cur and cur["type"] == "enabled":
                self.options = replace(self.options, thinking=_thinking(True, cfg.max_thinking_tokens))
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

    async def exit_interactive_fork(self, action: ForkExitAction) -> bool:
        """Exit interactive fork: promote (SAVE), report (REPORT), or discard (EXIT).

        Returns True if SAVE successfully promoted the fork to main session.
        """
        cancel_pending()
        client = self._fork_client
        session_id = self._fork_session_id
        self._fork_client = None
        self._fork_session_id = None
        set_interactive_fork(False)

        if client is None:
            return False

        if action is ForkExitAction.SAVE and session_id is not None:
            await self.swap_client(client, session_id)
            return True

        with contextlib.suppress(CLIConnectionError):
            await client.interrupt()
        with contextlib.suppress(RuntimeError):
            await client.disconnect()
        return False

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
            opts = replace(opts, thinking=_thinking(thinking, runtime_config.load().max_thinking_tokens))
        opts = tool_policy.apply_tool_restrictions(opts, allowed_tools)
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
        opts = replace(opts, thinking=_thinking(thinking, runtime_config.load().max_thinking_tokens))
        opts = tool_policy.apply_tool_restrictions(opts, allowed_tools)
        client = ClaudeSDKClient(opts)
        await client.connect()
        return client

    async def run_on_client(self, client: ClaudeSDKClient, message: str, *, prepend_updates: bool = True) -> str:
        """Send a message on an explicit client, discard output, return session_id."""
        if prepend_updates:
            message = await prepend_context(message, clear=False)
        else:
            message = f"{timestamp()} {message}"
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
        async for msg in client.receive_response():
            if isinstance(msg, SystemMessage):
                if msg.subtype == "compact_boundary":
                    meta = msg.data.get("compact_metadata", {})
                    pre_tokens = meta.get("pre_tokens")
            elif isinstance(msg, ResultMessage):
                result_msg = msg
                if self._client is client:
                    save_session_id(msg.session_id)

        return format_compact_stats(result_msg, pre_tokens)

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
            message = await prepend_context(message, clear=False)
            return self._fork_client, message
        has_updates = bool(peek_pending_updates())
        message = await prepend_context(message)
        if has_updates:
            with contextlib.suppress(Exception):
                await get_channel().send("-# catching up on background activity...")
        client = await self._get_client()
        return client, message

    def _try_capture_fork_session(self, session_id: str) -> None:
        """Capture fork session ID idempotently (first call wins)."""
        if self._fork_session_id is not None:
            return
        self._fork_session_id = session_id
        log_session_event(session_id, "interactive_fork", parent_session_id=load_session_id())

    def _save_result_session(self, client: ClaudeSDKClient, msg: ResultMessage) -> None:
        """Save session ID from a ResultMessage."""
        if self._fork_client is not None and client is self._fork_client:
            self._try_capture_fork_session(msg.session_id)
        elif self._client is client:
            save_session_id(msg.session_id)

    def _capture_fork_session(self, client: ClaudeSDKClient) -> Callable[[str], None] | None:
        """Return a callback for fork session capture, or None if not in a fork."""
        if self._fork_client is None or client is not self._fork_client:
            return None
        return self._try_capture_fork_session

    async def stream_chat(
        self,
        message: str,
        *,
        images: list[dict[str, str]] | None = None,
    ) -> AsyncGenerator[str | StreamStatus, None]:
        """Yield text deltas and StreamStatus signals for live progress display."""
        client, message = await self._resolve_client(message)
        try:
            async for item in stream_response(
                client,
                message,
                images=images,
                on_fork_session=self._capture_fork_session(client),
                on_result_session=self._save_result_session,
            ):
                if isinstance(item, StreamStatus) and item.kind == "compact_start":
                    self._compacting = True
                yield item
        finally:
            self._compacting = False
