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
"""Structural reflections: post-fork execution traces for debugging."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ollim_bot.storage import DATA_DIR

if TYPE_CHECKING:
    from ollim_bot.agent import Agent

log = logging.getLogger(__name__)

REFLECTIONS_DIR = DATA_DIR / "reflections"


def reflection_path(item_id: str, ts: datetime) -> Path:
    """Return ``REFLECTIONS_DIR / item_id / <timestamp>.md``."""
    stamp = ts.strftime("%Y-%m-%dT%H-%M-%SZ")
    return REFLECTIONS_DIR / item_id / f"{stamp}.md"


def build_reflection_prompt(
    tag: str,
    item_id: str,
    description: str,
    *,
    report_message: str | None = None,
    error_info: str | None = None,
    timed_out: bool = False,
    timeout_seconds: int = 0,
) -> tuple[str, Path]:
    """Build the Haiku reflection prompt and target file path."""
    ts = datetime.now(UTC)
    target = reflection_path(item_id, ts)

    if timed_out:
        status = f"timed out after {timeout_seconds // 60} minutes"
    elif error_info:
        status = f"failed: {error_info}"
    else:
        status = "completed"

    report_section = f"Report filed: {report_message}" if report_message else "No report filed."

    prompt = (
        "You are writing a structured execution trace for a background task "
        "that just completed.\n\n"
        f"Task: {tag}\n"
        f"Description: {description}\n"
        f"Status: {status}\n"
        f"{report_section}\n\n"
        f"Write the reflection to: {target.relative_to(REFLECTIONS_DIR.parent)}\n\n"
        "Use this exact format:\n\n"
        f"# {item_id} \u2014 {ts.isoformat()}\n\n"
        f"**Status:** {status}\n"
        f"**Report filed:** {'yes' if report_message else 'no'}\n"
        "**Tools available:** [list tool names from the description or tag context, if known]\n"
        f"**Errors:** {error_info or 'none'}\n"
        "**Trace:** 1-3 sentences on what the task attempted and what happened, "
        "based on the description and outcome. Be factual.\n"
    )
    return prompt, target


async def run_reflection_fork(
    agent: Agent,
    tag: str,
    item_id: str,
    description: str,
    *,
    report_message: str | None = None,
    error_info: str | None = None,
    timed_out: bool = False,
    timeout_seconds: int = 0,
) -> None:
    """Spawn an isolated Haiku client to write a reflection file."""
    prompt, target = build_reflection_prompt(
        tag,
        item_id,
        description,
        report_message=report_message,
        error_info=error_info,
        timed_out=timed_out,
        timeout_seconds=timeout_seconds,
    )
    target.parent.mkdir(parents=True, exist_ok=True)

    async with asyncio.timeout(60):
        client = await agent.create_isolated_client(
            model="haiku",
            thinking="off",
            allowed_tools=["Write(reflections/**/*.md)"],
            bg=True,
        )
        try:
            await agent.run_on_client(client, prompt, prepend_updates=False)
        finally:
            async with asyncio.timeout(5):
                await client.disconnect()
