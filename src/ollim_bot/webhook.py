"""Webhook HTTP server for external triggers."""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft7Validator

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


_DEFAULT_MAX_LENGTH = 500
_MAX_PROPERTIES = 20


def _inject_default_max_length(schema: dict[str, Any]) -> dict[str, Any]:
    """Add maxLength to string properties that don't specify one."""
    schema = copy.deepcopy(schema)
    for prop in schema.get("properties", {}).values():
        if prop.get("type") == "string" and "maxLength" not in prop:
            prop["maxLength"] = _DEFAULT_MAX_LENGTH
    return schema


def validate_payload(schema: dict[str, Any], data: dict[str, Any]) -> list[str]:
    """Validate data against JSON Schema. Returns list of error messages."""
    properties = schema.get("properties", {})
    if len(properties) > _MAX_PROPERTIES:
        return [f"Too many properties ({len(properties)}, max {_MAX_PROPERTIES})"]

    enriched = _inject_default_max_length(schema)
    validator = Draft7Validator(enriched)
    return [err.message for err in validator.iter_errors(data)]
