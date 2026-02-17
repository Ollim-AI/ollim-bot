"""CLI handler for `ollim-bot reminder` subcommand."""

import argparse
import sys

from ollim_bot.scheduling.reminders import (
    Reminder,
    append_reminder,
    list_reminders,
    remove_reminder,
)


def _fmt_schedule(r: Reminder) -> str:
    sched = f"at {r.run_at[:16]}"
    if r.background:
        tag = "[bg,queue]" if not r.skip_if_busy else "[bg]"
        sched = f"{tag} {sched}"
    if r.max_chain > 0:
        sched += f"  (chain {r.chain_depth}/{r.max_chain})"
    return sched


def run_reminder_command(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="ollim-bot reminder")
    sub = parser.add_subparsers(dest="action")

    add_p = sub.add_parser("add", help="Schedule a one-shot reminder")
    add_p.add_argument("--message", "-m", required=True, help="Reminder message")
    add_p.add_argument("--delay", type=int, required=True, help="Fire in N minutes")
    add_p.add_argument("--background", action="store_true", help="Silent mode")
    add_p.add_argument("--no-skip", action="store_true", help="Always run (bg only)")
    add_p.add_argument(
        "--max-chain", type=int, default=0, help="Max follow-up chain depth"
    )
    # Internal flags used by follow_up_chain MCP tool — not documented to the agent
    add_p.add_argument("--chain-depth", type=int, default=0)
    add_p.add_argument("--chain-parent", type=str, default=None)

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
        background=args.background,
        skip_if_busy=not args.no_skip,
        max_chain=args.max_chain,
        chain_depth=args.chain_depth,
        chain_parent=args.chain_parent,
    )
    append_reminder(reminder)
    print(f"scheduled {reminder.id}: {_fmt_schedule(reminder)} -- {reminder.message}")


def _handle_list() -> None:
    reminders = list_reminders()
    if not reminders:
        print("no pending reminders")
        return
    for r in reminders:
        print(f"  {r.id}  {_fmt_schedule(r):40s}  {r.message[:60]}")


def _handle_cancel(reminder_id: str) -> None:
    if remove_reminder(reminder_id):
        print(f"cancelled {reminder_id}")
    else:
        print(f"reminder {reminder_id} not found")
        sys.exit(1)
