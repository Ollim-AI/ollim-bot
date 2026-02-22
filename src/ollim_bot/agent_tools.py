"""MCP tool definitions for agent interactions (embeds, buttons, chains, forks)."""

import subprocess
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Literal

from claude_agent_sdk import create_sdk_mcp_server, tool
from claude_agent_sdk.types import HookContext, HookInput, SyncHookJSONOutput

from ollim_bot import ping_budget
from ollim_bot.config import USER_NAME
from ollim_bot.sessions import track_message
from ollim_bot.embeds import (
    ButtonConfig,
    EmbedConfig,
    EmbedField,
    build_embed,
    build_view,
)
from ollim_bot.forks import (
    ForkExitAction,
    append_update,
    clear_pending_updates,
    in_bg_fork,
    in_interactive_fork,
    request_enter_fork,
    set_exit_action,
)

# ---------------------------------------------------------------------------
# Channel reference — globals for main session, contextvars for bg forks
# ---------------------------------------------------------------------------

_channel: Any = None
_channel_var: ContextVar[Any] = ContextVar("_channel", default=None)


def set_channel(channel: object) -> None:
    """Set channel global — used by main session (protected by agent lock)."""
    global _channel
    _channel = channel


def set_fork_channel(channel: object) -> None:
    """Set channel via contextvar — used by bg forks (no lock needed)."""
    _channel_var.set(channel)


# ---------------------------------------------------------------------------
# Chain context — same dual pattern
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChainContext:
    reminder_id: str
    message: str
    chain_depth: int
    max_chain: int
    chain_parent: str
    background: bool
    model: str | None = None
    isolated: bool = False


_chain_context: ChainContext | None = None
_chain_context_var: ContextVar[ChainContext | None] = ContextVar(
    "_chain_context", default=None
)


def set_chain_context(ctx: ChainContext | None) -> None:
    """Set chain context global — used by foreground reminders."""
    global _chain_context
    _chain_context = ctx


def set_fork_chain_context(ctx: ChainContext | None) -> None:
    """Set chain context via contextvar — used by bg reminders."""
    _chain_context_var.set(ctx)


# ---------------------------------------------------------------------------
# Bg output tracking — prevents bg forks from stopping without reporting
# ---------------------------------------------------------------------------

_bg_output_sent_var: ContextVar[bool] = ContextVar("_bg_output_sent", default=False)


def bg_output_sent() -> bool:
    return _bg_output_sent_var.get()


def _source() -> Literal["main", "bg", "fork"]:  # duplicate-ok
    """Return the execution context: main session, bg fork, or interactive fork."""
    if in_bg_fork():
        return "bg"
    if in_interactive_fork():
        return "fork"
    return "main"


def _check_bg_budget(args: dict[str, Any]) -> dict[str, Any] | None:
    """Check ping budget for bg forks. Returns error dict if exhausted, None if OK."""
    critical = args.get("critical", False)
    if not critical and not ping_budget.try_use():
        return {
            "content": [
                {
                    "type": "text",
                    "text": "Budget exhausted (0 remaining). Use critical=True "
                    "only for genuinely urgent items.",
                }
            ]
        }
    if critical:
        ping_budget.record_critical()
    return None


