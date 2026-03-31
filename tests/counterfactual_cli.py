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
"""CLI for counterfactual trajectory tests.

Usage:
    uv run python tests/counterfactual_cli.py SESSION REWIND_UUID [options]

Examples:
    uv run python tests/counterfactual_cli.py 408bc4a1 418a8812 --append "Respond in one sentence."
    uv run python tests/counterfactual_cli.py 408bc4a1 418a8812 --model haiku --max-turns 1
    uv run python tests/counterfactual_cli.py 408bc4a1 418a8812 --disallow Bash --with-baseline
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import textwrap

from tests.counterfactual import (
    CounterfactualResult,
    Intervention,
    ResponseSummary,
    run_counterfactual,
)

_BOLD = "\033[1m"
_DIM = "\033[2m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RESET = "\033[0m"


def _format_response(label: str, color: str, resp: ResponseSummary) -> str:
    lines: list[str] = []
    lines.append(f"{_BOLD}{color}{label}{_RESET}")
    lines.append("")

    # Text (wrapped)
    text = resp.text.strip() or "(no text)"
    for para in text.split("\n\n"):
        lines.append(textwrap.fill(para, width=88))
        lines.append("")

    # Tool calls
    if resp.tool_calls:
        lines.append(f"{_DIM}Tools ({len(resp.tool_calls)}):{_RESET}")
        for tc in resp.tool_calls:
            name = tc.get("name", "?")
            inp = tc.get("input", {})
            # Show a short summary of each tool call
            summary = ""
            if name == "Read":
                summary = inp.get("file_path", "")
            elif name == "Bash":
                summary = inp.get("command", "")[:60]
            elif name == "Edit":
                summary = inp.get("file_path", "")
            elif name in ("Grep", "Glob"):
                summary = inp.get("pattern", "")
            else:
                # Generic: show first string value
                for v in inp.values():
                    if isinstance(v, str) and len(v) < 80:
                        summary = v
                        break
            lines.append(f"  {_DIM}{name}{_RESET} {summary}")
        lines.append("")
    else:
        lines.append(f"{_DIM}Tools: none{_RESET}")
        lines.append("")

    # Stats
    stats: list[str] = []
    if resp.num_turns is not None:
        stats.append(f"turns={resp.num_turns}")
    if resp.total_cost_usd is not None:
        stats.append(f"cost=${resp.total_cost_usd:.4f}")
    if resp.input_tokens is not None:
        stats.append(f"in={resp.input_tokens:,}")
    if resp.output_tokens is not None:
        stats.append(f"out={resp.output_tokens:,}")
    if stats:
        lines.append(f"{_DIM}{' | '.join(stats)}{_RESET}")

    return "\n".join(lines)


def _format_result(result: CounterfactualResult) -> str:
    sections: list[str] = []

    # Header
    sections.append(f"{_BOLD}Counterfactual: {result.session_id[:8]} @ {result.rewind_uuid[:8]}{_RESET}")
    sections.append(
        f"{_DIM}Message: {result.original_message[:120]}{'...' if len(result.original_message) > 120 else ''}{_RESET}"
    )
    sections.append("")

    # Original
    sections.append(_format_response("ORIGINAL (from transcript)", _CYAN, result.original))
    sections.append("─" * 60)

    # Baseline
    if result.baseline:
        sections.append(_format_response("BASELINE (same settings, fresh run)", _GREEN, result.baseline))
        sections.append("─" * 60)

    # Variant
    sections.append(_format_response("VARIANT (with intervention)", _YELLOW, result.variant))

    return "\n".join(sections)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Run a counterfactual trajectory test on a production session.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("session", help="Session ID or prefix")
    p.add_argument("rewind_uuid", help="UUID of the user message to rewind to")
    p.add_argument("--cwd", default="~/.ollim-bot", help="Working directory (default: ~/.ollim-bot)")
    p.add_argument("--append", dest="system_prompt_append", help="Append to system prompt")
    p.add_argument("--replace-prompt", dest="system_prompt_replace", help="Replace system prompt entirely")
    p.add_argument("--model", help="Model override (e.g. haiku, sonnet, opus)")
    p.add_argument("--message", dest="message_override", help="Send a different message than the original")
    p.add_argument("--disallow", dest="disallowed_tools", action="append", help="Disallow a tool (repeatable)")
    p.add_argument("--max-turns", type=int, default=5, help="Max turns per run (default: 5)")
    p.add_argument("--max-budget", type=float, default=0.50, help="Max budget per run in USD (default: 0.50)")
    p.add_argument("--with-baseline", action="store_true", help="Also run a baseline (doubles cost)")
    p.add_argument("-v", "--verbose", action="store_true", help="Show debug logging")
    return p


def main() -> None:
    args = _build_parser().parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    intervention = Intervention(
        system_prompt_append=args.system_prompt_append,
        system_prompt_replace=args.system_prompt_replace,
        model=args.model,
        message_override=args.message_override,
        disallowed_tools=args.disallowed_tools,
        max_turns=args.max_turns,
        max_budget_usd=args.max_budget,
    )

    result = asyncio.run(
        run_counterfactual(
            session_id=args.session,
            rewind_uuid=args.rewind_uuid,
            intervention=intervention,
            cwd=args.cwd,
            skip_baseline=not args.with_baseline,
        )
    )

    print()
    print(_format_result(result))


if __name__ == "__main__":
    main()
