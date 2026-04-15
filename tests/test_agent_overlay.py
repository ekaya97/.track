"""Tests for real-time agent activity overlay on the graph."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from agent_track.services import paths


@pytest.fixture(autouse=True)
def track_env(tmp_path, monkeypatch):
    """Set up temp project-local and ephemeral directories."""
    track_dir = tmp_path / ".track"
    home_dir = tmp_path / ".track-home"

    monkeypatch.setattr(paths, "TRACK_DIR", track_dir)
    monkeypatch.setattr(paths, "AGENTS_DIR", home_dir / "agents")
    monkeypatch.setattr(paths, "SESSIONS_DIR", home_dir / "sessions")
    monkeypatch.setattr(paths, "GRAPH_DIR", track_dir / "graph")

    for d in [
        track_dir, track_dir / "graph",
        home_dir / "agents", home_dir / "sessions",
    ]:
        d.mkdir(parents=True, exist_ok=True)

    return track_dir, home_dir


def _write_agent(home_dir: Path, sid: str, agent_id: str, status: str = "active"):
    agent = {
        "id": agent_id,
        "session_id": sid,
        "status": status,
        "registered_at": "2026-04-15T10:00:00Z",
        "last_heartbeat": "2026-04-15T12:50:00Z",
    }
    (home_dir / "agents" / f"{sid}.json").write_text(json.dumps(agent))


def _write_activity(home_dir: Path, sid: str, entries: list[dict]):
    session_dir = home_dir / "sessions" / sid
    session_dir.mkdir(parents=True, exist_ok=True)
    with open(session_dir / "activity.jsonl", "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


class TestAgentActivityAPI:
    def test_returns_file_to_agent_mapping(self, track_env):
        _, home_dir = track_env
        from agent_track.dashboard.server import _get_agent_file_activity

        _write_agent(home_dir, "sess1", "agent-alpha")
        _write_activity(home_dir, "sess1", [
            {"ts": "2026-04-15T12:50:00Z", "tool": "Edit", "file": "/project/src/auth.py"},
            {"ts": "2026-04-15T12:50:05Z", "tool": "Read", "file": "/project/src/db.py"},
        ])

        result = _get_agent_file_activity("/project")
        assert "src/auth.py" in result
        assert result["src/auth.py"]["agent"] == "agent-alpha"

    def test_uses_relative_paths(self, track_env):
        _, home_dir = track_env
        from agent_track.dashboard.server import _get_agent_file_activity

        _write_agent(home_dir, "sess1", "agent-alpha")
        _write_activity(home_dir, "sess1", [
            {"ts": "2026-04-15T12:50:00Z", "tool": "Write", "file": "/project/src/cli.py"},
        ])

        result = _get_agent_file_activity("/project")
        # Should be relative, not absolute
        assert "src/cli.py" in result
        assert "/project/src/cli.py" not in result

    def test_tracks_most_recent_activity(self, track_env):
        _, home_dir = track_env
        from agent_track.dashboard.server import _get_agent_file_activity

        _write_agent(home_dir, "sess1", "agent-alpha")
        _write_activity(home_dir, "sess1", [
            {"ts": "2026-04-15T12:40:00Z", "tool": "Read", "file": "/project/src/auth.py"},
            {"ts": "2026-04-15T12:50:00Z", "tool": "Edit", "file": "/project/src/auth.py"},
        ])

        result = _get_agent_file_activity("/project")
        assert result["src/auth.py"]["last_active"] == "2026-04-15T12:50:00Z"
        assert result["src/auth.py"]["tool"] == "Edit"

    def test_multiple_agents_on_different_files(self, track_env):
        _, home_dir = track_env
        from agent_track.dashboard.server import _get_agent_file_activity

        _write_agent(home_dir, "sess1", "agent-alpha")
        _write_agent(home_dir, "sess2", "agent-bravo")
        _write_activity(home_dir, "sess1", [
            {"ts": "2026-04-15T12:50:00Z", "tool": "Edit", "file": "/project/src/auth.py"},
        ])
        _write_activity(home_dir, "sess2", [
            {"ts": "2026-04-15T12:50:10Z", "tool": "Edit", "file": "/project/src/db.py"},
        ])

        result = _get_agent_file_activity("/project")
        assert result["src/auth.py"]["agent"] == "agent-alpha"
        assert result["src/db.py"]["agent"] == "agent-bravo"

    def test_skips_deregistered_agents(self, track_env):
        _, home_dir = track_env
        from agent_track.dashboard.server import _get_agent_file_activity

        _write_agent(home_dir, "sess1", "agent-alpha", status="deregistered")
        _write_activity(home_dir, "sess1", [
            {"ts": "2026-04-15T12:50:00Z", "tool": "Edit", "file": "/project/src/auth.py"},
        ])

        result = _get_agent_file_activity("/project")
        assert len(result) == 0

    def test_skips_entries_without_file(self, track_env):
        _, home_dir = track_env
        from agent_track.dashboard.server import _get_agent_file_activity

        _write_agent(home_dir, "sess1", "agent-alpha")
        _write_activity(home_dir, "sess1", [
            {"ts": "2026-04-15T12:50:00Z", "tool": "Bash", "command": "ls"},
            {"ts": "2026-04-15T12:50:05Z", "tool": "Edit", "file": "/project/src/auth.py"},
        ])

        result = _get_agent_file_activity("/project")
        assert len(result) == 1
        assert "src/auth.py" in result

    def test_empty_sessions_returns_empty(self, track_env):
        from agent_track.dashboard.server import _get_agent_file_activity

        result = _get_agent_file_activity("/project")
        assert result == {}
