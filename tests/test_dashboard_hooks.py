"""Tests for dashboard API endpoints serving hook-captured data."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_track.services import paths


@pytest.fixture(autouse=True)
def track_env(tmp_path, monkeypatch):
    """Set up temp project-local and ephemeral directories."""
    track_dir = tmp_path / ".track"
    home_dir = tmp_path / ".track-home"

    monkeypatch.setattr(paths, "TRACK_DIR", track_dir)
    monkeypatch.setattr(paths, "TICKETS_DIR", track_dir / "tickets")
    monkeypatch.setattr(paths, "ARCHIVE_DIR", track_dir / "archive")
    monkeypatch.setattr(paths, "BOARD_FILE", track_dir / "BOARD.md")
    monkeypatch.setattr(paths, "CONVENTIONS_FILE", track_dir / "CONVENTIONS.md")
    monkeypatch.setattr(paths, "CONFIG_FILE", track_dir / "config.json")
    monkeypatch.setattr(paths, "AGENTS_DIR", home_dir / "agents")
    monkeypatch.setattr(paths, "SESSIONS_DIR", home_dir / "sessions")
    monkeypatch.setattr(paths, "SECURITY_DIR", home_dir / "security")
    monkeypatch.setattr(paths, "LOCKS_DIR", home_dir / "locks")
    monkeypatch.setattr(paths, "LOCKS_FILE", home_dir / "locks.json")
    monkeypatch.setattr(paths, "SERVER_PID_FILE", home_dir / "locks" / "server.pid")

    for d in [
        track_dir, track_dir / "tickets", track_dir / "archive",
        home_dir / "agents", home_dir / "sessions",
        home_dir / "security", home_dir / "locks",
    ]:
        d.mkdir(parents=True, exist_ok=True)

    return track_dir, home_dir


def _write_agent(home_dir: Path, sid: str, agent_id: str, status: str = "active"):
    agent = {
        "id": agent_id,
        "session_id": sid,
        "registered_at": "2026-04-15T10:00:00Z",
        "last_heartbeat": "2026-04-15T11:00:00Z",
        "status": status,
        "model": "claude-sonnet-4-6",
        "current_ticket": None,
        "files_touched": [],
        "history": [],
    }
    (home_dir / "agents" / f"{sid}.json").write_text(json.dumps(agent))


class TestSessionsAPI:
    def test_list_sessions_returns_active(self, track_env):
        _, home_dir = track_env
        from agent_track.dashboard.server import _get_sessions

        _write_agent(home_dir, "sess_001", "agent-alpha", "active")
        _write_agent(home_dir, "sess_002", "agent-bravo", "deregistered")

        sessions = _get_sessions()
        assert len(sessions) == 2
        active = [s for s in sessions if s["status"] == "active"]
        assert len(active) == 1
        assert active[0]["agent_id"] == "agent-alpha"

    def test_session_activity_returns_events(self, track_env):
        _, home_dir = track_env
        from agent_track.dashboard.server import _get_session_activity

        sid = "sess_activity"
        session_dir = home_dir / "sessions" / sid
        session_dir.mkdir()
        entries = [
            {"ts": "2026-04-15T10:10:00Z", "tool": "Read", "file": "a.py"},
            {"ts": "2026-04-15T10:15:00Z", "tool": "Edit", "file": "b.py"},
        ]
        with open(session_dir / "activity.jsonl", "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

        result = _get_session_activity(sid)
        assert len(result) == 2
        assert result[0]["tool"] == "Read"

    def test_session_activity_missing_session(self, track_env):
        from agent_track.dashboard.server import _get_session_activity

        result = _get_session_activity("nonexistent")
        assert result == []


class TestConflictsAPI:
    def test_returns_conflict_list(self, track_env):
        _, home_dir = track_env
        from agent_track.dashboard.server import _get_conflicts

        entries = [
            {"ts": "2026-04-15T10:20:00Z", "file": "src/auth.py", "agents": ["alpha", "bravo"]},
        ]
        with open(home_dir / "security" / "conflicts.jsonl", "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

        result = _get_conflicts()
        assert len(result) == 1
        assert result[0]["file"] == "src/auth.py"

    def test_returns_empty_when_no_conflicts(self, track_env):
        from agent_track.dashboard.server import _get_conflicts

        result = _get_conflicts()
        assert result == []


class TestSecurityAPI:
    def test_returns_access_log(self, track_env):
        _, home_dir = track_env
        from agent_track.dashboard.server import _get_security_alerts

        entries = [
            {"ts": "2026-04-15T10:30:00Z", "session_id": "s1", "tool": "Write", "file": ".env", "action": "warn"},
        ]
        with open(home_dir / "security" / "access-log.jsonl", "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

        result = _get_security_alerts()
        assert len(result) == 1
        assert result[0]["file"] == ".env"

    def test_returns_empty_when_no_alerts(self, track_env):
        from agent_track.dashboard.server import _get_security_alerts

        result = _get_security_alerts()
        assert result == []
