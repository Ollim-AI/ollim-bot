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
"""Claude Code auth via the bundled Agent SDK CLI."""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

_CLI_NAME = "claude.exe" if platform.system() == "Windows" else "claude"
_URL_PATTERN = re.compile(r"https://\S+")


def _find_bundled_cli() -> str:
    import claude_agent_sdk

    bundled = Path(claude_agent_sdk.__file__).parent / "_bundled" / _CLI_NAME
    if not bundled.is_file():
        print(f"Bundled CLI not found at {bundled}")
        raise SystemExit(1)
    return str(bundled)


def is_authenticated() -> bool:
    cli = _find_bundled_cli()
    result = subprocess.run([cli, "auth", "status", "--json"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return False
    status = json.loads(result.stdout)
    return bool(status.get("loggedIn"))


def check_auth() -> bool:
    """Return True if ANTHROPIC_AUTH_TOKEN is set or the CLI reports logged-in."""
    if os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    return is_authenticated()


def start_login() -> tuple[str, subprocess.Popen[bytes]]:
    """Start login flow with browser suppressed.

    The process blocks until the user completes auth via the URL.
    Caller must wait on the process after presenting the URL to the user.
    """
    cli = _find_bundled_cli()
    proc = subprocess.Popen(
        [cli, "auth", "login"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env={**os.environ, "BROWSER": ""},
    )
    assert proc.stdout is not None
    # Read lines until we find the auth URL
    for raw_line in proc.stdout:
        line = raw_line.decode(errors="replace")
        match = _URL_PATTERN.search(line)
        if match:
            return match.group(0), proc

    # Process exited without printing a URL
    proc.wait()
    print("Could not extract login URL from `claude auth login`")
    raise SystemExit(1)


HELP = """\
ollim-bot auth -- Claude Code authentication

commands:
  ollim-bot auth login       Sign in to your Anthropic account
  ollim-bot auth status      Show authentication status
  ollim-bot auth logout      Log out from your Anthropic account
"""


def run_auth_command(args: list[str]) -> None:
    cli = _find_bundled_cli()
    if not args or args[0] in ("help", "--help", "-h"):
        print(HELP)
        return
    sub = args[0]
    if sub not in ("login", "status", "logout"):
        print(f"Unknown auth command: {sub}")
        print(HELP)
        raise SystemExit(1)
    result = subprocess.run([cli, "auth", *args], check=False)
    sys.exit(result.returncode)
