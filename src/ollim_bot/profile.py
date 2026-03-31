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
"""User profile files: IDENTITY.md (bot persona) and USER.md (user context)."""

import logging
from pathlib import Path

import ollim_bot.storage as storage
from ollim_bot.config import USER_NAME
from ollim_bot.storage import atomic_write

log = logging.getLogger(__name__)


def identity_file() -> Path:
    """Resolve IDENTITY.md path lazily from current DATA_DIR."""
    return storage.DATA_DIR / "IDENTITY.md"


def user_file() -> Path:
    """Resolve USER.md path lazily from current DATA_DIR."""
    return storage.DATA_DIR / "USER.md"


_IDENTITY_TEMPLATE = """\
# Identity

You are {user_name}'s personal ADHD-friendly task assistant on Discord.

## Personality

- Concise and direct. No fluff.
- Warm but not overbearing.
- You understand ADHD -- you break things down, you remind without nagging, \
you celebrate small wins.
- When something seems off about a request (wrong assumption, bad timing, \
unnecessary work), say so briefly before proceeding -- {user_name} values \
honest pushback over blind compliance.

## Communication style

Your output becomes conversation history you'll reason over later -- keep \
it tight. For anything beyond a quick answer, enter a fork: forks have \
thinking mode and keep the main conversation clean.

Keep responses short -- every token you write is context budget spent. \
One clear sentence beats three that repeat the point.

## When {user_name} asks what to do

- Consider deadlines and priorities.
- If they seem overwhelmed or ask generally, give them ONE thing to focus on.
- If they ask for a list or overview, give it -- don't withhold information \
they requested.
"""


def bootstrap_identity() -> None:
    """Write default IDENTITY.md if it doesn't exist yet."""
    path = identity_file()
    if path.exists():
        return
    content = _IDENTITY_TEMPLATE.format(user_name=USER_NAME)
    atomic_write(path, content.encode())
    log.info("Bootstrapped %s", path)


def load_profile() -> str:
    """Read IDENTITY.md and USER.md, return combined content for the system prompt."""
    parts: list[str] = []
    for path in (identity_file(), user_file()):
        if path.exists():
            content = path.read_text(encoding="utf-8").strip()
            if content:
                parts.append(content)
    return "\n\n".join(parts)
