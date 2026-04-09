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
    target: Path,
    ts: datetime,
    *,
    report_message: str | None = None,
    error_info: str | None = None,
    timed_out: bool = False,
    timeout_seconds: int = 0,
) -> str:
    """Build the Haiku reflection prompt text."""
    if timed_out:
        status = f"timed out after {timeout_seconds // 60} minutes"
    elif error_info:
        status = f"failed: {error_info}"
    else:
        status = "completed"

    report_section = f"Report filed: {report_message}" if report_message else "No report filed."

    # Pre-fill all deterministic fields — Haiku only generates the Trace.
    file_path = target.relative_to(REFLECTIONS_DIR.parent)
    prefilled = (
        f"# {item_id} \u2014 {ts.isoformat()}\n\n"
        f"**Status:** {status}\n"
        f"**Report filed:** {'yes' if report_message else 'no'}\n"
        f"**Errors:** {error_info or 'none'}\n"
    )

    return (
        f"Write a structured execution trace to: {file_path}\n\n"
        f"Task: {tag}\n"
        f"Description: {description}\n"
        f"Status: {status}\n"
        f"{report_section}\n\n"
        f"Write this content, replacing only the TRACE line:\n\n"
        f"{prefilled}"
        "**Trace:** <1-3 factual sentences: what the task was supposed to do "
        "based on the description, and what the status indicates happened>\n"
    )


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
    """Spawn an isolated Haiku client to write a reflection file.

    Takes ``description`` (from Routine/Reminder), not the bg fork prompt —
    the prompt is preamble boilerplate; skill content is loaded by the SDK
    separately and never appears in the prompt string.
    """
    ts = datetime.now(UTC)
    target = reflection_path(item_id, ts)
    prompt = build_reflection_prompt(
        tag,
        item_id,
        description,
        target,
        ts,
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
