"""CLI command implementations (all cmd_* functions except serve/stop)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from agent_track.services import paths
from agent_track.services.frontmatter import parse_frontmatter
from agent_track.services.models import (
    BOARD_HEADER,
    all_agents,
    all_tickets,
    next_ticket_id,
    post_to_board,
    parse_board_entries,
    read_agent,
    read_ticket,
    write_agent,
    write_ticket,
)
from agent_track.services.utils import ConcurrentAccessError, file_lock, now_iso

_DATA_DIR = Path(__file__).parent.parent / "data"


def _load_conventions() -> str:
    return (_DATA_DIR / "CONVENTIONS.md").read_text(encoding="utf-8")


def cmd_init(_args: argparse.Namespace) -> None:
    for d in [
        paths.TRACK_DIR,
        paths.TICKETS_DIR,
        paths.AGENTS_DIR,
        paths.LOCKS_DIR,
        paths.ARCHIVE_DIR,
    ]:
        d.mkdir(parents=True, exist_ok=True)
    gi = paths.TRACK_DIR / ".gitignore"
    if not gi.exists():
        gi.write_text("locks/\n", encoding="utf-8")
    if not paths.BOARD_FILE.exists():
        paths.BOARD_FILE.write_text(BOARD_HEADER, encoding="utf-8")
    if not paths.CONVENTIONS_FILE.exists():
        paths.CONVENTIONS_FILE.write_text(_load_conventions(), encoding="utf-8")
    print("Initialized .track/ directory.")


def cmd_create(args: argparse.Namespace) -> None:
    with file_lock("_create.lock"):
        tid = next_ticket_id()
        meta = {
            "id": tid,
            "title": args.title,
            "status": "backlog",
            "priority": args.priority or "medium",
            "created": now_iso(),
            "created_by": args.by or "human",
            "claimed_by": None,
            "claimed_at": None,
            "labels": [lbl.strip() for lbl in args.labels.split(",")]
            if args.labels
            else [],
            "branch": None,
            "files": [],
            "depends_on": [d.strip() for d in args.depends_on.split(",")]
            if args.depends_on
            else [],
        }
        body_text = args.body or ""
        body = f"""## Description

{body_text}

## Acceptance Criteria

- [ ] (define criteria)

