"""MCP tool definitions for agent interactions (embeds, buttons, chains, forks)."""

import subprocess
from dataclasses import dataclass
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from ollim_bot.embeds import (
    ButtonConfig,
    EmbedConfig,
    EmbedField,
    build_embed,
    build_view,
)
from ollim_bot.forks import _append_update, clear_pending_updates

# Module-level channel reference, set by bot.py before each stream_chat().
# Safe because the per-user lock serializes access (single-user bot).
_channel = None


def set_channel(channel: object) -> None:
    """Must be called before every stream_chat() or tools dispatch to a stale channel."""
    global _channel
    _channel = channel


# Set immediately before the agent fires, cleared in fire_oneshot() after dispatch.
@dataclass(frozen=True, slots=True)
class ChainContext:
    reminder_id: str
    message: str
    chain_depth: int
    max_chain: int
    chain_parent: str
    background: bool


_chain_context: ChainContext | None = None


def set_chain_context(ctx: ChainContext | None) -> None:
    """Pass None to clear context after a chain reminder fires."""
    global _chain_context
    _chain_context = ctx


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
        },
        "required": ["title"],
    },
)
async def discord_embed(args: dict[str, Any]) -> dict[str, Any]:
    channel = _channel
    if channel is None:
        return {"content": [{"type": "text", "text": "Error: no active channel"}]}

    config = EmbedConfig(
        title=args["title"],
        description=args.get("description"),
        color=args.get("color", "blue"),
        fields=tuple(EmbedField(**f) for f in args.get("fields", [])),
        buttons=tuple(ButtonConfig(**b) for b in args.get("buttons", [])),
    )
    embed = build_embed(config)
    view = build_view(config.buttons)
    await channel.send(embed=embed, view=view)
    return {"content": [{"type": "text", "text": "Embed sent."}]}


@tool(
    "ping_user",
    "Send a plain text message to Julius. Use in background mode when something "
    "needs attention but an embed isn't necessary.",
    {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "The message to send",
            },
        },
        "required": ["message"],
    },
)
async def ping_user(args: dict[str, Any]) -> dict[str, Any]:
    channel = _channel
    if channel is None:
        return {"content": [{"type": "text", "text": "Error: no active channel"}]}

    await channel.send(args["message"])
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
    ctx = _chain_context
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
    "Signal that this background check produced useful context worth keeping in "
    "the conversation. Call this when you found something noteworthy, sent an alert, "
    "or made a decision the user should see in history. If you don't call this, "
    "everything from this check is discarded.",
    {
        "type": "object",
        "properties": {},
    },
)
async def save_context(args: dict[str, Any]) -> dict[str, Any]:
    import ollim_bot.forks as forks_mod

    if not forks_mod._in_fork:
        return {
            "content": [
                {"type": "text", "text": "Error: not in a forked background session"}
            ]
        }
    forks_mod._fork_saved = True
    clear_pending_updates()
    return {
        "content": [
            {"type": "text", "text": "Context saved -- this session will be preserved."}
        ]
    }


@tool(
    "report_updates",
    "Report a short summary from this background check to the main conversation. "
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
    import ollim_bot.forks as forks_mod

    if not forks_mod._in_fork:
        return {
            "content": [
                {"type": "text", "text": "Error: not in a forked background session"}
            ]
        }
    _append_update(args["message"])
    return {
        "content": [
            {
                "type": "text",
                "text": "Update reported -- summary will appear in main session.",
            }
        ]
    }


agent_server = create_sdk_mcp_server(
    "discord",
    tools=[discord_embed, ping_user, follow_up_chain, save_context, report_updates],
)
