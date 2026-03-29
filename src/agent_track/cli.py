"""CLI entry point: argument parser and command dispatch."""

from __future__ import annotations

import argparse
import sys

from agent_track import __version__
from agent_track.services.paths import (
    DEFAULT_PORT,
    HEARTBEAT_STALE_MINUTES,
    PRIORITIES,
    STATUSES,
    resolve_paths,
)
from agent_track.services.commands import (
    cmd_board,
    cmd_claim,
    cmd_create,
    cmd_deregister,
    cmd_files,
    cmd_heartbeat,
    cmd_init,
    cmd_list,
    cmd_log,
    cmd_register,
    cmd_show,
    cmd_stale,
    cmd_update,
)
from agent_track.dashboard import cmd_serve, cmd_stop


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="track", description=".track — lightweight ticketing & agent coordination."
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="Initialize .track/ directory")

    p = sub.add_parser("create", help="Create a new ticket")
    p.add_argument("--title", "-t", required=True, help="Ticket title")
    p.add_argument("--priority", "-p", choices=PRIORITIES, default="medium")
    p.add_argument("--labels", "-l", default="", help="Comma-separated labels")
    p.add_argument("--depends-on", default="", help="Comma-separated ticket IDs")
    p.add_argument("--body", "-b", default="", help="Description body")
    p.add_argument("--by", default="human", help="Creator ID")

    p = sub.add_parser("list", help="List tickets")
    p.add_argument("--status", "-s", choices=STATUSES)
    p.add_argument("--agent", help="Filter by assigned agent")
    p.add_argument("--label", help="Filter by label")
    p.add_argument("--priority", choices=PRIORITIES)
    p.add_argument("--all", "-a", action="store_true", help="Include done tickets")

    p = sub.add_parser("show", help="Show ticket details")
    p.add_argument("ticket_id", help="Ticket ID (e.g. T-0001)")

    p = sub.add_parser("claim", help="Claim a ticket")
    p.add_argument("ticket_id", help="Ticket ID")
    p.add_argument("--agent", required=True, help="Agent ID")
    p.add_argument("--force", action="store_true", help="Override existing claim")

    p = sub.add_parser("update", help="Update ticket metadata")
    p.add_argument("ticket_id", help="Ticket ID")
    p.add_argument("--status", "-s", choices=STATUSES)
    p.add_argument("--agent", help="Agent performing update")
    p.add_argument("--priority", choices=PRIORITIES)
    p.add_argument("--branch", help="Git branch name")
    p.add_argument("--add-label", help="Add a label")
    p.add_argument("--remove-label", help="Remove a label")
    p.add_argument("--title", help="Update title")
    p.add_argument("--force", action="store_true", help="Force invalid transition")

    p = sub.add_parser("log", help="Append to ticket work log")
    p.add_argument("ticket_id", help="Ticket ID")
    p.add_argument("--agent", required=True, help="Agent ID")
    p.add_argument("--message", "-m", required=True, help="Log message")

    p = sub.add_parser("board", help="Post to or read the board")
    p.add_argument("--agent", help="Poster ID")
    p.add_argument("--ticket", help="Related ticket ID")
    p.add_argument("--tag", default="note", help="Event tag")
    p.add_argument("--message", "-m", help="Message text")
    p.add_argument("--last", type=int, help="Show last N board entries")

    p = sub.add_parser("register", help="Register an agent")
    p.add_argument("--agent", help="Agent ID (auto-generated if omitted)")
    p.add_argument("--capabilities", default="", help="Comma-separated capabilities")
    p.add_argument("--session-id", default=None, help="Claude Code session ID")
    p.add_argument("--worktree", default=None, help="Git worktree path")

    p = sub.add_parser("deregister", help="Deregister an agent")
    p.add_argument("--agent", required=True, help="Agent ID")
    p.add_argument(
        "--release-tickets",
        action="store_true",
        help="Return claimed tickets to backlog",
    )

    p = sub.add_parser("files", help="Track file ownership")
    p.add_argument("--add", help="File path to track")
    p.add_argument("--check", help="Check who owns a file")
    p.add_argument("--list", action="store_true", help="List all tracked files")
    p.add_argument("--agent", help="Agent ID (for --add)")
    p.add_argument("--ticket", help="Ticket ID (for --add)")

    p = sub.add_parser("heartbeat", help="Update agent heartbeat")
    p.add_argument("--agent", required=True, help="Agent ID")

    p = sub.add_parser("stale", help="Check for stale agents")
    p.add_argument("--reclaim", action="store_true", help="Reclaim stale tickets")
    p.add_argument(
        "--threshold",
        type=int,
        help=f"Staleness in minutes (default {HEARTBEAT_STALE_MINUTES})",
    )

    p = sub.add_parser("serve", help="Start the dashboard web server")
    p.add_argument(
        "--port",
        "-p",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port (default {DEFAULT_PORT})",
    )
    p.add_argument(
        "-d", "--background", action="store_true", help="Run in background (daemonize)"
    )

    sub.add_parser("stop", help="Stop the dashboard web server")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    # `init` always creates .track/ in CWD; other commands walk up to find it
    resolve_paths(use_cwd=(args.command == "init"))
    commands = {
        "init": cmd_init,
        "create": cmd_create,
        "list": cmd_list,
        "show": cmd_show,
        "claim": cmd_claim,
        "update": cmd_update,
        "log": cmd_log,
        "board": cmd_board,
        "register": cmd_register,
        "deregister": cmd_deregister,
        "files": cmd_files,
        "heartbeat": cmd_heartbeat,
        "stale": cmd_stale,
        "serve": cmd_serve,
        "stop": cmd_stop,
    }
    fn = commands.get(args.command)
    if fn:
        fn(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
