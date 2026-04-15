"""PostToolUse hook handler — file activity capture, heartbeat, locks."""

from __future__ import annotations

import json
import re

from agent_track.services import paths
from agent_track.services.utils import atomic_write, now_iso

# Tools that modify files (update soft lock table)
_WRITE_TOOLS = {"Write", "Edit"}

# Patterns that indicate a test run
_TEST_PATTERNS = re.compile(
    r"\b(pytest|py\.test|unittest|nose2|jest|vitest|mocha|"
    r"cargo\s+test|go\s+test|npm\s+test|yarn\s+test|pnpm\s+test|"
    r"npx\s+jest|npx\s+vitest)\b"
)


def _get_last_todos(session_id: str) -> list[dict]:
    """Read the most recent todo list from the activity log."""
    activity_file = paths.SESSIONS_DIR / session_id / "activity.jsonl"
    if not activity_file.exists():
        return []
    # Read backwards to find the last TodoWrite entry
    try:
        lines = activity_file.read_text(encoding="utf-8").strip().split("\n")
        for line in reversed(lines):
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get("tool") == "TodoWrite" and "todos" in entry:
                return entry["todos"]
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _diff_todos(session_id: str, new_todos: list[dict]) -> list[dict]:
    """Compute changes between previous and current todo lists."""
    old_todos = _get_last_todos(session_id)
    old_by_content = {t.get("content", ""): t for t in old_todos}
    new_by_content = {t.get("content", ""): t for t in new_todos}

    changes = []
    # New or status-changed items
    for content, todo in new_by_content.items():
        old = old_by_content.get(content)
        if old is None:
            changes.append({"action": "added", "content": content, "status": todo.get("status")})
        elif old.get("status") != todo.get("status"):
            changes.append({
                "action": "status_changed",
                "content": content,
                "from": old.get("status"),
                "to": todo.get("status"),
            })
    # Removed items
    for content in old_by_content:
        if content not in new_by_content:
            changes.append({"action": "removed", "content": content})

    return changes


def _read_agent(session_id: str) -> dict | None:
    """Read agent record for a session, returning None if not found."""
    agent_path = paths.AGENTS_DIR / f"{session_id}.json"
    if not agent_path.exists():
        return None
    try:
        return json.loads(agent_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _update_agent(session_id: str, agent_data: dict) -> None:
    """Write updated agent record."""
    agent_path = paths.AGENTS_DIR / f"{session_id}.json"
    atomic_write(agent_path, json.dumps(agent_data, indent=2) + "\n")


def _extract_file_path(event: dict) -> str | None:
    """Extract the file path from a tool event, if applicable."""
    tool_input = event.get("tool_input", {})
    return tool_input.get("file_path")


def _is_test_run(event: dict) -> bool:
    """Check if a Bash command looks like a test run."""
    if event.get("tool_name") != "Bash":
        return False
    command = event.get("tool_input", {}).get("command", "")
    return bool(_TEST_PATTERNS.search(command))


def _build_activity_entry(event: dict) -> dict:
    """Build a single activity log entry from a hook event."""
    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input", {})
    is_failure = event.get("hook_event_name") == "PostToolUseFailure"

    entry: dict = {
        "ts": now_iso(),
        "tool": tool_name,
        "tool_use_id": event.get("tool_use_id"),
    }

    # File path for file-related tools
    file_path = _extract_file_path(event)
    if file_path:
        entry["file"] = file_path

    # Bash command
    if tool_name == "Bash":
        entry["command"] = tool_input.get("command", "")
        entry["is_test_run"] = _is_test_run(event)

    # TodoWrite — capture todos and diff against previous state
    if tool_name == "TodoWrite":
        todos = tool_input.get("todos", [])
        entry["todos"] = todos
        entry["todo_changes"] = _diff_todos(event.get("session_id", ""), todos)

    # Failure info
    if is_failure:
        entry["is_failure"] = True
        entry["error"] = event.get("error", "")
        entry["is_interrupt"] = event.get("is_interrupt", False)

    return entry


def _append_activity(session_id: str, entry: dict) -> None:
    """Append an activity entry to the session's activity.jsonl."""
    session_dir = paths.SESSIONS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    activity_file = session_dir / "activity.jsonl"
    with open(activity_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _log_conflict(file_path: str, agents: list[str]) -> None:
    """Append a conflict entry to conflicts.jsonl."""
    paths.SECURITY_DIR.mkdir(parents=True, exist_ok=True)
    conflict_file = paths.SECURITY_DIR / "conflicts.jsonl"
    entry = {
        "ts": now_iso(),
        "file": file_path,
        "agents": agents,
    }
    with open(conflict_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _update_soft_locks(
    file_path: str, agent_id: str, session_id: str, ticket: str | None
) -> None:
    """Update the soft lock table for a file write/edit. Detect conflicts."""
    locks: dict = {}
    if paths.LOCKS_FILE.exists():
        try:
            locks = json.loads(paths.LOCKS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    # Check for conflict: another agent touched this file
    existing = locks.get(file_path)
    if existing and existing.get("agent") != agent_id:
        _log_conflict(file_path, [existing["agent"], agent_id])

    locks[file_path] = {
        "agent": agent_id,
        "session_id": session_id,
        "timestamp": now_iso(),
        "ticket": ticket,
    }

    atomic_write(paths.LOCKS_FILE, json.dumps(locks, indent=2) + "\n")


def handle_post_tool_use(event: dict) -> None:
    """Handle a PostToolUse, PostToolUseFailure, TaskCreated, or TaskCompleted event."""
    session_id = event.get("session_id")
    if not session_id:
        return

    # Route task events to dedicated handler
    event_name = event.get("hook_event_name", "")
    if event_name == "TaskCreated":
        from agent_track.hooks.tasks import handle_task_created
        handle_task_created(event)
        return
    if event_name == "TaskCompleted":
        from agent_track.hooks.tasks import handle_task_completed
        handle_task_completed(event)
        return

    agent_data = _read_agent(session_id)

    # Build and append activity entry
    entry = _build_activity_entry(event)
    if agent_data and agent_data.get("current_ticket"):
        entry["ticket"] = agent_data["current_ticket"]
    _append_activity(session_id, entry)

    if not agent_data:
        return

    # Update heartbeat
    agent_data["last_heartbeat"] = now_iso()

    # Track file touches for write tools
    tool_name = event.get("tool_name", "")
    file_path = _extract_file_path(event)

    if tool_name in _WRITE_TOOLS and file_path:
        agent_data.setdefault("files_touched", []).append({
            "path": file_path,
            "ticket": agent_data.get("current_ticket"),
            "timestamp": now_iso(),
        })

        # Update soft lock table
        _update_soft_locks(
            file_path,
            agent_data["id"],
            session_id,
            agent_data.get("current_ticket"),
        )

    _update_agent(session_id, agent_data)
