"""Entry point for ollim-bot."""

import asyncio
import os

from dotenv import load_dotenv

from ollim_bot.bot import create_bot


def main():
    load_dotenv()

    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        print("Set DISCORD_TOKEN in .env")
        raise SystemExit(1)

    bot = create_bot()
    asyncio.run(bot.start(token))


if __name__ == "__main__":
    main()
