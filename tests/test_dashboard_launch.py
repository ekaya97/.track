"""Tests for dashboard integration — ticket-from-finding, launch, verification, injections."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_track.dashboard.server import TrackHandler


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def dash_env(tmp_path, monkeypatch):
    """Set up a full .track/ environment for dashboard API tests."""
    track_dir = tmp_path / ".track"
    track_dir.mkdir()
    tickets_dir = track_dir / "tickets"
    tickets_dir.mkdir()
    (track_dir / "archive").mkdir()
    analysis_dir = track_dir / "analysis"
    analysis_dir.mkdir()
    board = track_dir / "BOARD.md"
    board.write_text("# .track Board\n\n<!-- New messages are prepended below this line -->\n")

    home = tmp_path / "home"
    home.mkdir()
    (home / "locks").mkdir()
    (home / "agents").mkdir()
    sessions = home / "sessions"
    sessions.mkdir()

    monkeypatch.setattr("agent_track.services.paths.TRACK_DIR", track_dir)
    monkeypatch.setattr("agent_track.services.paths.TICKETS_DIR", tickets_dir)
    monkeypatch.setattr("agent_track.services.paths.ARCHIVE_DIR", track_dir / "archive")
    monkeypatch.setattr("agent_track.services.paths.ANALYSIS_DIR", analysis_dir)
    monkeypatch.setattr("agent_track.services.paths.BOARD_FILE", board)
    monkeypatch.setattr("agent_track.services.paths.CONFIG_FILE", track_dir / "config.json")
    monkeypatch.setattr("agent_track.services.paths.GRAPH_DIR", track_dir / "graph")
    monkeypatch.setattr("agent_track.services.paths.PROJECT_HOME", home)
    monkeypatch.setattr("agent_track.services.paths.LOCKS_DIR", home / "locks")
    monkeypatch.setattr("agent_track.services.paths.LOCKS_FILE", home / "locks.json")
    monkeypatch.setattr("agent_track.services.paths.AGENTS_DIR", home / "agents")
    monkeypatch.setattr("agent_track.services.paths.SESSIONS_DIR", sessions)

    return {
        "track_dir": track_dir,
        "tickets_dir": tickets_dir,
        "analysis_dir": analysis_dir,
        "sessions": sessions,
    }


def _write_ticket(env, ticket_id, labels=None, files=None):
    from agent_track.services.models import write_ticket
    meta = {
        "id": ticket_id,
        "title": f"Test ticket {ticket_id}",
        "status": "backlog",
        "priority": "medium",
        "created": "2026-04-15T10:00:00Z",
        "created_by": "human",
        "claimed_by": None,
        "claimed_at": None,
        "labels": labels or [],
        "branch": None,
        "files": files or [],
        "depends_on": [],
    }
    write_ticket(meta, "## Description\n\nTest.\n", env["tickets_dir"] / f"{ticket_id}.md")
    return meta


# ── Tests for create-ticket-from-finding ─────────────────────────────────────


class TestCreateTicketFromFinding:
    def test_creates_ticket_from_duplicate_finding(self, dash_env):
        from agent_track.dashboard.api import create_ticket_from_finding

        finding = {
            "type": "duplicates",
            "data": {
                "hash": "abc123",
                "type": "exact",
                "functions": [
                    {"file": "src/auth.py", "name": "validate_token", "line_start": 45, "line_end": 60, "lines": 16},
                    {"file": "src/api.py", "name": "check_token", "line_start": 112, "line_end": 127, "lines": 16},
                ],
                "suggested_action": "Extract to shared utility function",
            },
        }
        result = create_ticket_from_finding(finding)
        assert "ticket_id" in result
        assert result["ticket_id"].startswith("T-")

    def test_creates_ticket_from_coverage_finding(self, dash_env):
        from agent_track.dashboard.api import create_ticket_from_finding

        finding = {
            "type": "coverage",
            "data": {
                "file": "src/auth.py",
                "name": "refresh_token",
                "line_start": 45,
                "line_end": 72,
            },
        }
        result = create_ticket_from_finding(finding)
        assert "ticket_id" in result

    def test_creates_ticket_from_security_finding(self, dash_env):
        from agent_track.dashboard.api import create_ticket_from_finding

        finding = {
            "type": "security",
            "data": {
                "type": "hardcoded_secret",
                "severity": "high",
                "file": "src/config.py",
                "line": 15,
                "pattern": "AKIA prefix (AWS key)",
                "snippet": 'KEY = "AKIA..."',
            },
        }
        result = create_ticket_from_finding(finding)
        assert "ticket_id" in result

    def test_returns_error_for_unknown_type(self, dash_env):
        from agent_track.dashboard.api import create_ticket_from_finding

        result = create_ticket_from_finding({"type": "unknown", "data": {}})
        assert "error" in result


# ── Tests for verification endpoint ──────────────────────────────────────────


class TestVerificationEndpoint:
    def test_returns_verification_data(self, dash_env):
        from agent_track.dashboard.api import get_ticket_verification

        # Create ticket dir with verification.json
        ticket_dir = dash_env["tickets_dir"] / "T-0001"
        ticket_dir.mkdir()
        _write_ticket(dash_env, "T-0001")
        # Move to dir format
        flat = dash_env["tickets_dir"] / "T-0001.md"
        if flat.exists():
            flat.rename(ticket_dir / "ticket.md")

        verification = {
            "ticket_id": "T-0001",
            "verified_at": "2026-04-15T11:00:00Z",
            "result": "pass",
            "checks": [],
            "follow_up_needed": False,
        }
        (ticket_dir / "verification.json").write_text(json.dumps(verification))

        result = get_ticket_verification("T-0001")
        assert result["result"] == "pass"

    def test_returns_none_when_no_verification(self, dash_env):
        from agent_track.dashboard.api import get_ticket_verification

        _write_ticket(dash_env, "T-0099")
        result = get_ticket_verification("T-0099")
        assert result is None or "error" in result


# ── Tests for injection log endpoint ─────────────────────────────────────────


class TestInjectionLogEndpoint:
    def test_returns_injection_history(self, dash_env):
        from agent_track.dashboard.api import get_ticket_injections

        # Create a session with injections for a ticket
        # First create an agent tied to a ticket
        agent_data = {
            "id": "agent-alpha",
            "session_id": "sess-a",
            "status": "active",
            "current_ticket": "T-0001",
            "last_heartbeat": "2026-04-15T10:00:00Z",
        }
        (dash_env["sessions"].parent / "agents" / "sess-a.json").write_text(json.dumps(agent_data))

        session_dir = dash_env["sessions"] / "sess-a"
        session_dir.mkdir()
        injections = [
            {"ts": "2026-04-15T10:05:00Z", "signal": "wrong_file", "message": "Note: file locked"},
            {"ts": "2026-04-15T10:10:00Z", "signal": "skipping_tests", "message": "Run tests"},
        ]
        with open(session_dir / "injections.jsonl", "w") as f:
            for entry in injections:
                f.write(json.dumps(entry) + "\n")

        result = get_ticket_injections("T-0001")
        assert len(result) == 2
        assert result[0]["signal"] == "wrong_file"

    def test_returns_empty_when_no_injections(self, dash_env):
        from agent_track.dashboard.api import get_ticket_injections

        result = get_ticket_injections("T-9999")
        assert result == []


# ── Tests for follow-up button ───────────────────────────────────────────────


class TestFollowUpButton:
    def test_follow_up_on_failed_verification(self, dash_env):
        from agent_track.dashboard.api import get_ticket_verification

        ticket_dir = dash_env["tickets_dir"] / "T-0001"
        ticket_dir.mkdir()
        _write_ticket(dash_env, "T-0001")
        flat = dash_env["tickets_dir"] / "T-0001.md"
        if flat.exists():
            flat.rename(ticket_dir / "ticket.md")

        verification = {
            "ticket_id": "T-0001",
            "verified_at": "2026-04-15T11:00:00Z",
            "result": "fail",
            "checks": [{"type": "duplicates", "pre": {"clusters": 2}, "post": {"clusters": 2}, "result": "fail"}],
            "follow_up_needed": True,
        }
        (ticket_dir / "verification.json").write_text(json.dumps(verification))

        result = get_ticket_verification("T-0001")
        assert result["follow_up_needed"] is True
