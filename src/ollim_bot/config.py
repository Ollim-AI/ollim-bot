"""User-configurable names loaded from environment variables."""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

_REQUIRED = ("OLLIM_USER_NAME", "OLLIM_BOT_NAME")
_missing = [var for var in _REQUIRED if not os.environ.get(var)]
if _missing:
    print(f"Missing required env vars: {', '.join(_missing)}", file=sys.stderr)
    print("Set them in .env or your environment.", file=sys.stderr)
    raise SystemExit(1)

USER_NAME: str = os.environ["OLLIM_USER_NAME"]
BOT_NAME: str = os.environ["OLLIM_BOT_NAME"]
