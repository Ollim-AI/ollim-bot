"""Embed/button types and builders shared by discord_tools and views."""

import re
from dataclasses import dataclass, field
from typing import Literal

import discord
from discord.ui import Button, View

from ollim_bot import inquiries

ButtonStyle = Literal["primary", "secondary", "success", "danger"]
EmbedColor = Literal["blue", "green", "red", "yellow", "purple"]


@dataclass(frozen=True, slots=True)
class EmbedField:
    name: str
    value: str
    inline: bool = True


@dataclass(frozen=True, slots=True)
class ButtonConfig:
    label: str
    action: str
    style: ButtonStyle = "secondary"


@dataclass(frozen=True, slots=True)
class EmbedConfig:
    title: str
    description: str | None = None
    color: EmbedColor = "blue"
    fields: tuple[EmbedField, ...] = field(default_factory=tuple)
    buttons: tuple[ButtonConfig, ...] = field(default_factory=tuple)


STYLE_MAP: dict[ButtonStyle, discord.ButtonStyle] = {
    "primary": discord.ButtonStyle.primary,
    "secondary": discord.ButtonStyle.secondary,
    "success": discord.ButtonStyle.success,
    "danger": discord.ButtonStyle.danger,
}

COLOR_MAP: dict[EmbedColor, discord.Color] = {
    "blue": discord.Color.blue(),
    "green": discord.Color.green(),
    "red": discord.Color.red(),
    "yellow": discord.Color.yellow(),
    "purple": discord.Color.purple(),
}

_EMOJI_RE = re.compile(
    r"[\U0001f300-\U0001faff\u2600-\u27bf\u23e9-\u23fa\ufe0f\u200d]+\s*",
)


def build_embed(config: EmbedConfig) -> discord.Embed:
    """Strips emoji from the title to keep Discord embed headings clean."""
    color = COLOR_MAP.get(config.color, discord.Color.blue())
    title = _EMOJI_RE.sub("", config.title).strip() if config.title else None
    embed = discord.Embed(
        title=title,
        description=config.description,
        color=color,
    )
    for ef in config.fields:
        embed.add_field(name=ef.name, value=ef.value, inline=ef.inline)
    return embed


def build_view(buttons: tuple[ButtonConfig, ...]) -> View | None:
    """Returns None when empty; caps at 25 buttons (Discord limit).

    ``agent:`` actions persist their prompt via inquiries so buttons survive restarts.
    """
    if not buttons:
        return None
    view = View(timeout=None)
    for btn in buttons[:25]:
        action = btn.action
        style = STYLE_MAP.get(btn.style, discord.ButtonStyle.secondary)

        # Persist prompt so the button survives bot restarts
        if action.startswith("agent:"):
            uid = inquiries.register(action[6:])
            custom_id = f"act:agent:{uid}"
        elif ":" in action:
            custom_id = f"act:{action}"
        else:
            custom_id = f"act:{action}:_"

        view.add_item(
            Button(label=btn.label, style=style, custom_id=custom_id),
        )
    return view
