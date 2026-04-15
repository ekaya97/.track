"""Drift detection and context injection for pre_tool_use hooks."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from agent_track.services import paths
from agent_track.services.utils import now_iso

# ── Signal names ─────────────────────────────────────────────────────────────

SIGNAL_WRONG_FILE = "wrong_file"
SIGNAL_OFF_TICKET = "off_ticket"
SIGNAL_OUT_OF_SCOPE = "out_of_scope"
SIGNAL_SKIPPING_TESTS = "skipping_tests"
SIGNAL_TASK_STALL = "task_stall"

# Signals enabled per aggressiveness level
_GENTLE_SIGNALS = {SIGNAL_WRONG_FILE, SIGNAL_SKIPPING_TESTS}
_STRICT_SIGNALS = {SIGNAL_WRONG_FILE, SIGNAL_OFF_TICKET, SIGNAL_OUT_OF_SCOPE, SIGNAL_SKIPPING_TESTS, SIGNAL_TASK_STALL}

# Minimum source file edits before skipping-tests fires
_MIN_EDITS_BEFORE_TEST_REMINDER = 8


@dataclass
class DriftConfig:
    """Configuration for drift detection."""
    aggressiveness: str = "gentle"  # off, gentle, strict
    min_interval_tool_calls: int = 10

    def enabled_signals(self) -> set[str]:
        if self.aggressiveness == "off":
            return set()
        if self.aggressiveness == "gentle":
            return _GENTLE_SIGNALS
        return _STRICT_SIGNALS


# ── Helpers ──────────────────────────────────────────────────────────────────


def _read_agent_by_session(session_id: str) -> dict | None:
    agent_path = paths.AGENTS_DIR / f"{session_id}.json"
    if not agent_path.exists():
        return None
    try:
        return json.loads(agent_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _read_ticket(ticket_id: str) -> dict | None:
    """Read ticket metadata. Returns None if not found."""
    from agent_track.services.frontmatter import parse_frontmatter
    for d in [paths.TICKETS_DIR, paths.ARCHIVE_DIR]:
        if not d.exists():
            continue
        # Directory format
        ticket_file = d / ticket_id / "ticket.md"
        if ticket_file.exists():
            meta, _ = parse_frontmatter(ticket_file.read_text(encoding="utf-8"))
            return meta
        # Flat format
        flat = d / f"{ticket_id}.md"
        if flat.exists():
            meta, _ = parse_frontmatter(flat.read_text(encoding="utf-8"))
            return meta
    return None


def _read_activity(session_id: str) -> list[dict]:
    activity_file = paths.SESSIONS_DIR / session_id / "activity.jsonl"
    if not activity_file.exists():
        return []
    entries = []
    try:
        for line in activity_file.read_text(encoding="utf-8").strip().split("\n"):
            if line.strip():
                entries.append(json.loads(line))
    except (json.JSONDecodeError, OSError):
        pass
    return entries


def _read_locks() -> dict:
    if not paths.LOCKS_FILE.exists():
        return {}
    try:
        return json.loads(paths.LOCKS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _read_drift_state(session_id: str) -> dict:
    session_dir = paths.SESSIONS_DIR / session_id
    state_file = session_dir / "drift-state.json"
    if not state_file.exists():
        return {"last_injection_at_count": 0}
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"last_injection_at_count": 0}


def _write_drift_state(session_id: str, state: dict) -> None:
    session_dir = paths.SESSIONS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "drift-state.json").write_text(json.dumps(state))


def _log_injection(session_id: str, signal: str, message: str, file_path: str | None = None) -> None:
    session_dir = paths.SESSIONS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    log_file = session_dir / "injections.jsonl"
    entry = {"ts": now_iso(), "signal": signal, "message": message}
    if file_path:
        entry["file"] = file_path
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# ── Signal detectors ────────────────────────────────────────────────────────


def _check_wrong_file(
    agent_id: str, file_path: str | None, locks: dict
) -> dict | None:
    """Check if the file being edited is locked by another agent."""
    if not file_path:
        return None
    lock = locks.get(file_path)
    if not lock or lock.get("agent") == agent_id:
        return None
    other = lock["agent"]
    ticket = lock.get("ticket", "unknown")
    return {
        "signal": SIGNAL_WRONG_FILE,
        "message": (
            f"Note: `{file_path}` is currently being worked on by "
            f"`{other}` for `{ticket}`. Consider coordinating via `track board`."
        ),
        "decision": "allow",
    }


def _check_off_ticket(
    ticket_meta: dict | None, activity: list[dict], min_calls: int
) -> dict | None:
    """Check if agent hasn't touched ticket files in the last N tool calls."""
    if not ticket_meta:
        return None
    ticket_files = ticket_meta.get("files") or []
    if not ticket_files:
        return None

    if len(activity) < min_calls:
        return None

    # Check last min_calls entries for any ticket file touch
    recent = activity[-min_calls:]
    for entry in recent:
        entry_file = entry.get("file", "")
        for tf in ticket_files:
            if entry_file.endswith(tf) or tf in entry_file:
                return None

    ticket_id = ticket_meta.get("id", "?")
    title = ticket_meta.get("title", "")
    files_str = ", ".join(ticket_files[:5])
    return {
        "signal": SIGNAL_OFF_TICKET,
        "message": (
            f"Reminder: You're working on `{ticket_id}`: {title}. "
            f"Files: {files_str}."
        ),
        "decision": "allow",
    }


