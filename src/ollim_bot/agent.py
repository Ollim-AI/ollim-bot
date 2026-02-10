"""Claude Agent SDK wrapper -- the brain of the bot."""

import os

from anthropic import Anthropic

SYSTEM_PROMPT = """You are Julius's personal ADHD-friendly task assistant on Discord.

Your personality:
- Concise and direct. No fluff.
- Warm but not overbearing.
- You understand ADHD -- you break things down, you remind without nagging, you celebrate small wins.

When Julius tells you about a task:
- Extract the task title, due date (if any), and priority
- Confirm what you understood
- Add it to Google Tasks

When Julius asks what he should do:
- Look at his task list
- Consider deadlines and priorities
- Give him ONE thing to focus on (not a wall of options)

Keep responses short. Discord isn't the place for essays."""


class Agent:
    """Thin wrapper around Anthropic API. Will migrate to Claude Agent SDK with tools."""

    def __init__(self):
        self.client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        # Per-user conversation history (in-memory for now)
        self.conversations: dict[str, list[dict]] = {}

    async def chat(self, message: str, user_id: str) -> str:
        history = self.conversations.setdefault(user_id, [])
        history.append({"role": "user", "content": message})

        # Keep last 20 messages to avoid token bloat
        if len(history) > 20:
            history[:] = history[-20:]

        response = self.client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=history,
        )

        assistant_text = response.content[0].text
        history.append({"role": "assistant", "content": assistant_text})

        return assistant_text
