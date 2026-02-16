"""MCP tools for Discord interactions (embeds, buttons)."""

from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from ollim_bot.views import (
    ButtonConfig,
    EmbedConfig,
    EmbedField,
    build_embed,
    build_view,
)

# Module-level channel reference, set by bot.py before each stream_chat().
# Safe because the per-user lock serializes access (single-user bot).
_channel = None


def set_channel(channel) -> None:
    """Set the active Discord channel for tool handlers."""
    global _channel
    _channel = channel


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
        title=args.get("title", ""),
        description=args.get("description"),
        color=args.get("color", "blue"),
        fields=[EmbedField(**f) for f in args.get("fields", [])],
        buttons=[ButtonConfig(**b) for b in args.get("buttons", [])],
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


discord_server = create_sdk_mcp_server("discord", tools=[discord_embed, ping_user])
