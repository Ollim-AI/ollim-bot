"""Webhook HTTP server for external triggers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ollim_bot.storage import DATA_DIR, read_md_dir

log = logging.getLogger(__name__)

WEBHOOKS_DIR = DATA_DIR / "webhooks"


@dataclass(frozen=True, slots=True)
class WebhookSpec:
    id: str
    message: str
    fields: dict[str, Any]
    isolated: bool = False
    model: str | None = None
    thinking: bool = True
    allow_ping: bool = True
    update_main_session: str = "on_ping"


def list_webhooks() -> list[WebhookSpec]:
    """Read all webhook spec files from the webhooks directory."""
    return read_md_dir(WEBHOOKS_DIR, WebhookSpec)


def load_webhook(slug: str) -> WebhookSpec | None:
    """Load a single webhook spec by its id."""
    for spec in list_webhooks():
        if spec.id == slug:
            return spec
    return None