def _check_out_of_scope(
    ticket_meta: dict | None, file_path: str | None
) -> dict | None:
    """Check if the file being created/edited is outside ticket's directory scope."""
    if not ticket_meta or not file_path:
        return None
    ticket_files = ticket_meta.get("files") or []
    if not ticket_files:
        return None

    # Derive directory scopes from ticket files
    scopes = set()
    for tf in ticket_files:
        parts = tf.split("/")
        if len(parts) > 1:
            scopes.add(parts[0])  # top-level dir like "src", "tests"

    if not scopes:
        return None

    # Check if file_path starts with any scope
    for scope in scopes:
        if f"/{scope}/" in file_path or file_path.endswith(f"/{scope}"):
            return None
        # Handle relative-ish paths
        parts = file_path.split("/")
        if scope in parts:
            return None

    ticket_id = ticket_meta.get("id", "?")
    return {
        "signal": SIGNAL_OUT_OF_SCOPE,
        "message": (
            f"Note: `{file_path}` is outside the scope of `{ticket_id}`. "
            f"If this is intentional, carry on."
        ),
        "decision": "allow",
    }


def _check_skipping_tests(activity: list[dict], min_edits: int) -> dict | None:
    """Check if agent modified source files without running tests."""
    if not activity:
        return None

    # Count edits since last test run
    edits_since_test = 0
    for entry in reversed(activity):
        if entry.get("is_test_run"):
            break
        if entry.get("tool") in ("Write", "Edit") and entry.get("file"):
            edits_since_test += 1

    if edits_since_test < min_edits:
        return None

    return {
        "signal": SIGNAL_SKIPPING_TESTS,
        "message": (
            f"Reminder: You've modified {edits_since_test} files but "
            f"haven't run tests yet."
        ),
        "decision": "allow",
    }


# ── Main entry point ─────────────────────────────────────────────────────────


def check_drift(
    *,
    session_id: str,
    tool_name: str,
    tool_input: dict,
    config: DriftConfig | None = None,
) -> dict | None:
    """Check for drift signals and return an injection dict if needed.

    Returns:
        Dict with signal, message, decision keys if drift detected.
        None if no drift or rate-limited.
    """
    if config is None:
        config = DriftConfig()

    enabled = config.enabled_signals()
    if not enabled:
        return None

    agent_data = _read_agent_by_session(session_id)
    if not agent_data:
        return None

    agent_id = agent_data.get("id", "")
    ticket_id = agent_data.get("current_ticket")
    file_path = tool_input.get("file_path")

    # Read state for rate limiting
    drift_state = _read_drift_state(session_id)
    activity = _read_activity(session_id)
    current_count = len(activity)
    last_injection = drift_state.get("last_injection_at_count", 0)

    if current_count - last_injection < config.min_interval_tool_calls and last_injection > 0:
        return None  # Rate limited

    # Read context
    locks = _read_locks()
    ticket_meta = _read_ticket(ticket_id) if ticket_id else None

    # Check signals in priority order
    result = None

    if SIGNAL_WRONG_FILE in enabled and not result:
        result = _check_wrong_file(agent_id, file_path, locks)

    if SIGNAL_SKIPPING_TESTS in enabled and not result:
        result = _check_skipping_tests(activity, _MIN_EDITS_BEFORE_TEST_REMINDER)

    if SIGNAL_OFF_TICKET in enabled and not result:
        result = _check_off_ticket(ticket_meta, activity, config.min_interval_tool_calls)

    if SIGNAL_OUT_OF_SCOPE in enabled and not result:
        result = _check_out_of_scope(ticket_meta, file_path)

    if not result:
        return None

    # Update rate limit state
    drift_state["last_injection_at_count"] = current_count
    _write_drift_state(session_id, drift_state)

    # Log injection
    _log_injection(session_id, result["signal"], result["message"], file_path)

    return result


def load_config_from_file() -> DriftConfig:
    """Load drift config from .track/config.json."""
    if not paths.CONFIG_FILE.exists():
        return DriftConfig()
    try:
        data = json.loads(paths.CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return DriftConfig()

    dc = data.get("drift_correction", {})
    if not dc.get("enabled", True):
        return DriftConfig(aggressiveness="off")

    return DriftConfig(
        aggressiveness=dc.get("aggressiveness", "gentle"),
        min_interval_tool_calls=dc.get("min_interval_tool_calls", 10),
    )
