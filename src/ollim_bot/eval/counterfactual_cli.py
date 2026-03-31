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

Aligned with claude-history conventions (--cwd, --project, session prefixes,
slug resolution, same color helpers).

Usage:
    counterfactual <session> <rewind_uuid> [options]
    counterfactual 408bc4a1 418a8812 --append "Respond in one sentence."
    counterfactual prev 418a8812 --model haiku --max-turns 1
    counterfactual elegant-hopping-seal 418a8812 --disallow Bash --with-baseline
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import textwrap

from claude_history.render import bold, cyan, dim, green, yellow

from ollim_bot.eval.counterfactual import (
    CounterfactualResult,
    Intervention,
    ResponseSummary,
    run_counterfactual,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Formatting (uses claude-history render helpers)
# ---------------------------------------------------------------------------


def _format_tool_summary(tc: dict) -> str:
    """One-line summary of a tool call."""
    name = tc.get("name", "?")
    inp = tc.get("input", {})
    detail = ""
    if name in ("Read", "Edit", "Write"):
        detail = inp.get("file_path", "")
    elif name == "Bash":
        detail = inp.get("command", "")[:60]
    elif name in ("Grep", "Glob"):
        detail = inp.get("pattern", "")
    else:
        for v in inp.values():
            if isinstance(v, str) and len(v) < 80:
                detail = v
                break
    return f"  {dim(name)} {detail}"


def _format_response(label: str, color_fn, resp: ResponseSummary) -> str:
    lines: list[str] = []
    lines.append(bold(color_fn(label)))
    lines.append("")

    text = resp.text.strip() or "(no text)"
    for para in text.split("\n\n"):
        lines.append(textwrap.fill(para, width=88))
        lines.append("")

    if resp.tool_calls:
        lines.append(dim(f"Tools ({len(resp.tool_calls)}):"))
        for tc in resp.tool_calls:
            lines.append(_format_tool_summary(tc))
        lines.append("")
    else:
        lines.append(dim("Tools: none"))
        lines.append("")

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
        lines.append(dim(" | ".join(stats)))

    return "\n".join(lines)


def _format_result(result: CounterfactualResult) -> str:
    sections: list[str] = []

    sections.append(bold(f"Counterfactual: {cyan(result.session_id[:8])} @ {cyan(result.rewind_uuid[:8])}"))
    msg_preview = result.original_message[:120]
    if len(result.original_message) > 120:
        msg_preview += "..."
    sections.append(dim(f"Message: {msg_preview}"))
    sections.append("")

    sections.append(_format_response("ORIGINAL (from transcript)", cyan, result.original))
    sections.append("─" * 60)

    if result.baseline:
        sections.append(_format_response("BASELINE (same settings, fresh run)", green, result.baseline))
        sections.append("─" * 60)

    sections.append(_format_response("VARIANT (with intervention)", yellow, result.variant))

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Session resolution (reuses claude-history's resolve module)
# ---------------------------------------------------------------------------


def _resolve_session(identifier: str, args: argparse.Namespace) -> str:
    """Resolve a session identifier to a prefix, matching claude-history conventions.

    Supports: UUID prefixes, 'prev', 'prev-N', and slug names.
    """
    from claude_history.resolve import resolve_project_dir, resolve_session_ref

    project_dir = resolve_project_dir(args)
    prefix, _ = resolve_session_ref(identifier, project_dir)
    return prefix


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Run a counterfactual trajectory test on a production session.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            examples:
              %(prog)s 408bc4a1 418a8812 --append "Respond in one sentence."
              %(prog)s prev 418a8812 --model haiku --max-turns 1
              %(prog)s elegant-hopping-seal 418a8812 --disallow Bash
        """),
    )
    p.add_argument(
        "session",
        help="Session ID prefix, 'prev', 'prev-N', or slug name",
    )
    p.add_argument("rewind_uuid", help="UUID (or prefix) of the user message to rewind to")

    # claude-history-aligned flags
    p.add_argument("--cwd", help="Working directory path to find project for")
    p.add_argument("--project", help="Direct project directory path in ~/.claude/projects/")

    # Intervention flags
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

    # Resolve session using claude-history conventions
    session_prefix = _resolve_session(args.session, args)

    # Resolve cwd for the counterfactual run
    cwd = args.cwd or "~/.ollim-bot"

    intervention = Intervention(
        system_prompt_append=args.system_prompt_append,
        system_prompt_replace=args.system_prompt_replace,
        model=args.model,
        message_override=args.message_override,
        disallowed_tools=args.disallowed_tools,
        max_turns=args.max_turns,
        max_budget_usd=args.max_budget,
    )

    try:
        result = asyncio.run(
            run_counterfactual(
                session_id=session_prefix,
                rewind_uuid=args.rewind_uuid,
                intervention=intervention,
                cwd=cwd,
                skip_baseline=not args.with_baseline,
            )
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print()
    print(_format_result(result))


if __name__ == "__main__":
    main()
