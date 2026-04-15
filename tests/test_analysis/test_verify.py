"""Tests for post-completion verification of ticket work."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_track.analysis.verify import (
    capture_pre_analysis,
    run_verification,
    VerificationResult,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def verify_env(tmp_path, monkeypatch):
    """Set up .track/ with ticket directories for verification."""
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

    monkeypatch.setattr("agent_track.services.paths.TRACK_DIR", track_dir)
    monkeypatch.setattr("agent_track.services.paths.TICKETS_DIR", tickets_dir)
    monkeypatch.setattr("agent_track.services.paths.ARCHIVE_DIR", track_dir / "archive")
    monkeypatch.setattr("agent_track.services.paths.ANALYSIS_DIR", analysis_dir)
    monkeypatch.setattr("agent_track.services.paths.BOARD_FILE", board)
    monkeypatch.setattr("agent_track.services.paths.PROJECT_HOME", home)
    monkeypatch.setattr("agent_track.services.paths.LOCKS_DIR", home / "locks")

    return {"track_dir": track_dir, "tickets_dir": tickets_dir, "analysis_dir": analysis_dir}


def _write_ticket_dir(env, ticket_id, labels=None, files=None):
    """Create a ticket in directory format for verification artifacts."""
    from agent_track.services.models import write_ticket
    ticket_dir = env["tickets_dir"] / ticket_id
    ticket_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "id": ticket_id,
        "title": f"Test ticket {ticket_id}",
        "status": "claimed",
        "priority": "medium",
        "created": "2026-04-15T10:00:00Z",
        "created_by": "human",
        "claimed_by": "agent-alpha",
        "claimed_at": "2026-04-15T10:00:00Z",
        "labels": labels or [],
        "branch": None,
        "files": files or [],
        "depends_on": [],
    }
    write_ticket(meta, "## Description\n\nTest.\n", ticket_dir / "ticket.md")
    return ticket_dir


def _write_analysis(env, dup_clusters=0, untested_funcs=0, security_findings=0):
    """Write analysis JSON files with controlled counts."""
    analysis_dir = env["analysis_dir"]

    dup = {
        "generated_at": "2026-04-15T10:00:00Z",
        "clusters": [
            {
                "hash": f"hash{i}",
                "type": "exact",
                "functions": [
                    {"file": "src/auth.py", "name": f"func{i}", "line_start": i * 10, "line_end": i * 10 + 5, "lines": 6},
                    {"file": "src/api.py", "name": f"func{i}", "line_start": i * 10, "line_end": i * 10 + 5, "lines": 6},
                ],
                "suggested_action": "Extract",
            }
            for i in range(dup_clusters)
        ],
        "stats": {"functions_analyzed": 50, "exact_clusters": dup_clusters, "near_clusters": 0, "total_duplicate_lines": dup_clusters * 12},
    }
    (analysis_dir / "duplicates.json").write_text(json.dumps(dup))

    cov = {
        "generated_at": "2026-04-15T10:00:00Z",
        "coverage": {"files_with_tests": 5, "files_without_tests": 2, "functions_with_tests": 20, "functions_without_tests": untested_funcs, "test_files": 5, "coverage_ratio": 0.7},
        "untested_functions": [
            {"file": "src/auth.py", "name": f"untested_{i}", "line_start": i * 10, "line_end": i * 10 + 5}
            for i in range(untested_funcs)
        ],
        "untested_files": [],
        "suspicious_tests": [],
    }
    (analysis_dir / "test-coverage.json").write_text(json.dumps(cov))

    sec = {
        "generated_at": "2026-04-15T10:00:00Z",
        "findings": [
            {
                "type": "hardcoded_secret",
                "severity": "high",
                "file": "src/config.py",
                "line": 15 + i,
                "pattern": "AKIA prefix",
                "snippet": f"KEY{i} = 'AKIA...'",
            }
            for i in range(security_findings)
        ],
        "stats": {"files_scanned": 10, "findings_high": security_findings, "findings_medium": 0, "findings_low": 0},
    }
    (analysis_dir / "security.json").write_text(json.dumps(sec))


# ── Pre-analysis capture ─────────────────────────────────────────────────────


class TestPreAnalysisCapturedOnClaim:
    def test_captures_snapshot(self, verify_env):
        ticket_dir = _write_ticket_dir(verify_env, "T-0001", labels=["dedup"])
        _write_analysis(verify_env, dup_clusters=2)

        capture_pre_analysis("T-0001")

        pre_file = ticket_dir / "pre-analysis.json"
        assert pre_file.exists()
        data = json.loads(pre_file.read_text())
        assert "duplicates" in data or "coverage" in data or "security" in data

    def test_captures_relevant_analysis_for_dedup(self, verify_env):
        ticket_dir = _write_ticket_dir(verify_env, "T-0001", labels=["dedup"])
        _write_analysis(verify_env, dup_clusters=3)

        capture_pre_analysis("T-0001")

        data = json.loads((ticket_dir / "pre-analysis.json").read_text())
        assert data["duplicates"]["stats"]["exact_clusters"] == 3


# ── Post-analysis and verification ───────────────────────────────────────────


class TestPostAnalysisRunsOnDone:
    def test_runs_verification(self, verify_env):
        ticket_dir = _write_ticket_dir(verify_env, "T-0001", labels=["dedup"])
        _write_analysis(verify_env, dup_clusters=2)
        capture_pre_analysis("T-0001")

        # Simulate fix: now 0 clusters
        _write_analysis(verify_env, dup_clusters=0)

        result = run_verification("T-0001")
        assert result is not None
        assert result.ticket_id == "T-0001"


class TestVerificationPass:
    def test_pass_when_fixed(self, verify_env):
        ticket_dir = _write_ticket_dir(verify_env, "T-0001", labels=["dedup"])
        _write_analysis(verify_env, dup_clusters=2)
        capture_pre_analysis("T-0001")

        _write_analysis(verify_env, dup_clusters=0)
        result = run_verification("T-0001")
        assert result.result == "pass"


class TestVerificationFail:
    def test_fail_when_not_fixed(self, verify_env):
        ticket_dir = _write_ticket_dir(verify_env, "T-0001", labels=["dedup"])
        _write_analysis(verify_env, dup_clusters=2)
        capture_pre_analysis("T-0001")

        # Same clusters remain
        result = run_verification("T-0001")
        assert result.result == "fail"


class TestVerificationPartial:
    def test_partial_when_partially_fixed(self, verify_env):
        ticket_dir = _write_ticket_dir(verify_env, "T-0001", labels=["dedup"])
        _write_analysis(verify_env, dup_clusters=3)
        capture_pre_analysis("T-0001")

        _write_analysis(verify_env, dup_clusters=1)
        result = run_verification("T-0001")
        assert result.result == "partial"


class TestFollowUpTicket:
    def test_suggests_follow_up_on_fail(self, verify_env):
        ticket_dir = _write_ticket_dir(verify_env, "T-0001", labels=["dedup"])
        _write_analysis(verify_env, dup_clusters=2)
        capture_pre_analysis("T-0001")

        result = run_verification("T-0001")
        assert result.follow_up_needed is True


class TestVerificationResultWritten:
    def test_writes_to_ticket_dir(self, verify_env):
        ticket_dir = _write_ticket_dir(verify_env, "T-0001", labels=["dedup"])
        _write_analysis(verify_env, dup_clusters=2)
        capture_pre_analysis("T-0001")

        _write_analysis(verify_env, dup_clusters=0)
        run_verification("T-0001")

        verify_file = ticket_dir / "verification.json"
        assert verify_file.exists()
        data = json.loads(verify_file.read_text())
        assert data["result"] == "pass"
        assert data["ticket_id"] == "T-0001"


class TestVerificationWithCoverage:
    def test_coverage_pass(self, verify_env):
        _write_ticket_dir(verify_env, "T-0002", labels=["testing"])
        _write_analysis(verify_env, untested_funcs=3)
        capture_pre_analysis("T-0002")

        _write_analysis(verify_env, untested_funcs=0)
        result = run_verification("T-0002")
        assert result.result == "pass"


class TestVerificationWithSecurity:
    def test_security_pass(self, verify_env):
        _write_ticket_dir(verify_env, "T-0003", labels=["security"])
        _write_analysis(verify_env, security_findings=2)
        capture_pre_analysis("T-0003")

        _write_analysis(verify_env, security_findings=0)
        result = run_verification("T-0003")
        assert result.result == "pass"
