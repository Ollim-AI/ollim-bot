"""CLI handler for `ollim-bot reminder` subcommand."""

import argparse
import sys

from ollim_bot.scheduling.reminders import (
    Reminder,
    append_reminder,
    list_reminders,
    remove_reminder,
)


def _summary(r: Reminder) -> str:
    return r.description or r.message


def _fmt_schedule(r: Reminder) -> str:
    sched = f"at {r.run_at[:16]}"
    if r.background:
        parts = ["bg"]
        if r.isolated:
            parts.append("isolated")
        tag = f"[{','.join(parts)}]"
        sched = f"{tag} {sched}"
    if r.model:
        sched += f"  (model: {r.model})"
    if not r.thinking:
        sched += "  (no-thinking)"
    if r.max_chain > 0:
        sched += f"  (chain {r.chain_depth}/{r.max_chain})"
    return sched


def run_reminder_command(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="ollim-bot reminder")
    sub = parser.add_subparsers(dest="action")

    add_p = sub.add_parser("add", help="Schedule a one-shot reminder")
    add_p.add_argument("--message", "-m", required=True, help="Reminder message")
    add_p.add_argument("--description", "-d", default="", help="Short summary for list")
    add_p.add_argument("--delay", type=int, required=True, help="Fire in N minutes")
    add_p.add_argument("--background", action="store_true", help="Silent mode")
    add_p.add_argument(
        "--max-chain", type=int, default=0, help="Max follow-up chain depth"
    )
    # Internal flags used by follow_up_chain MCP tool — not documented to the agent
    add_p.add_argument("--chain-depth", type=int, default=0)
    add_p.add_argument("--chain-parent", type=str, default=None)
    add_p.add_argument("--model", default=None, help="Model override (bg only)")
    add_p.add_argument(
        "--no-thinking",
        action="store_true",
        help="Disable extended thinking (bg only)",
    )
    add_p.add_argument(
        "--isolated", action="store_true", help="Fresh context (bg only)"
    )
    add_p.add_argument(
        "--update-main-session",
        default="on_ping",
        choices=["always", "on_ping", "freely", "blocked"],
        help="When to report to main session (bg only)",
    )
    add_p.add_argument(
        "--no-ping",
        action="store_true",
        help="Disable ping_user/discord_embed (bg only)",
    )
    add_p.add_argument(
        "--allowed-tools",
        nargs="+",
        default=None,
        help="Allowlist of SDK tool patterns (bg only)",
    )
    add_p.add_argument(
        "--disallowed-tools",
        nargs="+",
        default=None,
        help="Denylist of SDK tool patterns (bg only)",
    )

    sub.add_parser("list", help="Show pending reminders")

    cancel_p = sub.add_parser("cancel", help="Cancel a reminder by ID")
    cancel_p.add_argument("id", help="Reminder ID")

    args = parser.parse_args(argv)

    if args.action == "add":
        _handle_add(args)
    elif args.action == "list":
        _handle_list()
    elif args.action == "cancel":
        _handle_cancel(args.id)
    else:
        parser.print_help()
        sys.exit(1)


def _handle_add(args: argparse.Namespace) -> None:
    reminder = Reminder.new(
        message=args.message,
        delay_minutes=args.delay,
        description=args.description,
        background=args.background,
        max_chain=args.max_chain,
        chain_depth=args.chain_depth,
        chain_parent=args.chain_parent,
        model=args.model,
        thinking=not args.no_thinking,
        isolated=args.isolated,
        update_main_session=args.update_main_session,
        allow_ping=not args.no_ping,
        allowed_tools=args.allowed_tools,
        disallowed_tools=args.disallowed_tools,
    )
    append_reminder(reminder)
    print(f"scheduled {reminder.id}: {_fmt_schedule(reminder)} -- {_summary(reminder)}")


def _handle_list() -> None:
    reminders = list_reminders()
    if not reminders:
        print("no pending reminders")
        return
    for r in reminders:
        print(f"  {r.id}  {_fmt_schedule(r):24s}  {_summary(r)}")


def _handle_cancel(reminder_id: str) -> None:
    if remove_reminder(reminder_id):
        print(f"cancelled {reminder_id}")
    else:
        print(f"reminder {reminder_id} not found")
        sys.exit(1)
