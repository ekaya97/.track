"""Tests for soft lock table and conflict detection."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def track_env(tmp_path):
    """Provide temp directories with two pre-registered agents."""
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

    # Register two agents
    for sid, name in [("sess_alpha", "agent-alpha"), ("sess_bravo", "agent-bravo")]:
        agent = {
            "id": name,
            "session_id": sid,
            "registered_at": "2026-04-15T10:00:00Z",
            "last_heartbeat": "2026-04-15T10:00:00Z",
            "status": "active",
            "current_ticket": None,
            "capabilities": [],
            "files_touched": [],
            "history": [],
        }
        (home / "agents" / f"{sid}.json").write_text(json.dumps(agent))
        (home / "sessions" / sid).mkdir()

    env = os.environ.copy()
    env["TRACK_DIR"] = str(track)
    env["TRACK_HOME"] = str(home)
    return tmp_path, track, home, env


def _run_post(payload: dict, env: dict, cwd: Path | None = None):
    return subprocess.run(
        [sys.executable, "-m", "agent_track.cli", "hook", "post-tool-use"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
    )


def _make_write_event(session_id: str, file_path: str) -> dict:
    return {
        "hook_event_name": "PostToolUse",
        "session_id": session_id,
        "cwd": "/tmp",
        "tool_name": "Edit",
        "tool_use_id": "toolu_01ABC",
        "tool_input": {"file_path": file_path, "old_string": "a", "new_string": "b"},
        "tool_response": {"success": True},
        "permission_mode": "default",
    }


class TestSoftLocks:
    def test_no_conflict_when_single_agent(self, track_env):
        tmp_path, track, home, env = track_env
        _run_post(_make_write_event("sess_alpha", "/tmp/src/auth.py"), env, tmp_path)

        conflicts_file = home / "security" / "conflicts.jsonl"
        assert not conflicts_file.exists()

    def test_conflict_detected_within_window(self, track_env):
        tmp_path, track, home, env = track_env
        # Agent alpha edits a file
        _run_post(_make_write_event("sess_alpha", "/tmp/src/auth.py"), env, tmp_path)
        # Agent bravo edits the SAME file
        _run_post(_make_write_event("sess_bravo", "/tmp/src/auth.py"), env, tmp_path)

        conflicts_file = home / "security" / "conflicts.jsonl"
        assert conflicts_file.exists()
        entry = json.loads(conflicts_file.read_text().strip())
        assert "/tmp/src/auth.py" in entry["file"]
        assert "agent-alpha" in entry["agents"]
        assert "agent-bravo" in entry["agents"]

    def test_no_conflict_different_files(self, track_env):
        tmp_path, track, home, env = track_env
        _run_post(_make_write_event("sess_alpha", "/tmp/src/auth.py"), env, tmp_path)
        _run_post(_make_write_event("sess_bravo", "/tmp/src/db.py"), env, tmp_path)

        conflicts_file = home / "security" / "conflicts.jsonl"
        assert not conflicts_file.exists()

    def test_conflict_includes_both_agents(self, track_env):
        tmp_path, track, home, env = track_env
        _run_post(_make_write_event("sess_alpha", "/tmp/x.py"), env, tmp_path)
        _run_post(_make_write_event("sess_bravo", "/tmp/x.py"), env, tmp_path)

        entry = json.loads(
            (home / "security" / "conflicts.jsonl").read_text().strip()
        )
        assert set(entry["agents"]) == {"agent-alpha", "agent-bravo"}

    def test_same_agent_no_conflict(self, track_env):
        """Same agent editing the same file twice is NOT a conflict."""
        tmp_path, track, home, env = track_env
        _run_post(_make_write_event("sess_alpha", "/tmp/x.py"), env, tmp_path)
        _run_post(_make_write_event("sess_alpha", "/tmp/x.py"), env, tmp_path)

        conflicts_file = home / "security" / "conflicts.jsonl"
        assert not conflicts_file.exists()
