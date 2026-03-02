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
    """Locate the Claude CLI bundled with claude-agent-sdk."""
    import claude_agent_sdk

    bundled = Path(claude_agent_sdk.__file__).parent / "_bundled" / _CLI_NAME
    if not bundled.is_file():
        print(f"Bundled CLI not found at {bundled}")
        raise SystemExit(1)
    return str(bundled)


def is_authenticated() -> bool:
    """Check if Claude CLI is authenticated."""
    cli = _find_bundled_cli()
    result = subprocess.run([cli, "auth", "status", "--json"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return False
    status = json.loads(result.stdout)
    return bool(status.get("loggedIn"))


def start_login() -> tuple[str, subprocess.Popen[bytes]]:
    """Start login flow with browser suppressed. Returns (auth_url, process).

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
