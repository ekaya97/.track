"""Task capture — handle TaskCreated and TaskCompleted events."""

from __future__ import annotations

import json

from agent_track.services import paths
from agent_track.services.utils import atomic_write, now_iso


def _read_agent(session_id: str) -> dict | None:
    """Read agent record, returning None if not found."""
    agent_path = paths.AGENTS_DIR / f"{session_id}.json"
    if not agent_path.exists():
        return None
    try:
        return json.loads(agent_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _find_task_file(task_id: str, ticket_id: str | None, session_id: str):
    """Find where a task file should be, checking ticket dir first."""
    if ticket_id:
        ticket_tasks = paths.TICKETS_DIR / ticket_id / "tasks"
        task_file = ticket_tasks / f"{task_id}.json"
        if task_file.exists():
            return task_file
    # Check session dir
    session_tasks = paths.SESSIONS_DIR / session_id / "tasks"
    task_file = session_tasks / f"{task_id}.json"
    if task_file.exists():
        return task_file
    return None


def handle_task_created(event: dict) -> None:
    """Handle a TaskCreated event — write task file."""
    session_id = event.get("session_id", "")
    task_id = event.get("task_id", "")
    if not task_id:
        return

    agent_data = _read_agent(session_id)
    agent_id = agent_data.get("id", "unknown") if agent_data else "unknown"
    ticket_id = agent_data.get("current_ticket") if agent_data else None

    task = {
        "task_id": task_id,
        "subject": event.get("task_subject", ""),
        "description": event.get("task_description", ""),
        "created_at": now_iso(),
        "status": "pending",
        "session_id": session_id,
        "agent": agent_id,
    }

    if ticket_id:
        tasks_dir = paths.TICKETS_DIR / ticket_id / "tasks"
    else:
        tasks_dir = paths.SESSIONS_DIR / session_id / "tasks"

    tasks_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(tasks_dir / f"{task_id}.json", json.dumps(task, indent=2) + "\n")


def handle_task_completed(event: dict) -> None:
    """Handle a TaskCompleted event — update task status."""
    session_id = event.get("session_id", "")
    task_id = event.get("task_id", "")
    if not task_id:
        return

    agent_data = _read_agent(session_id)
    ticket_id = agent_data.get("current_ticket") if agent_data else None

    task_file = _find_task_file(task_id, ticket_id, session_id)
    if not task_file:
        return

    try:
        task = json.loads(task_file.read_text(encoding="utf-8"))
        task["status"] = "completed"
        task["completed_at"] = now_iso()
        atomic_write(task_file, json.dumps(task, indent=2) + "\n")
    except (json.JSONDecodeError, OSError):
        pass