@tool(
    "discord_embed",
    "Send a rich embed message with optional action buttons to the Discord channel. "
    "Use for task lists, calendar views, email digests, or any structured data.",
    {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Embed title"},
            "description": {"type": "string", "description": "Embed body text"},
            "color": {"type": "string", "description": "blue, green, red, or yellow"},
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "value": {"type": "string"},
                        "inline": {"type": "boolean"},
                    },
                    "required": ["name", "value"],
                },
            },
            "buttons": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "style": {"type": "string"},
                        "action": {"type": "string"},
                    },
                    "required": ["label", "action"],
                },
            },
            "critical": {
                "type": "boolean",
                "description": "Set true only for genuinely urgent/time-sensitive items",
            },
        },
        "required": ["title"],
    },
)
async def discord_embed(args: dict[str, Any]) -> dict[str, Any]:
    channel = _channel_var.get() or _channel
    if channel is None:
        return {"content": [{"type": "text", "text": "Error: no active channel"}]}

    if _source() == "bg":
        if budget_error := _check_bg_budget(args):
            return budget_error

    config = EmbedConfig(
        title=args["title"],
        description=args.get("description"),
        color=args.get("color", "blue"),
        fields=tuple(EmbedField(**f) for f in args.get("fields", [])),
        buttons=tuple(ButtonConfig(**b) for b in args.get("buttons", [])),
    )
    embed = build_embed(config)
    source = _source()
    if source != "main":
        embed.set_footer(text=source)
    view = build_view(config.buttons)
    msg = await channel.send(embed=embed, view=view)
    track_message(msg.id)
    if source == "bg":
        _bg_output_sent_var.set(True)
    return {"content": [{"type": "text", "text": "Embed sent."}]}


@tool(
    "ping_user",
    f"Send a plain text message to {USER_NAME}. Use in background mode when something "
    "needs attention but an embed isn't necessary.",
    {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "The message to send",
            },
            "critical": {
                "type": "boolean",
                "description": "Set true only for genuinely urgent/time-sensitive items",
            },
        },
        "required": ["message"],
    },
)
async def ping_user(args: dict[str, Any]) -> dict[str, Any]:
    if _source() != "bg":
        return {
            "content": [
                {
                    "type": "text",
                    "text": "Error: ping_user is only available in background forks",
                }
            ]
        }
    if budget_error := _check_bg_budget(args):
        return budget_error
    channel = _channel_var.get() or _channel
    if channel is None:
        return {"content": [{"type": "text", "text": "Error: no active channel"}]}

    msg = await channel.send(f"[bg] {args['message']}")
    track_message(msg.id)
    _bg_output_sent_var.set(True)
    return {"content": [{"type": "text", "text": "Message sent."}]}


@tool(
    "follow_up_chain",
    "Schedule a follow-up check for this reminder. Call with minutes_from_now to "
    "check again later. If the task is done or no follow-up needed, simply don't "
    "call this tool and the chain ends.",
    {
        "type": "object",
        "properties": {
            "minutes_from_now": {
                "type": "integer",
                "description": "Minutes until the next check",
            },
        },
        "required": ["minutes_from_now"],
    },
)
async def follow_up_chain(args: dict[str, Any]) -> dict[str, Any]:
    ctx = _chain_context_var.get() or _chain_context
    if ctx is None:
        return {
            "content": [{"type": "text", "text": "Error: no active reminder context"}]
        }
    if ctx.chain_depth >= ctx.max_chain:
        return {"content": [{"type": "text", "text": "Error: follow-up limit reached"}]}

    minutes = args["minutes_from_now"]
    cmd = [
        "ollim-bot",
        "reminder",
        "add",
        "--delay",
        str(minutes),
        "-m",
        ctx.message,
        "--max-chain",
        str(ctx.max_chain),
        "--chain-depth",
        str(ctx.chain_depth + 1),
        "--chain-parent",
        ctx.chain_parent,
    ]
    if ctx.background:
        cmd.append("--background")
    if ctx.model:
        cmd.extend(["--model", ctx.model])
    if ctx.isolated:
        cmd.append("--isolated")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return {
            "content": [
                {"type": "text", "text": f"Error scheduling follow-up: {result.stderr}"}
            ]
        }
    return {
        "content": [
            {"type": "text", "text": f"Follow-up scheduled in {minutes} minutes"}
        ]
    }


