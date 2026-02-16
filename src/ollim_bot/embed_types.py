"""Structured types for embed/button configs passed between modules."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class EmbedField:
    name: str
    value: str
    inline: bool = True


@dataclass(frozen=True, slots=True)
class ButtonConfig:
    label: str
    action: str
    style: str = "secondary"


@dataclass(frozen=True, slots=True)
class EmbedConfig:
    title: str
    description: str | None = None
    color: str = "blue"
    fields: list[EmbedField] = field(default_factory=list)
    buttons: list[ButtonConfig] = field(default_factory=list)
