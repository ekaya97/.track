"""Tests for drift detection and injection logic."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_track.hooks.drift import (
    check_drift,
    DriftConfig,
    SIGNAL_WRONG_FILE,
    SIGNAL_OFF_TICKET,
    SIGNAL_OUT_OF_SCOPE,
    SIGNAL_SKIPPING_TESTS,
    SIGNAL_TASK_STALL,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def drift_env(tmp_path, monkeypatch):
    """Set up minimal .track/ and ephemeral dirs for drift testing."""
    track_dir = tmp_path / ".track"
    track_dir.mkdir()
    (track_dir / "tickets").mkdir()
    (track_dir / "archive").mkdir()
    board = track_dir / "BOARD.md"
    board.write_text("# .track Board\n\n<!-- New messages are prepended below this line -->\n")

    home = tmp_path / "home"
    home.mkdir()
    (home / "locks").mkdir()
    (home / "agents").mkdir()
    sessions = home / "sessions"
    sessions.mkdir()

    monkeypatch.setattr("agent_track.services.paths.TRACK_DIR", track_dir)
    monkeypatch.setattr("agent_track.services.paths.TICKETS_DIR", track_dir / "tickets")
    monkeypatch.setattr("agent_track.services.paths.ARCHIVE_DIR", track_dir / "archive")
    monkeypatch.setattr("agent_track.services.paths.BOARD_FILE", board)
    monkeypatch.setattr("agent_track.services.paths.CONFIG_FILE", track_dir / "config.json")
    monkeypatch.setattr("agent_track.services.paths.PROJECT_HOME", home)
    monkeypatch.setattr("agent_track.services.paths.LOCKS_DIR", home / "locks")
    monkeypatch.setattr("agent_track.services.paths.LOCKS_FILE", home / "locks.json")
    monkeypatch.setattr("agent_track.services.paths.AGENTS_DIR", home / "agents")
    monkeypatch.setattr("agent_track.services.paths.SESSIONS_DIR", sessions)

    return {"track_dir": track_dir, "home": home, "sessions": sessions}


def _write_agent(env, agent_id, session_id, ticket=None):
    """Helper to write an agent JSON file."""
    agents_dir = env["home"] / "agents"
    data = {
        "id": agent_id,
        "session_id": session_id,
        "status": "active",
        "current_ticket": ticket,
        "last_heartbeat": "2026-04-15T10:00:00Z",
    }
    (agents_dir / f"{session_id}.json").write_text(json.dumps(data))
    return data


def _write_ticket(env, ticket_id, files=None, labels=None, claimed_by=None):
    """Helper to write a ticket file."""
    from agent_track.services.models import write_ticket
    meta = {
        "id": ticket_id,
        "title": f"Test ticket {ticket_id}",
        "status": "claimed" if claimed_by else "backlog",
        "priority": "medium",
        "created": "2026-04-15T10:00:00Z",
        "created_by": "human",
        "claimed_by": claimed_by,
        "claimed_at": "2026-04-15T10:00:00Z" if claimed_by else None,
        "labels": labels or [],
        "branch": None,
        "files": files or [],
        "depends_on": [],
    }
    path = env["track_dir"] / "tickets" / f"{ticket_id}.md"
    write_ticket(meta, "## Description\n\nTest.\n", path)
    return meta


def _write_activity(env, session_id, entries):
    """Write activity.jsonl for a session."""
    session_dir = env["sessions"] / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    with open(session_dir / "activity.jsonl", "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _write_locks(env, locks_data):
    """Write soft lock table."""
    locks_file = env["home"] / "locks.json"
    locks_file.write_text(json.dumps(locks_data))


# ── Wrong file detection ─────────────────────────────────────────────────────


class TestWrongFileDetected:
    def test_detects_edit_on_another_agents_locked_file(self, drift_env):
        _write_agent(drift_env, "agent-alpha", "sess-a", ticket="T-0001")
        _write_agent(drift_env, "agent-bravo", "sess-b", ticket="T-0002")
        _write_locks(drift_env, {
            "/tmp/proj/src/auth.py": {
                "agent": "agent-bravo",
                "session_id": "sess-b",
                "ticket": "T-0002",
                "timestamp": "2026-04-15T10:00:00Z",
            }
        })

        result = check_drift(
            session_id="sess-a",
            tool_name="Edit",
            tool_input={"file_path": "/tmp/proj/src/auth.py"},
            config=DriftConfig(aggressiveness="strict"),
        )
        assert result is not None
        assert result["signal"] == SIGNAL_WRONG_FILE
        assert "agent-bravo" in result["message"]

    def test_no_signal_when_editing_own_locked_file(self, drift_env):
        _write_agent(drift_env, "agent-alpha", "sess-a", ticket="T-0001")
        _write_locks(drift_env, {
            "/tmp/proj/src/auth.py": {
                "agent": "agent-alpha",
                "session_id": "sess-a",
                "ticket": "T-0001",
                "timestamp": "2026-04-15T10:00:00Z",
            }
        })

        result = check_drift(
            session_id="sess-a",
            tool_name="Edit",
            tool_input={"file_path": "/tmp/proj/src/auth.py"},
            config=DriftConfig(aggressiveness="strict"),
        )
        assert result is None


# ── Off-ticket detection ─────────────────────────────────────────────────────


class TestOffTicketDetected:
    def test_detects_when_not_touching_ticket_files(self, drift_env):
        _write_agent(drift_env, "agent-alpha", "sess-a", ticket="T-0001")
        _write_ticket(drift_env, "T-0001", files=["src/auth.py"], claimed_by="agent-alpha")
        # Activity: 15 tool calls, none touching ticket files, but includes test runs
        # so skipping_tests doesn't fire first
        entries = []
        for i in range(15):
            entries.append({"ts": f"2026-04-15T10:{i:02d}:00Z", "tool": "Edit", "file": "/tmp/proj/src/other.py"})
            if i % 5 == 4:
                entries.append({"ts": f"2026-04-15T10:{i:02d}:30Z", "tool": "Bash", "command": "pytest", "is_test_run": True})
        _write_activity(drift_env, "sess-a", entries)

        result = check_drift(
            session_id="sess-a",
            tool_name="Edit",
            tool_input={"file_path": "/tmp/proj/src/other.py"},
            config=DriftConfig(aggressiveness="strict", min_interval_tool_calls=5),
        )
        assert result is not None
        assert result["signal"] == SIGNAL_OFF_TICKET

    def test_no_signal_when_touching_ticket_files(self, drift_env):
        _write_agent(drift_env, "agent-alpha", "sess-a", ticket="T-0001")
        _write_ticket(drift_env, "T-0001", files=["src/auth.py"], claimed_by="agent-alpha")
        entries = [
            {"ts": "2026-04-15T10:00:00Z", "tool": "Edit", "file": "/tmp/proj/src/auth.py"}
        ]
        _write_activity(drift_env, "sess-a", entries)

        result = check_drift(
            session_id="sess-a",
            tool_name="Edit",
            tool_input={"file_path": "/tmp/proj/src/auth.py"},
            config=DriftConfig(aggressiveness="strict"),
        )
        # Should not trigger off-ticket since we are touching ticket files
        assert result is None or result["signal"] != SIGNAL_OFF_TICKET


# ── Out-of-scope detection ───────────────────────────────────────────────────


class TestOutOfScopeFileDetected:
    def test_detects_file_outside_ticket_scope(self, drift_env):
        _write_agent(drift_env, "agent-alpha", "sess-a", ticket="T-0001")
        _write_ticket(drift_env, "T-0001", files=["src/auth.py"], claimed_by="agent-alpha")

        result = check_drift(
            session_id="sess-a",
            tool_name="Write",
            tool_input={"file_path": "/tmp/proj/docs/readme.md"},
            config=DriftConfig(aggressiveness="strict"),
        )
        assert result is not None
        assert result["signal"] == SIGNAL_OUT_OF_SCOPE


# ── Skipping tests detection ────────────────────────────────────────────────


class TestSkippingTestsDetected:
    def test_detects_many_edits_without_test_run(self, drift_env):
        _write_agent(drift_env, "agent-alpha", "sess-a", ticket="T-0001")
        # 12 file edits, no test runs
        entries = [
            {"ts": f"2026-04-15T10:{i:02d}:00Z", "tool": "Edit", "file": f"/tmp/proj/src/f{i}.py"}
            for i in range(12)
        ]
        _write_activity(drift_env, "sess-a", entries)

        result = check_drift(
            session_id="sess-a",
            tool_name="Edit",
            tool_input={"file_path": "/tmp/proj/src/f12.py"},
            config=DriftConfig(aggressiveness="strict", min_interval_tool_calls=5),
        )
        assert result is not None
        assert result["signal"] == SIGNAL_SKIPPING_TESTS

    def test_no_signal_when_tests_run_recently(self, drift_env):
        _write_agent(drift_env, "agent-alpha", "sess-a", ticket="T-0001")
        entries = [
            {"ts": "2026-04-15T10:00:00Z", "tool": "Edit", "file": "/tmp/proj/src/f1.py"},
            {"ts": "2026-04-15T10:01:00Z", "tool": "Bash", "command": "pytest tests/", "is_test_run": True},
            {"ts": "2026-04-15T10:02:00Z", "tool": "Edit", "file": "/tmp/proj/src/f2.py"},
        ]
        _write_activity(drift_env, "sess-a", entries)

        result = check_drift(
            session_id="sess-a",
            tool_name="Edit",
            tool_input={"file_path": "/tmp/proj/src/f3.py"},
            config=DriftConfig(aggressiveness="strict"),
        )
        assert result is None or result["signal"] != SIGNAL_SKIPPING_TESTS


# ── Rate limiting ────────────────────────────────────────────────────────────


class TestRateLimiting:
    def test_respects_interval(self, drift_env):
        _write_agent(drift_env, "agent-alpha", "sess-a", ticket="T-0001")
        _write_ticket(drift_env, "T-0001", files=["src/auth.py"], claimed_by="agent-alpha")
        entries = [
            {"ts": f"2026-04-15T10:{i:02d}:00Z", "tool": "Edit", "file": f"/tmp/proj/src/other{i}.py"}
            for i in range(15)
        ]
        _write_activity(drift_env, "sess-a", entries)

        config = DriftConfig(aggressiveness="strict", min_interval_tool_calls=10)

        # First check should return an injection
        result1 = check_drift(
            session_id="sess-a",
            tool_name="Edit",
            tool_input={"file_path": "/tmp/proj/src/other.py"},
            config=config,
        )
        assert result1 is not None

        # Immediate second check should be rate-limited (None)
        result2 = check_drift(
            session_id="sess-a",
            tool_name="Edit",
            tool_input={"file_path": "/tmp/proj/src/other.py"},
            config=config,
        )
        assert result2 is None


# ── Disabled / aggressiveness modes ──────────────────────────────────────────


class TestDisabledMode:
    def test_no_injection_when_disabled(self, drift_env):
        _write_agent(drift_env, "agent-alpha", "sess-a", ticket="T-0001")
        _write_agent(drift_env, "agent-bravo", "sess-b", ticket="T-0002")
        _write_locks(drift_env, {
            "/tmp/proj/src/auth.py": {
                "agent": "agent-bravo",
                "session_id": "sess-b",
                "ticket": "T-0002",
                "timestamp": "2026-04-15T10:00:00Z",
            }
        })

        result = check_drift(
            session_id="sess-a",
            tool_name="Edit",
            tool_input={"file_path": "/tmp/proj/src/auth.py"},
            config=DriftConfig(aggressiveness="off"),
        )
        assert result is None


class TestGentleMode:
    def test_only_wrong_file_and_tests(self, drift_env):
        """Gentle mode should only fire wrong_file and skipping_tests signals."""
        _write_agent(drift_env, "agent-alpha", "sess-a", ticket="T-0001")
        _write_ticket(drift_env, "T-0001", files=["src/auth.py"], claimed_by="agent-alpha")

        # Out-of-scope should NOT trigger in gentle mode
        result = check_drift(
            session_id="sess-a",
            tool_name="Write",
            tool_input={"file_path": "/tmp/proj/docs/readme.md"},
            config=DriftConfig(aggressiveness="gentle"),
        )
        assert result is None or result["signal"] not in (SIGNAL_OFF_TICKET, SIGNAL_OUT_OF_SCOPE, SIGNAL_TASK_STALL)


class TestStrictMode:
    def test_all_signals_enabled(self, drift_env):
        _write_agent(drift_env, "agent-alpha", "sess-a", ticket="T-0001")
        _write_ticket(drift_env, "T-0001", files=["src/auth.py"], claimed_by="agent-alpha")

        # Out-of-scope should trigger in strict mode
        result = check_drift(
            session_id="sess-a",
            tool_name="Write",
            tool_input={"file_path": "/tmp/proj/docs/readme.md"},
            config=DriftConfig(aggressiveness="strict"),
        )
        assert result is not None
        assert result["signal"] == SIGNAL_OUT_OF_SCOPE


# ── Injection logging ────────────────────────────────────────────────────────


class TestInjectionLogging:
    def test_injection_logged_to_jsonl(self, drift_env):
        _write_agent(drift_env, "agent-alpha", "sess-a", ticket="T-0001")
        _write_agent(drift_env, "agent-bravo", "sess-b", ticket="T-0002")
        _write_locks(drift_env, {
            "/tmp/proj/src/auth.py": {
                "agent": "agent-bravo",
                "session_id": "sess-b",
                "ticket": "T-0002",
                "timestamp": "2026-04-15T10:00:00Z",
            }
        })

        check_drift(
            session_id="sess-a",
            tool_name="Edit",
            tool_input={"file_path": "/tmp/proj/src/auth.py"},
            config=DriftConfig(aggressiveness="strict"),
        )

        log_file = drift_env["sessions"] / "sess-a" / "injections.jsonl"
        assert log_file.exists()
        entries = [json.loads(line) for line in log_file.read_text().strip().split("\n")]
        assert len(entries) >= 1
        assert entries[0]["signal"] == SIGNAL_WRONG_FILE


# ── Always allows ────────────────────────────────────────────────────────────


class TestInjectionAlwaysAllows:
    def test_injection_always_allows_action(self, drift_env):
        """Drift injections should never block — they use additionalContext, not deny."""
        _write_agent(drift_env, "agent-alpha", "sess-a", ticket="T-0001")
        _write_agent(drift_env, "agent-bravo", "sess-b", ticket="T-0002")
        _write_locks(drift_env, {
            "/tmp/proj/src/auth.py": {
                "agent": "agent-bravo",
                "session_id": "sess-b",
                "ticket": "T-0002",
                "timestamp": "2026-04-15T10:00:00Z",
            }
        })

        result = check_drift(
            session_id="sess-a",
            tool_name="Edit",
            tool_input={"file_path": "/tmp/proj/src/auth.py"},
            config=DriftConfig(aggressiveness="strict"),
        )
        assert result is not None
        # Should return context for injection, not a deny decision
        assert "message" in result
        assert result.get("decision", "allow") == "allow"


# ── No injection when on track ───────────────────────────────────────────────


class TestNoInjectionWhenOnTrack:
    def test_no_signal_when_agent_is_on_track(self, drift_env):
        _write_agent(drift_env, "agent-alpha", "sess-a", ticket="T-0001")
        _write_ticket(drift_env, "T-0001", files=["src/auth.py"], claimed_by="agent-alpha")
        entries = [
            {"ts": "2026-04-15T10:00:00Z", "tool": "Edit", "file": "/tmp/proj/src/auth.py"},
            {"ts": "2026-04-15T10:01:00Z", "tool": "Bash", "command": "pytest tests/", "is_test_run": True},
        ]
        _write_activity(drift_env, "sess-a", entries)

        result = check_drift(
            session_id="sess-a",
            tool_name="Edit",
            tool_input={"file_path": "/tmp/proj/src/auth.py"},
            config=DriftConfig(aggressiveness="strict"),
        )
        assert result is None
