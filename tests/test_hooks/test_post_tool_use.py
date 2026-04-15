"""Tests for PostToolUse hook handler — file activity capture, heartbeat, locks."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.fixture
def track_env(tmp_path):
    """Provide temp directories with a pre-registered agent."""
    track = tmp_path / ".track"
    home = tmp_path / ".track-home"
    track.mkdir()
    (track / "tickets").mkdir()
    (track / "archive").mkdir()
    (track / "BOARD.md").write_text(
        "# .track Board\n\n<!-- New messages are prepended below this line -->\n"
    )
    for d in ["agents", "sessions", "security", "locks"]:
        (home / d).mkdir(parents=True)

    # Pre-register an agent
    session_id = "sess_post_test"
    agent = {
        "id": "agent-alpha",
        "session_id": session_id,
        "registered_at": "2026-04-15T10:00:00Z",
        "last_heartbeat": "2026-04-15T10:00:00Z",
        "status": "active",
        "model": "claude-sonnet-4-6",
        "current_ticket": None,
        "capabilities": [],
        "files_touched": [],
        "history": [{"action": "registered", "timestamp": "2026-04-15T10:00:00Z"}],
    }
    (home / "agents" / f"{session_id}.json").write_text(json.dumps(agent))
    (home / "sessions" / session_id).mkdir()

    env = os.environ.copy()
    env["TRACK_DIR"] = str(track)
    env["TRACK_HOME"] = str(home)
    return tmp_path, track, home, env, session_id


def _run_hook(payload: dict, env: dict, cwd: Path | None = None):
    return subprocess.run(
        [sys.executable, "-m", "agent_track.cli", "hook", "post-tool-use"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
    )


def _make_event(
    session_id: str,
    tool_name: str = "Read",
    tool_input: dict | None = None,
    tool_response: dict | None = None,
    is_failure: bool = False,
    error: str | None = None,
) -> dict:
    event = {
        "hook_event_name": "PostToolUseFailure" if is_failure else "PostToolUse",
        "session_id": session_id,
        "cwd": "/tmp",
        "tool_name": tool_name,
        "tool_use_id": "toolu_01ABC",
        "tool_input": tool_input or {},
        "permission_mode": "default",
    }
    if is_failure:
        event["error"] = error or "Command failed"
        event["is_interrupt"] = False
    else:
        event["tool_response"] = tool_response or {"success": True}
    return event


class TestPostToolUse:
    def test_updates_agent_heartbeat(self, track_env):
        tmp_path, track, home, env, sid = track_env
        payload = _make_event(sid, "Read", {"file_path": "/tmp/foo.py"})
        _run_hook(payload, env, tmp_path)

        data = json.loads((home / "agents" / f"{sid}.json").read_text())
        assert data["last_heartbeat"] != "2026-04-15T10:00:00Z"

    def test_write_tool_extracts_file_path(self, track_env):
        tmp_path, track, home, env, sid = track_env
        payload = _make_event(sid, "Write", {"file_path": "/tmp/src/auth.py", "content": "x"})
        _run_hook(payload, env, tmp_path)

        data = json.loads((home / "agents" / f"{sid}.json").read_text())
        touched_paths = [f["path"] for f in data.get("files_touched", [])]
        assert "/tmp/src/auth.py" in touched_paths

    def test_edit_tool_extracts_file_path(self, track_env):
        tmp_path, track, home, env, sid = track_env
        payload = _make_event(
            sid, "Edit",
            {"file_path": "/tmp/src/db.py", "old_string": "a", "new_string": "b"},
        )
        _run_hook(payload, env, tmp_path)

        data = json.loads((home / "agents" / f"{sid}.json").read_text())
        touched_paths = [f["path"] for f in data.get("files_touched", [])]
        assert "/tmp/src/db.py" in touched_paths

    def test_read_tool_does_not_update_locks(self, track_env):
        tmp_path, track, home, env, sid = track_env
        payload = _make_event(sid, "Read", {"file_path": "/tmp/src/auth.py"})
        _run_hook(payload, env, tmp_path)

        locks_file = home / "locks.json"
        if locks_file.exists():
            locks = json.loads(locks_file.read_text())
            assert "/tmp/src/auth.py" not in locks

    def test_bash_tool_captures_command(self, track_env):
        tmp_path, track, home, env, sid = track_env
        payload = _make_event(sid, "Bash", {"command": "ls -la", "description": "List files"})
        _run_hook(payload, env, tmp_path)

        activity_file = home / "sessions" / sid / "activity.jsonl"
        assert activity_file.exists()
        lines = activity_file.read_text().strip().split("\n")
        last = json.loads(lines[-1])
        assert last["tool"] == "Bash"
        assert last["command"] == "ls -la"

    def test_bash_detects_test_run(self, track_env):
        tmp_path, track, home, env, sid = track_env
        for cmd in ["pytest tests/", "npm test", "jest", "cargo test"]:
            payload = _make_event(sid, "Bash", {"command": cmd})
            _run_hook(payload, env, tmp_path)

        activity_file = home / "sessions" / sid / "activity.jsonl"
        lines = activity_file.read_text().strip().split("\n")
        test_entries = [json.loads(l) for l in lines if json.loads(l).get("is_test_run")]
        assert len(test_entries) == 4

    def test_appends_to_activity_jsonl(self, track_env):
        tmp_path, track, home, env, sid = track_env
        # Two events
        _run_hook(_make_event(sid, "Read", {"file_path": "/tmp/a.py"}), env, tmp_path)
        _run_hook(_make_event(sid, "Write", {"file_path": "/tmp/b.py", "content": "x"}), env, tmp_path)

        activity_file = home / "sessions" / sid / "activity.jsonl"
        lines = activity_file.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_activity_entry_format(self, track_env):
        tmp_path, track, home, env, sid = track_env
        payload = _make_event(sid, "Edit", {"file_path": "/tmp/foo.py", "old_string": "a", "new_string": "b"})
        _run_hook(payload, env, tmp_path)

        activity_file = home / "sessions" / sid / "activity.jsonl"
        entry = json.loads(activity_file.read_text().strip())
        assert "ts" in entry
        assert entry["tool"] == "Edit"
        assert entry["file"] == "/tmp/foo.py"
        assert "tool_use_id" in entry

    def test_updates_soft_lock_table(self, track_env):
        tmp_path, track, home, env, sid = track_env
        payload = _make_event(sid, "Write", {"file_path": "/tmp/src/auth.py", "content": "x"})
        _run_hook(payload, env, tmp_path)

        locks_file = home / "locks.json"
        assert locks_file.exists()
        locks = json.loads(locks_file.read_text())
        assert "/tmp/src/auth.py" in locks
        assert locks["/tmp/src/auth.py"]["agent"] == "agent-alpha"
        assert locks["/tmp/src/auth.py"]["session_id"] == sid

    def test_soft_lock_includes_ticket_from_agent(self, track_env):
        tmp_path, track, home, env, sid = track_env
        # Set current_ticket on agent
        agent_file = home / "agents" / f"{sid}.json"
        data = json.loads(agent_file.read_text())
        data["current_ticket"] = "T-0042"
        agent_file.write_text(json.dumps(data))

        payload = _make_event(sid, "Edit", {"file_path": "/tmp/x.py", "old_string": "a", "new_string": "b"})
        _run_hook(payload, env, tmp_path)

        locks = json.loads((home / "locks.json").read_text())
        assert locks["/tmp/x.py"]["ticket"] == "T-0042"

    def test_failure_event_captures_error(self, track_env):
        tmp_path, track, home, env, sid = track_env
        payload = _make_event(
            sid, "Bash",
            tool_input={"command": "npm test"},
            is_failure=True,
            error="exit code 1",
        )
        _run_hook(payload, env, tmp_path)

        activity_file = home / "sessions" / sid / "activity.jsonl"
        entry = json.loads(activity_file.read_text().strip())
        assert entry["error"] == "exit code 1"
        assert entry["is_failure"] is True

    def test_failure_event_records_is_interrupt(self, track_env):
        tmp_path, track, home, env, sid = track_env
        payload = _make_event(
            sid, "Bash",
            tool_input={"command": "long-running"},
            is_failure=True,
            error="interrupted",
        )
        payload["is_interrupt"] = True
        _run_hook(payload, env, tmp_path)

        activity_file = home / "sessions" / sid / "activity.jsonl"
        entry = json.loads(activity_file.read_text().strip())
        assert entry["is_interrupt"] is True

    def test_todo_write_captures_todos(self, track_env):
        tmp_path, track, home, env, sid = track_env
        todos = [
            {"content": "Write tests", "status": "completed", "activeForm": "Writing tests"},
            {"content": "Implement feature", "status": "in_progress", "activeForm": "Implementing"},
        ]
        payload = _make_event(sid, "TodoWrite", {"todos": todos})
        _run_hook(payload, env, tmp_path)

        activity_file = home / "sessions" / sid / "activity.jsonl"
        entry = json.loads(activity_file.read_text().strip().split("\n")[-1])
        assert entry["tool"] == "TodoWrite"
        assert len(entry["todos"]) == 2
        assert entry["todos"][0]["content"] == "Write tests"
        # First write — all items are "added"
        assert len(entry["todo_changes"]) == 2
        assert all(c["action"] == "added" for c in entry["todo_changes"])

    def test_todo_write_diffs_changes(self, track_env):
        tmp_path, track, home, env, sid = track_env
        # First write
        todos_v1 = [
            {"content": "Task A", "status": "pending", "activeForm": "Doing A"},
            {"content": "Task B", "status": "pending", "activeForm": "Doing B"},
        ]
        _run_hook(_make_event(sid, "TodoWrite", {"todos": todos_v1}), env, tmp_path)

        # Second write — A completed, B removed, C added
        todos_v2 = [
            {"content": "Task A", "status": "completed", "activeForm": "Doing A"},
            {"content": "Task C", "status": "in_progress", "activeForm": "Doing C"},
        ]
        _run_hook(_make_event(sid, "TodoWrite", {"todos": todos_v2}), env, tmp_path)

        activity_file = home / "sessions" / sid / "activity.jsonl"
        lines = activity_file.read_text().strip().split("\n")
        entry = json.loads(lines[-1])
        changes = entry["todo_changes"]

        change_map = {c["content"]: c for c in changes}
        assert change_map["Task A"]["action"] == "status_changed"
        assert change_map["Task A"]["from"] == "pending"
        assert change_map["Task A"]["to"] == "completed"
        assert change_map["Task B"]["action"] == "removed"
        assert change_map["Task C"]["action"] == "added"

    def test_handles_missing_agent_record_gracefully(self, track_env):
        tmp_path, track, home, env, sid = track_env
        # Use a session_id with no agent record
        payload = _make_event("sess_unknown", "Read", {"file_path": "/tmp/foo.py"})
        result = _run_hook(payload, env, tmp_path)
        # Should not crash
        assert result.returncode == 0