## Work Log
"""
        path = paths.TICKETS_DIR / f"{tid}.md"
        write_ticket(meta, body, path)
    post_to_board(meta["created_by"], tid, "created", f"Created: {args.title}")
    print(f"Created {tid}: {args.title}")


def cmd_list(args: argparse.Namespace) -> None:
    tickets = all_tickets()
    if args.status:
        tickets = [(m, b, p) for m, b, p in tickets if m.get("status") == args.status]
    elif not args.all:
        tickets = [(m, b, p) for m, b, p in tickets if m.get("status") != "done"]
    if args.agent:
        tickets = [
            (m, b, p) for m, b, p in tickets if m.get("claimed_by") == args.agent
        ]
    if args.label:
        tickets = [
            (m, b, p) for m, b, p in tickets if args.label in (m.get("labels") or [])
        ]
    if args.priority:
        tickets = [
            (m, b, p) for m, b, p in tickets if m.get("priority") == args.priority
        ]
    if not tickets:
        print("No tickets found.")
        return
    header = f"{'ID':<10} {'Status':<14} {'Priority':<10} {'Agent':<16} {'Title'}"
    print(header)
    print("-" * len(header))
    for meta, _body, _path in tickets:
        print(
            f"{meta.get('id', '?'):<10} "
            f"{meta.get('status', '?'):<14} "
            f"{meta.get('priority', '?'):<10} "
            f"{(meta.get('claimed_by') or '--'):<16} "
            f"{meta.get('title', '?')}"
        )


def cmd_show(args: argparse.Namespace) -> None:
    meta, body, path = read_ticket(args.ticket_id)
    print(path.read_text(encoding="utf-8"))


def cmd_claim(args: argparse.Namespace) -> None:
    tid = args.ticket_id
    agent = args.agent
    try:
        with file_lock(f"{tid}.lock", blocking=False):
            meta, body, path = read_ticket(tid)
            if meta.get("status") != "backlog" and not args.force:
                current = meta.get("claimed_by")
                if current:
                    print(
                        f"Error: {tid} already claimed by {current}. Use --force to override.",
                        file=sys.stderr,
                    )
                else:
                    print(
                        f"Error: {tid} status is '{meta.get('status')}', expected 'backlog'.",
                        file=sys.stderr,
                    )
                sys.exit(1)
            deps = meta.get("depends_on") or []
            if deps:
                unmet = []
                for dep in deps:
                    try:
                        dm, _, _ = read_ticket(dep)
                        if dm.get("status") != "done":
                            unmet.append(f"{dep} ({dm.get('status')})")
                    except SystemExit:
                        unmet.append(f"{dep} (not found)")
                if unmet:
                    print(f"Warning: Unmet dependencies: {', '.join(unmet)}")
            meta["status"] = "claimed"
            meta["claimed_by"] = agent
            meta["claimed_at"] = now_iso()
            write_ticket(meta, body, path)
            try:
                adata = read_agent(agent)
                adata["current_ticket"] = tid
                adata["last_heartbeat"] = now_iso()
                adata.setdefault("history", []).append(
                    {"ticket": tid, "action": "claimed", "timestamp": now_iso()}
                )
                write_agent(adata)
            except SystemExit:
                pass
    except ConcurrentAccessError:
        print(
            f"Error: {tid} is being claimed by another agent right now. Try again.",
            file=sys.stderr,
        )
        sys.exit(1)
    post_to_board(agent, tid, "claimed", f"Claiming {tid}: {meta.get('title')}")
    print(f"Claimed {tid} for {agent}.")


def cmd_update(args: argparse.Namespace) -> None:
    tid = args.ticket_id
    with file_lock(f"{tid}.lock"):
        meta, body, path = read_ticket(tid)
        if args.status:
            old_status = meta.get("status")
            new_status = args.status
            valid_transitions = {
                "backlog": ["claimed"],
                "claimed": ["in-progress", "backlog"],
                "in-progress": ["review", "backlog"],
                "review": ["done", "in-progress"],
                "done": [],
            }
            allowed = valid_transitions.get(old_status, [])
            if new_status not in allowed and not args.force:
                print(
                    f"Error: Cannot transition {old_status} -> {new_status}. "
                    f"Allowed: {', '.join(allowed) or 'none'}. Use --force to override.",
                    file=sys.stderr,
                )
                sys.exit(1)
            meta["status"] = new_status
            if new_status == "backlog":
                meta["claimed_by"] = None
                meta["claimed_at"] = None
            if new_status == "done" and args.agent:
                try:
                    adata = read_agent(args.agent)
                    if adata.get("current_ticket") == tid:
                        adata["current_ticket"] = None
                    adata.setdefault("history", []).append(
                        {
                            "ticket": tid,
                            "action": f"status:{new_status}",
                            "timestamp": now_iso(),
                        }
                    )
                    write_agent(adata)
                except SystemExit:
                    pass
            if args.agent:
                post_to_board(
                    args.agent,
                    tid,
                    f"status:{new_status}",
                    f"Updated {tid} to {new_status}",
                )
        if args.priority:
            meta["priority"] = args.priority
        if args.branch:
            meta["branch"] = args.branch
        if args.add_label:
            labels = meta.get("labels") or []
            if args.add_label not in labels:
                labels.append(args.add_label)
            meta["labels"] = labels
        if args.remove_label:
            labels = meta.get("labels") or []
            if args.remove_label in labels:
                labels.remove(args.remove_label)
            meta["labels"] = labels
        if args.title:
            meta["title"] = args.title
        write_ticket(meta, body, path)
    print(f"Updated {tid}.")


def cmd_log(args: argparse.Namespace) -> None:
    tid = args.ticket_id
    with file_lock(f"{tid}.lock"):
        meta, body, path = read_ticket(tid)
        entry = f"\n### [{now_iso()}] {args.agent}\n{args.message}\n"
        if "## Work Log" in body:
            body = body + entry
        else:
            body = body + "\n## Work Log\n" + entry
        write_ticket(meta, body, path)
    try:
        adata = read_agent(args.agent)
        adata["last_heartbeat"] = now_iso()
        write_agent(adata)
    except SystemExit:
        pass
    print(f"Logged to {tid}.")


def cmd_board(args: argparse.Namespace) -> None:
    if args.last:
        entries = parse_board_entries(limit=args.last)
        if not entries:
            print("Board is empty.")
            return
        for e in entries:
            ts = e["timestamp"]
            short_ts = ts[11:16] if len(ts) > 16 else ts
            print(f"[{short_ts}] {e['agent']} | {e['ticket']} | {e['tag']}")
            print(f"  {e['message']}")
            print()
        return
    if not args.message:
        print("Error: -m/--message is required.", file=sys.stderr)
        sys.exit(1)
    if not args.agent:
        print("Error: --agent is required.", file=sys.stderr)
        sys.exit(1)
    ticket = args.ticket or "system"
    tag = args.tag or "note"
    post_to_board(args.agent, ticket, tag, args.message)
    print("Posted to board.")


def cmd_register(args: argparse.Namespace) -> None:
    paths.AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    agent_id = args.agent
    if not agent_id:
        existing = {f.stem for f in paths.AGENTS_DIR.glob("*.json")}
        for name in paths.NATO:
            candidate = f"agent-{name}"
            if candidate not in existing:
                agent_id = candidate
                break
        if not agent_id:
            import secrets

            agent_id = f"agent-{secrets.token_hex(2)}"
    path = paths.AGENTS_DIR / f"{agent_id}.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("status") == "active":
            print(f"Warning: Agent '{agent_id}' is already registered and active.")
            print(f"Registered: {agent_id}")
            return
    caps = (
        [c.strip() for c in args.capabilities.split(",")] if args.capabilities else []
    )
    data = {
        "id": agent_id,
        "registered_at": now_iso(),
        "last_heartbeat": now_iso(),
        "status": "active",
        "current_ticket": None,
        "capabilities": caps,
        "session_id": args.session_id,
        "worktree": args.worktree,
        "files_modified": [],
        "history": [],
    }
    write_agent(data)
    post_to_board(
        agent_id,
        "system",
        "registered",
        f"Agent registered. Capabilities: {', '.join(caps) or 'general'}",
    )
    print(f"Registered: {agent_id}")


def cmd_deregister(args: argparse.Namespace) -> None:
    agent_id = args.agent
    adata = read_agent(agent_id)
    if args.release_tickets:
        for meta, body, path in all_tickets():
            if meta.get("claimed_by") == agent_id and meta.get("status") in (
                "claimed",
                "in-progress",
            ):
                with file_lock(f"{meta['id']}.lock"):
                    text = path.read_text(encoding="utf-8")
                    m2, b2 = parse_frontmatter(text)
                    m2["status"] = "backlog"
                    m2["claimed_by"] = None
                    m2["claimed_at"] = None
                    write_ticket(m2, b2, path)
                    post_to_board(
                        "system",
                        meta["id"],
                        "status:backlog",
                        f"Released from deregistered {agent_id}",
                    )
                    print(f"  Released {meta['id']} back to backlog.")
    adata["status"] = "deregistered"
    adata["current_ticket"] = None
    adata.setdefault("history", []).append(
        {"action": "deregistered", "timestamp": now_iso()}
    )
    write_agent(adata)
    post_to_board(agent_id, "system", "deregistered", "Agent deregistered.")
    print(f"Deregistered: {agent_id}")


def cmd_files(args: argparse.Namespace) -> None:
    if args.add:
        if not args.agent or not args.ticket:
            print("Error: --agent and --ticket required with --add.", file=sys.stderr)
            sys.exit(1)
        try:
            adata = read_agent(args.agent)
            adata.setdefault("files_modified", []).append(
                {
                    "path": args.add,
                    "ticket": args.ticket,
                    "timestamp": now_iso(),
                }
            )
            write_agent(adata)
        except SystemExit:
            print(f"Warning: Agent '{args.agent}' not registered.")
        with file_lock(f"{args.ticket}.lock"):
            meta, body, path = read_ticket(args.ticket)
            files = meta.get("files") or []
            if args.add not in files:
                files.append(args.add)
            meta["files"] = files
            write_ticket(meta, body, path)
        print(f"Tracked: {args.add} -> {args.agent} ({args.ticket})")
    elif args.check:
        found = False
        for adata in all_agents():
            if adata.get("status") not in ("active", "idle"):
                continue
            for fm in adata.get("files_modified", []):
                if fm.get("path") == args.check:
                    print(
                        f"  {adata['id']} ({fm.get('ticket', '?')}) -- {fm.get('timestamp', '?')}"
                    )
                    found = True
        if not found:
            print(f"No active agent is tracking '{args.check}'.")
    elif args.list:
        file_map: dict[str, list[tuple[str, str]]] = {}
        for adata in all_agents():
            if adata.get("status") not in ("active", "idle"):
                continue
            for fm in adata.get("files_modified", []):
                fpath = fm.get("path", "?")
                file_map.setdefault(fpath, []).append(
                    (adata["id"], fm.get("ticket", "?"))
                )
        if not file_map:
            print("No files tracked.")
            return
        for fpath in sorted(file_map.keys()):
            owners = file_map[fpath]
            if len(owners) > 1:
                print(f"  [CONFLICT] {fpath}")
            else:
                print(f"  {fpath}")
            for agent_id, ticket in owners:
                print(f"    -> {agent_id} ({ticket})")
    else:
        print("Error: Specify --add, --check, or --list.", file=sys.stderr)
        sys.exit(1)


def cmd_heartbeat(args: argparse.Namespace) -> None:
    adata = read_agent(args.agent)
    adata["last_heartbeat"] = now_iso()
    write_agent(adata)
    print(f"Heartbeat: {args.agent}")


def cmd_stale(args: argparse.Namespace) -> None:
    threshold = args.threshold or paths.HEARTBEAT_STALE_MINUTES
    now = datetime.now(timezone.utc)
    found = False
    for adata in all_agents():
        if adata.get("status") != "active":
            continue
        hb = adata.get("last_heartbeat")
        if not hb:
            continue
        try:
            hb_dt = datetime.fromisoformat(hb.replace("Z", "+00:00"))
            age_min = (now - hb_dt).total_seconds() / 60
        except ValueError:
            age_min = 999
        if age_min > threshold:
            found = True
            ticket = adata.get("current_ticket") or "--"
            print(
                f"  STALE: {adata['id']}  last heartbeat: {int(age_min)}m ago  ticket: {ticket}"
            )
            if args.reclaim:
                adata["status"] = "stale"
                old_ticket = adata.get("current_ticket")
                adata["current_ticket"] = None
                write_agent(adata)
                if old_ticket:
                    try:
                        meta, body, path = read_ticket(old_ticket)
                        if meta.get("claimed_by") == adata["id"]:
                            with file_lock(f"{old_ticket}.lock"):
                                meta2, body2 = parse_frontmatter(
                                    path.read_text(encoding="utf-8")
                                )
                                meta2["status"] = "backlog"
                                meta2["claimed_by"] = None
                                meta2["claimed_at"] = None
                                write_ticket(meta2, body2, path)
                            post_to_board(
                                "system",
                                old_ticket,
                                "status:backlog",
                                f"Reclaimed from stale {adata['id']}",
                            )
                            print(f"    -> Reclaimed {old_ticket} back to backlog.")
                    except SystemExit:
                        pass
    if not found:
        print("No stale agents found.")
