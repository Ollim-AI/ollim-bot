"""Single-owner DM channel — set once at startup, read everywhere."""

from typing import Any

_channel: Any = None


def init_channel(channel: object) -> None:
    """Called once in on_ready after owner.create_dm()."""
    global _channel
    _channel = channel


def get_channel() -> Any:
    """Return the DM channel."""
    return _channel
