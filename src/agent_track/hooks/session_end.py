"""SessionEnd hook handler — auto-deregister, session summary."""

from __future__ import annotations

import json
from collections import Counter

from agent_track.services import paths
from agent_track.services.frontmatter import parse_frontmatter
from agent_track.services.models import post_to_board, write_ticket
from agent_track.services.utils import atomic_write, file_lock, now_iso


def _read_activity(session_id: str) -> list[dict]:
    """Read all activity entries for a session."""
    activity_file = paths.SESSIONS_DIR / session_id / "activity.jsonl"
    if not activity_file.exists():
        return []
    entries = []
    for line in activity_file.read_text(encoding="utf-8").strip().split("\n"):
        if line.strip():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return entries


def _build_summary(
    session_id: str, agent_data: dict, activity: list[dict], source: str
) -> dict:
    """Build a session summary from activity data."""
    # Count tools
    tools_used: Counter[str] = Counter()
    files_modified: set[str] = set()
    files_read: set[str] = set()
    test_runs = 0
    test_failures = 0
    errors = 0
    commands_run = 0

    for entry in activity:
        tool = entry.get("tool", "")
        tools_used[tool] += 1

        file_path = entry.get("file")
        if file_path:
            if tool in ("Write", "Edit"):
                files_modified.add(file_path)
            elif tool == "Read":
                files_read.add(file_path)

        if tool == "Bash":
            commands_run += 1

        if entry.get("is_test_run"):
            test_runs += 1
            if entry.get("is_failure"):
                test_failures += 1

        if entry.get("is_failure"):
            errors += 1

    return {
        "session_id": session_id,
        "agent": agent_data.get("id", "unknown"),
        "started_at": agent_data.get("registered_at"),
        "ended_at": now_iso(),
        "source": source,
        "files_modified": sorted(files_modified),
        "files_read": sorted(files_read),
        "commands_run": commands_run,
        "test_runs": test_runs,
        "test_failures": test_failures,
        "tools_used": dict(tools_used),
        "ticket": agent_data.get("current_ticket"),
        "errors": errors,
    }


def handle_session_end(event: dict) -> None:
    """Handle a SessionEnd event. Deregister agent, write summary."""
    session_id = event.get("session_id")
    if not session_id:
        return

    agent_path = paths.AGENTS_DIR / f"{session_id}.json"
    if not agent_path.exists():
        return

    try:
        agent_data = json.loads(agent_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return

    # Read activity and build summary
    activity = _read_activity(session_id)
    source = event.get("source", "unknown")
    summary = _build_summary(session_id, agent_data, activity, source)

    # Write summary
    session_dir = paths.SESSIONS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(
        session_dir / "summary.json", json.dumps(summary, indent=2) + "\n"
    )

    # Release tickets still in "claimed" status (agent never started work).
    # Keep "in-progress" tickets — stale reclaim handles those.
    ticket_id = agent_data.get("current_ticket")
    if ticket_id:
        try:
            from agent_track.services.models import _resolve_ticket_path

            ticket_path = _resolve_ticket_path(ticket_id)
            if ticket_path and ticket_path.exists():
                text = ticket_path.read_text(encoding="utf-8")
                meta, body = parse_frontmatter(text)
                if meta.get("status") == "claimed" and meta.get("claimed_by") == agent_data.get("id"):
                    with file_lock(f"{ticket_id}.lock"):
                        # Re-read under lock
                        text = ticket_path.read_text(encoding="utf-8")
                        meta, body = parse_frontmatter(text)
                        if meta.get("status") == "claimed":
                            meta["status"] = "backlog"
                            meta["claimed_by"] = None
                            meta["claimed_at"] = None
                            write_ticket(meta, body, ticket_path)
                            post_to_board(
                                agent_data.get("id", "unknown"),
                                ticket_id,
                                "status:backlog",
                                f"Released {ticket_id} (session ended, work not started)",
                            )
                    agent_data["current_ticket"] = None
        except Exception:
            pass

    # Deregister agent
    agent_data["status"] = "deregistered"
    agent_data["last_heartbeat"] = now_iso()
    agent_data.setdefault("history", []).append({
        "action": "deregistered",
        "timestamp": now_iso(),
    })
    atomic_write(agent_path, json.dumps(agent_data, indent=2) + "\n")

    # Post to board
    files_count = len(summary["files_modified"])
    post_to_board(
        agent_data.get("id", "unknown"),
        agent_data.get("current_ticket") or "system",
        "deregistered",
        f"Agent {agent_data.get('id')} session ended "
        f"({files_count} files modified, {summary['test_runs']} test runs)",
    )
