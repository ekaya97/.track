"""Tests for SessionEnd hook handler — auto-deregister, session summary."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def track_env(tmp_path):
    """Provide temp directories with a pre-registered agent and activity."""
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

    sid = "sess_end_test"
    agent = {
        "id": "agent-alpha",
        "session_id": sid,
        "registered_at": "2026-04-15T10:00:00Z",
        "last_heartbeat": "2026-04-15T11:00:00Z",
        "status": "active",
        "model": "claude-sonnet-4-6",
        "current_ticket": "T-0001",
        "capabilities": [],
        "files_touched": [
            {"path": "src/auth.py", "ticket": "T-0001", "timestamp": "2026-04-15T10:30:00Z"},
            {"path": "tests/test_auth.py", "ticket": "T-0001", "timestamp": "2026-04-15T10:45:00Z"},
        ],
        "history": [{"action": "registered", "timestamp": "2026-04-15T10:00:00Z"}],
    }
    (home / "agents" / f"{sid}.json").write_text(json.dumps(agent))

    # Create a ticket (in-progress, so it should NOT be released)
    ticket_dir = track / "tickets" / "T-0001"
    ticket_dir.mkdir(parents=True)
    (ticket_dir / "ticket.md").write_text(
        "---\nid: T-0001\ntitle: Test ticket\nstatus: in-progress\npriority: medium\n"
        "created: 2026-04-15T10:00:00Z\ncreated_by: human\nclaimed_by: agent-alpha\n"
        "claimed_at: 2026-04-15T10:05:00Z\nlabels: []\nbranch: null\nfiles: []\ndepends_on: []\n"
        "---\n\n## Description\n\nTest.\n"
    )

    # Create activity log
    session_dir = home / "sessions" / sid
    session_dir.mkdir()
    activity = [
        {"ts": "2026-04-15T10:10:00Z", "tool": "Read", "file": "src/auth.py", "tool_use_id": "t1"},
        {"ts": "2026-04-15T10:15:00Z", "tool": "Edit", "file": "src/auth.py", "tool_use_id": "t2"},
        {"ts": "2026-04-15T10:20:00Z", "tool": "Write", "file": "tests/test_auth.py", "tool_use_id": "t3"},
        {"ts": "2026-04-15T10:25:00Z", "tool": "Bash", "command": "pytest tests/", "is_test_run": True, "tool_use_id": "t4"},
        {"ts": "2026-04-15T10:30:00Z", "tool": "Bash", "command": "pytest tests/", "is_test_run": True, "is_failure": True, "error": "exit 1", "tool_use_id": "t5"},
        {"ts": "2026-04-15T10:35:00Z", "tool": "Edit", "file": "src/auth.py", "tool_use_id": "t6"},
        {"ts": "2026-04-15T10:40:00Z", "tool": "Bash", "command": "pytest tests/", "is_test_run": True, "tool_use_id": "t7"},
        {"ts": "2026-04-15T10:45:00Z", "tool": "Bash", "command": "ls -la", "tool_use_id": "t8"},
    ]
    with open(session_dir / "activity.jsonl", "w") as f:
        for entry in activity:
            f.write(json.dumps(entry) + "\n")

    (session_dir / "start.json").write_text(json.dumps({
        "session_id": sid,
        "source": "startup",
        "model": "claude-sonnet-4-6",
    }))

    env = os.environ.copy()
    env["TRACK_DIR"] = str(track)
    env["TRACK_HOME"] = str(home)
    return tmp_path, track, home, env, sid


def _run_hook(payload: dict, env: dict, cwd: Path | None = None):
    return subprocess.run(
        [sys.executable, "-m", "agent_track.cli", "hook", "session-end"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
    )


def _make_event(session_id: str = "sess_end_test") -> dict:
    return {
        "hook_event_name": "SessionEnd",
        "session_id": session_id,
        "cwd": "/tmp",
        "source": "prompt_input_exit",
        "transcript_path": "/tmp/transcript.jsonl",
        "permission_mode": "default",
    }


class TestSessionEnd:
    def test_deregisters_agent(self, track_env):
        tmp_path, track, home, env, sid = track_env
        _run_hook(_make_event(sid), env, tmp_path)

        data = json.loads((home / "agents" / f"{sid}.json").read_text())
        assert data["status"] == "deregistered"

    def test_generates_session_summary(self, track_env):
        tmp_path, track, home, env, sid = track_env
        _run_hook(_make_event(sid), env, tmp_path)

        summary_file = home / "sessions" / sid / "summary.json"
        assert summary_file.exists()
        summary = json.loads(summary_file.read_text())
        assert summary["session_id"] == sid
        assert summary["agent"] == "agent-alpha"
        assert "ended_at" in summary

    def test_summary_counts_files_modified(self, track_env):
        tmp_path, track, home, env, sid = track_env
        _run_hook(_make_event(sid), env, tmp_path)

        summary = json.loads((home / "sessions" / sid / "summary.json").read_text())
        assert "src/auth.py" in summary["files_modified"]
        assert "tests/test_auth.py" in summary["files_modified"]

    def test_summary_counts_tools_used(self, track_env):
        tmp_path, track, home, env, sid = track_env
        _run_hook(_make_event(sid), env, tmp_path)

        summary = json.loads((home / "sessions" / sid / "summary.json").read_text())
        assert summary["tools_used"]["Edit"] == 2
        assert summary["tools_used"]["Bash"] == 4
        assert summary["tools_used"]["Read"] == 1
        assert summary["tools_used"]["Write"] == 1

    def test_summary_counts_test_runs(self, track_env):
        tmp_path, track, home, env, sid = track_env
        _run_hook(_make_event(sid), env, tmp_path)

        summary = json.loads((home / "sessions" / sid / "summary.json").read_text())
        assert summary["test_runs"] == 3

    def test_summary_detects_test_failures(self, track_env):
        tmp_path, track, home, env, sid = track_env
        _run_hook(_make_event(sid), env, tmp_path)

        summary = json.loads((home / "sessions" / sid / "summary.json").read_text())
        assert summary["test_failures"] == 1

    def test_posts_to_board(self, track_env):
        tmp_path, track, home, env, sid = track_env
        _run_hook(_make_event(sid), env, tmp_path)

        board = (track / "BOARD.md").read_text()
        assert "session ended" in board.lower()

    def test_does_not_release_in_progress_tickets(self, track_env):
        """In-progress tickets stay claimed — stale reclaim handles them."""
        tmp_path, track, home, env, sid = track_env
        _run_hook(_make_event(sid), env, tmp_path)

        data = json.loads((home / "agents" / f"{sid}.json").read_text())
        assert data["current_ticket"] == "T-0001"

    def test_releases_claimed_tickets(self, track_env):
        """Tickets still in 'claimed' status are released back to backlog."""
        tmp_path, track, home, env, sid = track_env
        # Change ticket to claimed (not in-progress)
        ticket_path = track / "tickets" / "T-0001" / "ticket.md"
        text = ticket_path.read_text()
        text = text.replace("status: in-progress", "status: claimed")
        ticket_path.write_text(text)

        _run_hook(_make_event(sid), env, tmp_path)

        # Ticket should be back to backlog
        from agent_track.services.frontmatter import parse_frontmatter
        meta, _ = parse_frontmatter(ticket_path.read_text())
        assert meta["status"] == "backlog"
        assert meta["claimed_by"] is None

        # Agent's current_ticket should be cleared
        data = json.loads((home / "agents" / f"{sid}.json").read_text())
        assert data["current_ticket"] is None

    def test_handles_missing_agent_record(self, track_env):
        tmp_path, track, home, env, sid = track_env
        result = _run_hook(_make_event("sess_nonexistent"), env, tmp_path)
        assert result.returncode == 0

    def test_handles_empty_activity_log(self, track_env):
        tmp_path, track, home, env, sid = track_env
        # Overwrite activity with empty file
        (home / "sessions" / sid / "activity.jsonl").write_text("")
        result = _run_hook(_make_event(sid), env, tmp_path)
        assert result.returncode == 0

        summary = json.loads((home / "sessions" / sid / "summary.json").read_text())
        assert summary["test_runs"] == 0
        assert summary["files_modified"] == []
