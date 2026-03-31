# ollim-bot
# Copyright (C) 2025-2026 Julius Frost
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""Claude Agent SDK wrapper -- the brain of the bot."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
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
from ollim_bot.agent_tools import build_agent_server, require_report_hook
from ollim_bot.channel import get_channel
from ollim_bot.fork_state import (
    ForkExitAction,
    pop_exit_action,
    set_interactive_fork,
    touch_activity,
)
from ollim_bot.forks import peek_pending_updates
from ollim_bot.hooks import (
    auto_commit_hook,
    routine_validator,
    state_dir_guard,
    tool_error_hook,
    tool_failure_hook,
)
from ollim_bot.permissions import (
    cancel_pending,
    clear_denied,
    clear_errored,
    handle_tool_permission,
    set_dont_ask,
)
from ollim_bot.permissions import (
    reset as reset_permissions,
)
from ollim_bot.prompts import build_system_prompt
from ollim_bot.sessions import (
    delete_session_id,
    load_session_id,
    log_session_event,
    save_session_id,
    set_swap_in_progress,
)
from ollim_bot.storage import DATA_DIR
from ollim_bot.streamer import StreamStatus

log = logging.getLogger(__name__)


def _with_thinking(opts: ClaudeAgentOptions, mode: str) -> ClaudeAgentOptions:
    return replace(opts, thinking=_thinking(mode))


