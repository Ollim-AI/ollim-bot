# ollim-bot
# Copyright (C) 2025-2026 Julius Frost
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""Persistent runtime configuration — settings that survive restarts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import NamedTuple

from ollim_bot.storage import STATE_DIR, atomic_write, safe_json_load

CONFIG_FILE: Path = STATE_DIR / "config.json"

_MODELS = {"opus", "sonnet", "haiku"}
BYPASS_PERMISSIONS = "bypassPermissions"
_PERMISSION_MODES = {"dontAsk", "default", "acceptEdits", BYPASS_PERMISSIONS}
_BOOL_TRUE = {"on", "true", "1", "yes"}
_BOOL_FALSE = {"off", "false", "0", "no"}
_THINKING_NAMED = {"off", "adaptive"}


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    model_main: str | None = None  # None = SDK default
    model_fork: str | None = None  # None = inherit from model_main
    thinking_main: str = "off"  # "off" | "adaptive" | str(budget_tokens int)
    thinking_fork: str = "adaptive"
    bg_fork_timeout: int = 1800  # seconds
    fork_idle_timeout: int = 10  # minutes
    permission_mode: str = "dontAsk"
    auto_update: bool = False
    auto_update_interval: int = 60  # minutes
    auto_update_hour: int = 6  # 0-23, hour when updates are applied
    google_calendars: str = "primary"  # comma-separated calendar IDs
    google_task_list: str = "@default"  # Google Tasks list ID


_DEFAULTS = RuntimeConfig()


class _KeyMeta(NamedTuple):
    display: str
    description: str
    kind: str  # "model", "bool", "int", "permission_mode"
    options: str = ""  # human-readable options hint


_KEY_META: dict[str, _KeyMeta] = {
    "model_main": _KeyMeta("model.main", "Default model for main session", "model", "opus / sonnet / haiku / default"),
    "model_fork": _KeyMeta(
        "model.fork", "Default model for interactive forks", "model", "opus / sonnet / haiku / default"
    ),
    "thinking_main": _KeyMeta(
        "thinking.main", "Extended thinking for main session", "thinking", "off / adaptive / <budget>"
    ),
    "thinking_fork": _KeyMeta(
        "thinking.fork", "Extended thinking for interactive forks", "thinking", "off / adaptive / <budget>"
    ),
    "bg_fork_timeout": _KeyMeta("bg_fork_timeout", "Max background fork runtime (seconds)", "int"),
    "fork_idle_timeout": _KeyMeta("fork_idle_timeout", "Interactive fork idle timeout (minutes)", "int"),
    "permission_mode": _KeyMeta(
        "permission_mode",
        "Default permission mode",
        "permission_mode",
        "dontAsk / default / acceptEdits / bypassPermissions",
    ),
    "auto_update": _KeyMeta("auto_update", "Auto-pull and restart on new commits", "bool", "on / off"),
    "auto_update_interval": _KeyMeta("auto_update_interval", "Update check interval (minutes)", "int"),
    "auto_update_hour": _KeyMeta("auto_update_hour", "Hour to apply updates (0-23)", "hour", "0-23"),
    "google_calendars": _KeyMeta("google.calendars", "Calendar IDs to query", "str", "comma-separated IDs"),
    "google_task_list": _KeyMeta("google.task_list", "Task list ID", "str"),
}

VALID_KEYS = frozenset(_KEY_META)


def _migrate_thinking(value: object) -> str:
    if value is True:
        return "adaptive"
    if value is False:
        return "off"
    return str(value)


def load() -> RuntimeConfig:
    data = safe_json_load(CONFIG_FILE)
    if not data:
        return _DEFAULTS
    known = {f.name for f in fields(RuntimeConfig)}
    filtered = {k: v for k, v in data.items() if k in known}
    for key in ("thinking_main", "thinking_fork"):
        if key in filtered and isinstance(filtered[key], bool):
            filtered[key] = _migrate_thinking(filtered[key])
    return RuntimeConfig(**filtered)


