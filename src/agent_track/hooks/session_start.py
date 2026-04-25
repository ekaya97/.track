"""SessionStart hook handler — auto-register agent."""

from __future__ import annotations

import json

from agent_track.services import paths
from agent_track.services.models import post_to_board
from agent_track.services.utils import atomic_write, now_iso


def _pick_nato_alias() -> str:
    """Pick the first unused NATO phonetic name for an agent ID.

    Only considers currently *active* agents to avoid name exhaustion.
    Deregistered/stale agents' names are available for reuse.
    """
    active_ids: set[str] = set()
    if paths.AGENTS_DIR.exists():
        for f in paths.AGENTS_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("status") == "active":
                    active_ids.add(data.get("id", ""))
            except (json.JSONDecodeError, OSError):
                pass

    for name in paths.NATO:
        candidate = f"agent-{name}"
        if candidate not in active_ids:
            return candidate

    # All 26 NATO names taken — use hex suffix
    import secrets

    return f"agent-{secrets.token_hex(3)}"


def _get_stable_identity() -> str | None:
    """Try to load a stable agent identity for this project.

    Returns the stored agent ID if it exists and isn't currently
    held by another active session.
    """
    identity_file = paths.PROJECT_HOME / "identity"
    if not identity_file.exists():
        return None
    try:
        stored_id = identity_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not stored_id:
        return None

    # Check if another *active* session already uses this identity
    if paths.AGENTS_DIR.exists():
        for f in paths.AGENTS_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("id") == stored_id and data.get("status") == "active":
                    # Another active session owns this name — pick a new one
                    return None
            except (json.JSONDecodeError, OSError):
                pass
    return stored_id


def _save_stable_identity(agent_id: str) -> None:
    """Persist the agent identity for this project."""
    paths.PROJECT_HOME.mkdir(parents=True, exist_ok=True)
    identity_file = paths.PROJECT_HOME / "identity"
    atomic_write(identity_file, agent_id + "\n")


def _register_agent(event: dict) -> None:
    """Create a new agent record from a startup event."""
    session_id = event["session_id"]

    # Try to reuse a stable identity for this project
    agent_id = _get_stable_identity() or _pick_nato_alias()
    _save_stable_identity(agent_id)

    ts = now_iso()

    agent_data = {
        "id": agent_id,
        "session_id": session_id,
        "registered_at": ts,
        "last_heartbeat": ts,
        "status": "active",
        "model": event.get("model"),
        "cwd": event.get("cwd"),
        "current_ticket": None,
        "capabilities": [],
        "files_touched": [],
        "history": [{"action": "registered", "timestamp": ts}],
    }

    paths.AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    agent_path = paths.AGENTS_DIR / f"{session_id}.json"
    atomic_write(agent_path, json.dumps(agent_data, indent=2) + "\n")

    # Create session directory and save start event
    session_dir = paths.SESSIONS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(
        session_dir / "start.json", json.dumps(event, indent=2) + "\n"
    )

    post_to_board(
        agent_id,
        "system",
        "registered",
        f"Agent {agent_id} auto-registered (session {session_id})",
    )


def _update_heartbeat(session_id: str) -> None:
    """Update heartbeat on an existing agent record."""
    agent_path = paths.AGENTS_DIR / f"{session_id}.json"
    if not agent_path.exists():
        return
    try:
        data = json.loads(agent_path.read_text(encoding="utf-8"))
        data["last_heartbeat"] = now_iso()
        atomic_write(agent_path, json.dumps(data, indent=2) + "\n")
    except (json.JSONDecodeError, OSError):
        pass


def handle_session_start(event: dict) -> None:
    """Handle a SessionStart event. Auto-registers agent on startup."""
    session_id = event.get("session_id")
    if not session_id:
        return

    source = event.get("source", "")
    agent_path = paths.AGENTS_DIR / f"{session_id}.json"

    if source == "startup" and not agent_path.exists():
        _register_agent(event)
    else:
        # resume, clear, compact — just update heartbeat
        _update_heartbeat(session_id)