class Agent:
    def __init__(self) -> None:
        from ollim_bot.subagents import load_agent_tool_sets

        main_tools = tool_policy.build_main_tools()
        tool_sets: dict[str, list[str]] = {
            "main": list(main_tools),
            **load_agent_tool_sets(),
        }
        tool_policy.scan_all(tool_sets)
        self.options = ClaudeAgentOptions(
            cwd=DATA_DIR,
            include_partial_messages=True,
            can_use_tool=handle_tool_permission,
            system_prompt={
                "type": "preset",
                "preset": "claude_code",
                "append": build_system_prompt(),
            },
            setting_sources=["project"],
            mcp_servers={
                "discord": build_agent_server(),
                "docs": {"type": "http", "url": "https://docs.ollim.ai/mcp"},
            },
            allowed_tools=main_tools,
            permission_mode="default",
            hooks={
                "Stop": [HookMatcher(hooks=[require_report_hook])],
                "PreToolUse": [
                    HookMatcher(matcher="Write|Edit", hooks=[state_dir_guard, routine_validator]),
                ],
                "PostToolUse": [
                    HookMatcher(matcher="Write|Edit", hooks=[auto_commit_hook]),
                    HookMatcher(hooks=[tool_error_hook]),
                ],
                "PostToolUseFailure": [HookMatcher(hooks=[tool_failure_hook])],
            },
        )

        cfg = runtime_config.load()
        if cfg.model_main:
            self.options = replace(self.options, model=cfg.model_main)
        if cfg.permission_mode not in ("dontAsk", "default"):
            self.options = replace(self.options, permission_mode=cfg.permission_mode)
        self.options = _with_thinking(self.options, cfg.thinking_main)

        self._client: ClaudeSDKClient | None = None
        self._fork_client: ClaudeSDKClient | None = None
        self._fork_session_id: str | None = None
        self._lock = asyncio.Lock()
        self._compacting = False
        self._bg_tasks: set[asyncio.Task[None]] = set()
        self._last_input_tokens: int | None = None
        self._last_fork_upgraded: bool = False

    @property
    def in_fork(self) -> bool:
        return self._fork_client is not None

    @property
    def fork_session_id(self) -> str | None:
        return self._fork_session_id

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
            await asyncio.to_thread(log_session_event, current, "cleared")
        await self._drop_client()
        delete_session_id()

    async def set_model(self, model: ModelName) -> None:
        """Also switches any live client in-place (no reconnect needed)."""
        self.options = replace(self.options, model=model)
        if self._client:
            await self._client.set_model(model)
        if self._fork_client:
            await self._fork_client.set_model(model)

    async def set_thinking(self, mode: str) -> None:
        """Drops clients to apply -- no live setter available."""
        self.options = _with_thinking(self.options, mode)
        await self._drop_client()
        if self._fork_client:
            set_dont_ask(runtime_config.load().permission_mode == "dontAsk")
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
        """Fork-scoped: only affects the active fork client when in interactive fork."""
        if self._fork_client:
            await self._fork_client.set_permission_mode(mode)
        elif self._client:
            await self._client.set_permission_mode(mode)
            self.options = replace(self.options, permission_mode=mode)
        else:
            self.options = replace(self.options, permission_mode=mode)

    async def apply_config(self, key: str) -> None:
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
            self.options = _with_thinking(self.options, cfg.thinking_main)
            await self._drop_client()
        elif key in (
            "thinking_fork",
            "bg_fork_timeout",
            "fork_idle_timeout",
            "auto_update",
            "auto_update_interval",
            "auto_update_hour",
        ):
            pass  # takes effect on next cycle / next fork
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
        old = self._client
        old_session_id = load_session_id()
        self._client = client
        set_swap_in_progress(True)
        try:
            await asyncio.to_thread(save_session_id, session_id)
        finally:
            set_swap_in_progress(False)
        await asyncio.to_thread(log_session_event, session_id, "swapped", parent_session_id=old_session_id)
        if old:
            with contextlib.suppress(CLIConnectionError):
                await old.interrupt()
            with contextlib.suppress(RuntimeError):
                await old.disconnect()

    async def enter_interactive_fork(
        self, *, idle_timeout: int | None = None, resume_session_id: str | None = None
    ) -> bool:
        """Enter an interactive fork. Returns True if model was auto-upgraded (haiku→sonnet)."""
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
        set_interactive_fork(True, idle_timeout=idle_timeout, resume_session_id=resume_session_id)
        touch_activity()
        return self._last_fork_upgraded

    async def exit_interactive_fork(self, action: ForkExitAction) -> bool:
        """Exit interactive fork: promote (SAVE), report (REPORT), or discard (EXIT).

        Returns True if SAVE successfully promoted the fork to main session.
        """
        cancel_pending()
        # Restore _dont_ask from persisted config — /permissions during a fork
        # changes it globally, but it should be fork-scoped.
        set_dont_ask(runtime_config.load().permission_mode == "dontAsk")
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
        thinking: str | None = None,
        model: str | None = None,
        allowed_tools: list[str] | None = None,
        bg: bool = False,
    ) -> ClaudeSDKClient:
        """Create a disposable client that forks from a given or current session.

        fork=False resumes the session directly without branching. Use when the
        target is a completed bg fork session that may not support re-forking.
        thinking=None inherits from main session; True/False overrides.
        model=None inherits from main session options.
        bg=True forces permission_mode="default" so canUseTool is always
        reachable — prevents bypassPermissions from skipping tool gating.
        """
        from ollim_bot.agent_streaming import _CONTEXT_WINDOWS

        self._last_fork_upgraded = False
        if (
            model == "haiku"
            and self._last_input_tokens
            and self._last_input_tokens > _CONTEXT_WINDOWS.get("haiku", 200_000)
        ):
            log.warning("context %dk exceeds haiku limit, upgrading fork to sonnet", self._last_input_tokens // 1000)
            model = "sonnet"
            self._last_fork_upgraded = True
        sid = session_id or load_session_id()
        if sid:
            opts = replace(self.options, resume=sid, fork_session=fork)
        else:
            opts = self.options
        if bg:
            opts = replace(opts, permission_mode="default")
        if model:
            opts = replace(opts, model=model)
        if thinking is not None:
            opts = _with_thinking(opts, thinking)
        opts = tool_policy.apply_tool_restrictions(opts, allowed_tools)
        client = ClaudeSDKClient(opts)
        await client.connect()
        return client

    async def create_isolated_client(
        self,
        *,
        model: str | None = None,
        thinking: str = "adaptive",
        allowed_tools: list[str] | None = None,
        bg: bool = False,
    ) -> ClaudeSDKClient:
        """Create a standalone client with no conversation history.

        bg=True forces permission_mode="default" so canUseTool is always
        reachable — prevents bypassPermissions from skipping tool gating.
        """
        opts = self.options
        if bg:
            opts = replace(opts, permission_mode="default")
        if model:
            opts = replace(opts, model=model)
        opts = _with_thinking(opts, thinking)
        opts = tool_policy.apply_tool_restrictions(opts, allowed_tools)
        client = ClaudeSDKClient(opts)
        await client.connect()
        return client

    async def run_on_client(self, client: ClaudeSDKClient, message: str, *, prepend_updates: bool = True) -> str:
        """Discards streaming output -- only the session_id is captured."""
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
                    await asyncio.to_thread(save_session_id, msg.session_id)

        return format_compact_stats(result_msg, pre_tokens)

    async def _run_slash(self, client: ClaudeSDKClient, command: str) -> tuple[list[str], ResultMessage | None]:
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
                    await asyncio.to_thread(save_session_id, msg.session_id)

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
        """Uses fork client if active; otherwise uses main client with update injection."""
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

    async def _try_capture_fork_session(self, session_id: str) -> None:
        """Idempotent -- first call wins."""
        if self._fork_session_id is not None:
            return
        self._fork_session_id = session_id
        await asyncio.to_thread(log_session_event, session_id, "interactive_fork", parent_session_id=load_session_id())

    async def _save_result_session(self, client: ClaudeSDKClient, msg: ResultMessage) -> None:
        if msg.usage:
            self._last_input_tokens = msg.usage.get("input_tokens")
        if self._fork_client is not None and client is self._fork_client:
            await self._try_capture_fork_session(msg.session_id)
        elif self._client is client:
            await asyncio.to_thread(save_session_id, msg.session_id)

    def _capture_fork_session(self, client: ClaudeSDKClient) -> Callable[[str], Awaitable[None]] | None:
        if self._fork_client is None or client is not self._fork_client:
            return None
        return self._try_capture_fork_session

    async def stream_chat(
        self,
        message: str,
        *,
        images: list[dict[str, str]] | None = None,
    ) -> AsyncGenerator[str | StreamStatus, None]:
        clear_denied()
        clear_errored()
        client, message = await self._resolve_client(message)
        from ollim_bot.agent_streaming import _CONTEXT_WINDOWS, _DEFAULT_CONTEXT_WINDOW

        model = self.options.model or ""
        ctx_window = _CONTEXT_WINDOWS.get(model, _DEFAULT_CONTEXT_WINDOW)
        try:
            async for item in stream_response(
                client,
                message,
                images=images,
                on_fork_session=self._capture_fork_session(client),
                on_result_session=self._save_result_session,
                context_window=ctx_window,
            ):
                if isinstance(item, StreamStatus) and item.kind == "compact_start":
                    self._compacting = True
                yield item
        finally:
            self._compacting = False