@tool(
    "save_context",
    "Promote the current interactive fork to the main session. Only available "
    "in interactive forks. If you don't call this, everything from this fork "
    "is discarded.",
    {
        "type": "object",
        "properties": {},
    },
)
async def save_context(args: dict[str, Any]) -> dict[str, Any]:
    if in_bg_fork():
        return {
            "content": [
                {"type": "text", "text": "Error: not available in background forks"}
            ]
        }
    if not in_interactive_fork():
        return {
            "content": [{"type": "text", "text": "Error: not in an interactive fork"}]
        }
    set_exit_action(ForkExitAction.SAVE)
    clear_pending_updates()
    return {
        "content": [
            {
                "type": "text",
                "text": "Context saved. Fork will be promoted to main session "
                "after you finish responding.",
            }
        ]
    }


@tool(
    "report_updates",
    "Report a short summary from this fork to the main conversation. "
    "The fork is discarded but the summary is injected into the next main-session "
    "message. Use for lightweight findings that don't need full context preservation.",
    {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Short summary of what was found",
            },
        },
        "required": ["message"],
    },
)
async def report_updates(args: dict[str, Any]) -> dict[str, Any]:
    if in_bg_fork():
        await append_update(args["message"])
        _bg_output_sent_var.set(False)
        return {
            "content": [
                {
                    "type": "text",
                    "text": "Update reported -- summary will appear in main session.",
                }
            ]
        }
    if in_interactive_fork():
        set_exit_action(ForkExitAction.REPORT)
        await append_update(args["message"])
        return {
            "content": [
                {
                    "type": "text",
                    "text": "Update reported. Fork will be discarded after you "
                    "finish responding — further tool calls delay the exit.",
                }
            ]
        }
    return {"content": [{"type": "text", "text": "Error: not in a forked session"}]}


@tool(
    "enter_fork",
    "Start an interactive forked session for research, tangents, or focused work. "
    "The fork branches from the main conversation. Use exit_fork, save_context, or "
    "report_updates to end it.",
    {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "Optional topic for the fork",
            },
            "idle_timeout": {
                "type": "integer",
                "description": "Minutes before idle timeout prompt (default 10)",
            },
        },
    },
)
async def enter_fork(args: dict[str, Any]) -> dict[str, Any]:
    if in_bg_fork() or in_interactive_fork():
        return {"content": [{"type": "text", "text": "Error: already in a fork"}]}
    request_enter_fork(args.get("topic"), idle_timeout=args.get("idle_timeout", 10))
    return {
        "content": [
            {
                "type": "text",
                "text": "Fork will start after you finish responding — "
                "further tool calls delay the fork and run on the "
                "main session, not the fork.",
            }
        ]
    }


@tool(
    "exit_fork",
    "Exit the current interactive fork. The fork is discarded and the main "
    "session resumes.",
    {"type": "object", "properties": {}},
)
async def exit_fork(args: dict[str, Any]) -> dict[str, Any]:
    if in_bg_fork():
        return {
            "content": [
                {"type": "text", "text": "Error: not available in background forks"}
            ]
        }
    if not in_interactive_fork():
        return {
            "content": [{"type": "text", "text": "Error: not in an interactive fork"}]
        }
    set_exit_action(ForkExitAction.EXIT)
    return {
        "content": [
            {
                "type": "text",
                "text": "Fork will be discarded after you finish responding "
                "— further tool calls delay the exit.",
            }
        ]
    }


async def require_report_hook(
    input_data: HookInput,
    tool_use_id: str | None,
    context: HookContext,
) -> SyncHookJSONOutput:
    """Stop hook: prevent bg fork from stopping with unreported output."""
    if not in_bg_fork() or not _bg_output_sent_var.get():
        return {}
    return SyncHookJSONOutput(
        systemMessage=(
            "You sent visible output (ping/embed) but haven't called "
            "report_updates. Call it now to bridge your findings to the "
            "main session."
        ),
    )


agent_server = create_sdk_mcp_server(
    "discord",
    tools=[
        discord_embed,
        ping_user,
        follow_up_chain,
        save_context,
        report_updates,
        enter_fork,
        exit_fork,
    ],
)