def save(config: RuntimeConfig) -> None:
    """Atomic write. No git commit — ephemeral state."""
    atomic_write(CONFIG_FILE, json.dumps(asdict(config)).encode())


def _parse_value(key: str, raw: str) -> str | int | bool | None:
    meta = _KEY_META[key]
    if meta.kind == "model":
        lowered = raw.lower().strip()
        if lowered in ("", "null", "none", "default"):
            return None
        if lowered not in _MODELS:
            raise ValueError(f"must be one of: {', '.join(sorted(_MODELS))}")
        return lowered
    if meta.kind == "bool":
        lowered = raw.lower().strip()
        if lowered in _BOOL_TRUE:
            return True
        if lowered in _BOOL_FALSE:
            return False
        raise ValueError("must be on/off")
    if meta.kind == "thinking":
        lowered = raw.lower().strip()
        if lowered in _THINKING_NAMED:
            return lowered
        if lowered.isdigit() and int(lowered) > 0:
            return lowered
        raise ValueError("must be 'off', 'adaptive', or a positive integer (budget tokens)")
    if meta.kind == "int":
        stripped = raw.strip()
        if not stripped.isdigit():
            raise ValueError("must be a positive integer")
        val = int(stripped)
        if val <= 0:
            raise ValueError("must be a positive integer")
        return val
    if meta.kind == "hour":
        stripped = raw.strip()
        if not stripped.isdigit():
            raise ValueError("must be an integer 0-23")
        val = int(stripped)
        if val > 23:
            raise ValueError("must be an integer 0-23")
        return val
    if meta.kind == "permission_mode":
        stripped = raw.strip()
        if stripped not in _PERMISSION_MODES:
            raise ValueError(f"must be one of: {', '.join(sorted(_PERMISSION_MODES))}")
        return stripped
    if meta.kind == "str":
        stripped = raw.strip()
        if not stripped:
            raise ValueError("must not be empty")
        return stripped
    raise ValueError(f"unknown key kind: {meta.kind}")


def set_value(key: str, raw: str) -> RuntimeConfig:
    if key not in _KEY_META:
        raise ValueError(f"unknown key: {key}")
    parsed = _parse_value(key, raw)
    config = load()
    config = replace(config, **{key: parsed})
    save(config)
    return config


def _format_value(key: str, value: str | int | bool | None) -> str:
    meta = _KEY_META[key]
    default = getattr(_DEFAULTS, key)
    is_default = value == default

    if meta.kind == "model":
        if value is None:
            if key == "model_fork":
                label = "(inherit main)"
            else:
                label = "(default)"
            return label
        return f"{value} (default)" if is_default else str(value)

    if meta.kind == "bool":
        label = "on" if value else "off"
        return f"{label} (default)" if is_default else label

    if meta.kind == "thinking":
        s = str(value)
        label = f"{int(s) // 1000}k budget" if s.isdigit() else s
        return f"{label} (default)" if is_default else label

    if key == "bg_fork_timeout":
        label = f"{value}s"
        return f"{label} (default)" if is_default else label

    if key in ("fork_idle_timeout", "auto_update_interval"):
        label = f"{value}m"
        return f"{label} (default)" if is_default else label

    if meta.kind == "hour":
        label = f"{value}:00"
        return f"{label} (default)" if is_default else label

    label = str(value)
    return f"{label} (default)" if is_default else label


def format_all() -> str:
    config = load()
    lines: list[str] = []
    for key, meta in _KEY_META.items():
        value = getattr(config, key)
        line = f"**{meta.display}**: {_format_value(key, value)}"
        if meta.options:
            line += f"  `{meta.options}`"
        lines.append(line)
    return "\n".join(lines)


def format_one(key: str) -> str:
    config = load()
    meta = _KEY_META[key]
    value = getattr(config, key)
    line = f"**{meta.display}**: {_format_value(key, value)}"
    if meta.options:
        line += f"  `{meta.options}`"
    return line
