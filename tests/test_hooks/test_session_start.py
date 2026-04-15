"""Tests for SessionStart hook handler — auto-register agent."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def track_env(tmp_path):
    """Provide temp project-local and ephemeral directories."""
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
    env = os.environ.copy()
    env["TRACK_DIR"] = str(track)
    env["TRACK_HOME"] = str(home)
    return tmp_path, track, home, env


def _run_hook(
    subcommand: str, payload: dict, env: dict, cwd: Path | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "agent_track.cli", "hook", subcommand],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
    )


def _make_startup_event(session_id: str = "sess_test_001", cwd: str = "/tmp") -> dict:
    return {
        "hook_event_name": "SessionStart",
        "session_id": session_id,
        "cwd": cwd,
        "source": "startup",
        "model": "claude-sonnet-4-6",
        "transcript_path": "/tmp/transcript.jsonl",
        "permission_mode": "default",
    }


class TestSessionStart:
    def test_startup_creates_agent_record(self, track_env):
        tmp_path, track, home, env = track_env
        payload = _make_startup_event("sess_abc123", str(tmp_path))
        result = _run_hook("session-start", payload, env, tmp_path)
        assert result.returncode == 0

        agent_file = home / "agents" / "sess_abc123.json"
        assert agent_file.exists()
        data = json.loads(agent_file.read_text())
        assert data["session_id"] == "sess_abc123"
        assert data["status"] == "active"
        assert data["model"] == "claude-sonnet-4-6"

    def test_startup_generates_nato_alias(self, track_env):
        tmp_path, track, home, env = track_env
        payload = _make_startup_event("sess_nato_test")
        result = _run_hook("session-start", payload, env, tmp_path)
        assert result.returncode == 0

        agent_file = home / "agents" / "sess_nato_test.json"
        data = json.loads(agent_file.read_text())
        # Agent ID should be a NATO phonetic name
        assert data["id"].startswith("agent-")
        assert data["id"] != "agent-"  # not empty

    def test_startup_skips_existing_nato_names(self, track_env):
        tmp_path, track, home, env = track_env
        # Pre-register agent-alpha
        existing = {"id": "agent-alpha", "session_id": "sess_old", "status": "active"}
        (home / "agents" / "sess_old.json").write_text(json.dumps(existing))

        payload = _make_startup_event("sess_new")
        _run_hook("session-start", payload, env, tmp_path)

        agent_file = home / "agents" / "sess_new.json"
        data = json.loads(agent_file.read_text())
        # Should NOT be agent-alpha since it's taken
        assert data["id"] != "agent-alpha"
        assert data["id"].startswith("agent-")

    def test_startup_posts_to_board(self, track_env):
        tmp_path, track, home, env = track_env
        payload = _make_startup_event("sess_board_test")
        _run_hook("session-start", payload, env, tmp_path)

        board = (track / "BOARD.md").read_text()
        assert "auto-registered" in board.lower() or "registered" in board.lower()

    def test_startup_creates_session_directory(self, track_env):
        tmp_path, track, home, env = track_env
        payload = _make_startup_event("sess_dir_test")
        _run_hook("session-start", payload, env, tmp_path)

        session_dir = home / "sessions" / "sess_dir_test"
        assert session_dir.is_dir()
        # start.json should exist with the event payload
        start_file = session_dir / "start.json"
        assert start_file.exists()

    def test_resume_updates_heartbeat_only(self, track_env):
        tmp_path, track, home, env = track_env
        # First, startup
        payload = _make_startup_event("sess_resume_test")
        _run_hook("session-start", payload, env, tmp_path)

        agent_file = home / "agents" / "sess_resume_test.json"
        data_before = json.loads(agent_file.read_text())
        original_registered_at = data_before["registered_at"]

        # Resume event
        payload["source"] = "resume"
        _run_hook("session-start", payload, env, tmp_path)

        data_after = json.loads(agent_file.read_text())
        # registered_at should NOT change
        assert data_after["registered_at"] == original_registered_at
        # status should still be active
        assert data_after["status"] == "active"

    def test_resume_does_not_reregister(self, track_env):
        tmp_path, track, home, env = track_env
        # Startup
        payload = _make_startup_event("sess_no_rereg")
        _run_hook("session-start", payload, env, tmp_path)

        # Count board entries
        board_before = (track / "BOARD.md").read_text()
        reg_count_before = board_before.lower().count("registered")

        # Resume
        payload["source"] = "resume"
        _run_hook("session-start", payload, env, tmp_path)

        board_after = (track / "BOARD.md").read_text()
        reg_count_after = board_after.lower().count("registered")
        # Should not add another registration message
        assert reg_count_after == reg_count_before

    def test_agent_record_has_session_id_and_model(self, track_env):
        tmp_path, track, home, env = track_env
        payload = _make_startup_event("sess_fields_test")
        payload["model"] = "claude-opus-4-6"
        _run_hook("session-start", payload, env, tmp_path)

        data = json.loads((home / "agents" / "sess_fields_test.json").read_text())
        assert data["session_id"] == "sess_fields_test"
        assert data["model"] == "claude-opus-4-6"
        assert "registered_at" in data
        assert "last_heartbeat" in data
        assert "history" in data
