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
"""Discord-free chat interface for debugging agent behavior."""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import replace
from typing import Any


class FakeMessage:
    """Minimal duck type for discord.Message — satisfies track_message(msg.id)."""

    def __init__(self, id: int) -> None:
        self.id = id


class ChatChannel:
    """Duck-typed discord.TextChannel that prints to stdout and records calls."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self._counter = 0

    async def send(
        self,
        content: str | None = None,
        *,
        embed: Any = None,
        view: Any = None,
        file: Any = None,
    ) -> FakeMessage:
        self._counter += 1
        self.messages.append({"content": content, "embed": embed, "view": view, "file": file})
        if embed is not None:
            title = getattr(embed, "title", None) or ""
            print(f"[embed] {title}")
        elif content:
            print(content)
        return FakeMessage(id=self._counter)


async def run_chat(model: str | None = None) -> None:
    from dotenv import load_dotenv

    from ollim_bot.storage import DATA_DIR, PROJECT_DIR

    load_dotenv(PROJECT_DIR / ".env")

    # Auth check — same logic as main.py:333
    if not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        from ollim_bot.auth import is_authenticated

        if not is_authenticated():
            print("not logged in to claude. run: ollim-bot auth login", file=sys.stderr)
            raise SystemExit(1)

    from ollim_bot.main import _ensure_sdk_layout

    _ensure_sdk_layout()

    # Fix import-time path binding in profile.py
    import ollim_bot.profile as profile_mod

    profile_mod.IDENTITY_FILE = DATA_DIR / "IDENTITY.md"
    profile_mod.USER_FILE = DATA_DIR / "USER.md"

    from ollim_bot.channel import init_channel

    channel = ChatChannel()
    init_channel(channel)

    from ollim_bot.agent import Agent
    from ollim_bot.streamer import StreamStatus

    agent = Agent()
    if model:
        agent.options = replace(agent.options, model=model)
    agent.options = replace(agent.options, permission_mode="bypassPermissions")

    display_model = model or agent.options.model or "default"
    print(f"ollim-bot chat \u00b7 model: {display_model}\n")

    try:
        while True:
            try:
                message = input("you> ")
            except EOFError:
                break
            if not message.strip():
                continue

            async for chunk in agent.stream_chat(message):
                if isinstance(chunk, StreamStatus):
                    if chunk.kind == "tool_start":
                        print(f"\033[2m[tool] {chunk.label}\033[0m")
                else:
                    print(chunk, end="", flush=True)
            print()
    except KeyboardInterrupt:
        pass

    print("\nchat ended.")


def run_chat_command(args: list[str]) -> None:
    model: str | None = None
    i = 0
    while i < len(args):
        if args[i] == "--model" and i + 1 < len(args):
            model = args[i + 1]
            i += 2
        elif args[i] in ("help", "--help", "-h"):
            print("usage: ollim-bot chat [--model <name>]")
            print("  Chat with the agent directly (no Discord)")
            return
        else:
            print(f"unknown argument: {args[i]}", file=sys.stderr)
            raise SystemExit(1)

    asyncio.run(run_chat(model=model))
