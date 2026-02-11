"""CLI handler for `ollim-bot schedule` subcommand."""

import argparse
import sys

from ollim_bot.wakeups import Wakeup, append_wakeup, list_wakeups, remove_wakeup


def _fmt_schedule(w: Wakeup) -> str:
    if w.run_at:
        return f"at {w.run_at[:16]}"
    if w.cron:
        return f"cron '{w.cron}'"
    if w.interval_minutes:
        return f"every {w.interval_minutes}min"
    return "unknown"


def run_schedule_command(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="ollim-bot schedule")
    sub = parser.add_subparsers(dest="action")

    # -- add --
    add_p = sub.add_parser("add", help="Schedule a new reminder")
    add_p.add_argument("--message", "-m", required=True, help="Reminder message")
    add_p.add_argument("--delay", type=int, help="One-shot: fire in N minutes")
    add_p.add_argument("--cron", help='Recurring: 5-field cron (e.g. "0 9 * * 1-5")')
    add_p.add_argument("--every", type=int, help="Interval: fire every N minutes")

    # -- list --
    sub.add_parser("list", help="Show pending reminders")

    # -- cancel --
    cancel_p = sub.add_parser("cancel", help="Cancel a reminder by ID")
    cancel_p.add_argument("id", help="Reminder ID to cancel")

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
    if args.delay is None and args.cron is None and args.every is None:
        print("error: provide --delay, --cron, or --every")
        sys.exit(1)

    wakeup = Wakeup.new(
        message=args.message,
        delay_minutes=args.delay,
        cron=args.cron,
        interval_minutes=args.every,
    )
    append_wakeup(wakeup)
    print(f"scheduled {wakeup.id}: {_fmt_schedule(wakeup)} -- {wakeup.message}")


def _handle_list() -> None:
    wakeups = list_wakeups()
    if not wakeups:
        print("no pending reminders")
        return
    for w in wakeups:
        print(f"  {w.id}  {_fmt_schedule(w):24s}  {w.message}")


def _handle_cancel(wakeup_id: str) -> None:
    if remove_wakeup(wakeup_id):
        print(f"cancelled {wakeup_id}")
    else:
        print(f"reminder {wakeup_id} not found")
        sys.exit(1)
