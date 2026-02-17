"""Structured types for embed/button configs passed between modules."""

from dataclasses import dataclass, field
from typing import Literal

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
    fields: list[EmbedField] = field(default_factory=list)
    buttons: list[ButtonConfig] = field(default_factory=list)
