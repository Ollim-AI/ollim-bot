"""User-configurable values loaded from environment variables."""

import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

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


def _detect_local_tz() -> str:
    """Detect the system's IANA timezone name. Falls back to UTC."""
    # Debian/Ubuntu: plain text file with IANA name
    etc_tz = Path("/etc/timezone")
    if etc_tz.exists():
        name = etc_tz.read_text().strip()
        if name:
            return name

    # Most Linux/WSL: /etc/localtime is a symlink into zoneinfo
    localtime = Path("/etc/localtime")
    if localtime.is_symlink():
        target = str(localtime.resolve())
        marker = "/zoneinfo/"
        idx = target.find(marker)
        if idx != -1:
            return target[idx + len(marker) :]

    return "UTC"


TZ: ZoneInfo = ZoneInfo(os.environ.get("OLLIM_TIMEZONE") or _detect_local_tz())
