"""Single-owner DM channel — set once at startup, read everywhere."""

from typing import Any

_channel: Any = None


def init_channel(channel: object) -> None:
    global _channel
    _channel = channel


def get_channel() -> Any:
    return _channel
