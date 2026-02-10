"""Claude Agent SDK wrapper -- the brain of the bot."""

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
)

SYSTEM_PROMPT = """You are Julius's personal ADHD-friendly task assistant on Discord.

Your personality:
- Concise and direct. No fluff.
- Warm but not overbearing.
- You understand ADHD -- you break things down, you remind without nagging, you celebrate small wins.

When Julius tells you about a task:
- Extract the task title, due date (if any), and priority
- Confirm what you understood

When Julius asks what he should do:
- Consider deadlines and priorities
- Give him ONE thing to focus on (not a wall of options)

You can schedule reminders using the schedule-wakeup skill.
Proactively schedule follow-ups when tasks have deadlines or when Julius might need a nudge.

Messages starting with [wakeup:ID] are scheduled wakeups firing.
When you see one, respond as if you're proactively reaching out -- use conversation context
to make it personal and relevant, not generic.

Keep responses short. Discord isn't the place for essays."""


class Agent:
    """Wraps the Claude Agent SDK with persistent per-user sessions.

    Each user gets a ClaudeSDKClient that maintains conversation context
    indefinitely. Auto-compaction is handled by Claude Code CLI when
    the context window fills up.
    """

    def __init__(self):
        self.options = ClaudeAgentOptions(
            system_prompt=SYSTEM_PROMPT,
            allowed_tools=[
                "WebSearch",
                "WebFetch",
                "Skill(claude-history)",
                "Bash(claude-history:*)",
                "Skill(schedule-wakeup)",
                "Bash(ollim-bot schedule:*)",
                "Read",
            ],
            permission_mode="default",
            setting_sources=["user"],
        )
        self._clients: dict[str, ClaudeSDKClient] = {}

    async def _get_client(self, user_id: str) -> ClaudeSDKClient:
        if user_id not in self._clients:
            client = ClaudeSDKClient(self.options)
            await client.connect()
            self._clients[user_id] = client
        return self._clients[user_id]

    async def chat(self, message: str, user_id: str) -> str:
        client = await self._get_client(user_id)
        await client.query(message)

        parts: list[str] = []
        result_text: str | None = None
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        parts.append(block.text)
            elif isinstance(msg, ResultMessage) and msg.result:
                result_text = msg.result

        # Use ResultMessage.result only as fallback when no text blocks found
        if not parts and result_text:
            parts.append(result_text)

        return "\n".join(parts) or "hmm, I didn't have a response for that."
