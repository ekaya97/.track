"""Tests for ticket generation from analysis findings."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_track.analysis.ticket_gen import (
    generate_tickets_from_findings,
    tickets_from_duplicates,
    tickets_from_coverage,
    tickets_from_security,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def dup_findings():
    """Sample duplicates analysis result."""
    return {
        "generated_at": "2026-04-15T10:00:00Z",
        "clusters": [
            {
                "hash": "abc123",
                "type": "exact",
                "functions": [
                    {"file": "src/auth.py", "name": "validate_token", "line_start": 45, "line_end": 60, "lines": 16},
                    {"file": "src/api.py", "name": "check_token", "line_start": 112, "line_end": 127, "lines": 16},
                    {"file": "src/middleware.py", "name": "verify_token", "line_start": 23, "line_end": 38, "lines": 16},
                ],
                "suggested_action": "Extract to shared utility function",
            }
        ],
        "stats": {"functions_analyzed": 50, "exact_clusters": 1, "near_clusters": 0, "total_duplicate_lines": 48},
    }


@pytest.fixture
def coverage_findings():
    """Sample coverage analysis result."""
    return {
        "generated_at": "2026-04-15T10:00:00Z",
        "coverage": {
            "files_with_tests": 5,
            "files_without_tests": 2,
            "functions_with_tests": 20,
            "functions_without_tests": 3,
            "test_files": 5,
            "coverage_ratio": 0.71,
        },
        "untested_functions": [
            {"file": "src/auth.py", "name": "refresh_token", "line_start": 45, "line_end": 72},
            {"file": "src/api.py", "name": "handle_upload", "line_start": 10, "line_end": 25},
        ],
        "untested_files": [
            {"file": "src/config.py", "functions": ["load_config", "validate_config"]},
        ],
        "suspicious_tests": [],
    }


@pytest.fixture
def security_findings():
    """Sample security analysis result."""
    return {
        "generated_at": "2026-04-15T10:00:00Z",
        "findings": [
            {
                "type": "hardcoded_secret",
                "severity": "high",
                "file": "src/config.py",
                "line": 15,
                "pattern": "AKIA prefix (AWS key)",
                "snippet": 'AWS_KEY = "AKIA..."',
            },
            {
                "type": "dangerous_pattern",
                "severity": "medium",
                "file": "src/db.py",
                "line": 42,
                "pattern": "SQL string with variable interpolation",
                "snippet": 'f"SELECT * FROM users WHERE id={uid}"',
            },
        ],
        "stats": {"files_scanned": 10, "findings_high": 1, "findings_medium": 1, "findings_low": 0},
    }


@pytest.fixture
def track_env(tmp_path, monkeypatch):
    """Set up a minimal .track/ environment for ticket creation."""
    track_dir = tmp_path / ".track"
    track_dir.mkdir()
    (track_dir / "tickets").mkdir()
    (track_dir / "archive").mkdir()
    board = track_dir / "BOARD.md"
    board.write_text("# .track Board\n\n<!-- New messages are prepended below this line -->\n")

    monkeypatch.setattr("agent_track.services.paths.TRACK_DIR", track_dir)
    monkeypatch.setattr("agent_track.services.paths.TICKETS_DIR", track_dir / "tickets")
    monkeypatch.setattr("agent_track.services.paths.ARCHIVE_DIR", track_dir / "archive")
    monkeypatch.setattr("agent_track.services.paths.BOARD_FILE", board)
    monkeypatch.setattr("agent_track.services.paths.ANALYSIS_DIR", track_dir / "analysis")

    # Ephemeral dirs for locks
    home = tmp_path / "home"
    home.mkdir()
    locks = home / "locks"
    locks.mkdir()
    monkeypatch.setattr("agent_track.services.paths.PROJECT_HOME", home)
    monkeypatch.setattr("agent_track.services.paths.LOCKS_DIR", locks)

    return track_dir


# ── Duplicate finding → ticket ───────────────────────────────────────────────


class TestDuplicateFindingGeneratesTicket:
    def test_generates_ticket_for_exact_cluster(self, dup_findings):
        tickets = tickets_from_duplicates(dup_findings)
        assert len(tickets) == 1

    def test_ticket_title_includes_function_name(self, dup_findings):
        tickets = tickets_from_duplicates(dup_findings)
        assert "validate_token" in tickets[0]["title"] or "check_token" in tickets[0]["title"]

    def test_ticket_title_includes_copy_count(self, dup_findings):
        tickets = tickets_from_duplicates(dup_findings)
        assert "3" in tickets[0]["title"]

    def test_ticket_has_dedup_label(self, dup_findings):
        tickets = tickets_from_duplicates(dup_findings)
        assert "dedup" in tickets[0]["labels"]
        assert "auto-generated" in tickets[0]["labels"]

    def test_ticket_priority_medium(self, dup_findings):
        tickets = tickets_from_duplicates(dup_findings)
        assert tickets[0]["priority"] == "medium"

    def test_ticket_references_all_files(self, dup_findings):
        tickets = tickets_from_duplicates(dup_findings)
        files = tickets[0]["files"]
        assert "src/auth.py" in files
        assert "src/api.py" in files
        assert "src/middleware.py" in files

    def test_ticket_body_has_acceptance_criteria(self, dup_findings):
        tickets = tickets_from_duplicates(dup_findings)
        assert "Acceptance Criteria" in tickets[0]["body"]

    def test_ticket_body_has_suggested_fix(self, dup_findings):
        tickets = tickets_from_duplicates(dup_findings)
        assert "Suggested fix" in tickets[0]["body"] or "suggested" in tickets[0]["body"].lower()

    def test_ticket_body_lists_all_functions(self, dup_findings):
        tickets = tickets_from_duplicates(dup_findings)
        body = tickets[0]["body"]
        assert "src/auth.py" in body
        assert "validate_token" in body
        assert "src/api.py" in body
        assert "check_token" in body


# ── Coverage finding → ticket ────────────────────────────────────────────────


class TestCoverageFindingGeneratesTicket:
    def test_generates_tickets_for_untested_functions(self, coverage_findings):
        tickets = tickets_from_coverage(coverage_findings)
        assert len(tickets) >= 2  # one per untested function

    def test_ticket_title_includes_function_name(self, coverage_findings):
        tickets = tickets_from_coverage(coverage_findings)
        titles = [t["title"] for t in tickets]
        assert any("refresh_token" in t for t in titles)

    def test_ticket_has_testing_label(self, coverage_findings):
        tickets = tickets_from_coverage(coverage_findings)
        for t in tickets:
            assert "testing" in t["labels"]
            assert "auto-generated" in t["labels"]

    def test_ticket_priority_low(self, coverage_findings):
        tickets = tickets_from_coverage(coverage_findings)
        for t in tickets:
            assert t["priority"] == "low"

    def test_ticket_references_source_file(self, coverage_findings):
        tickets = tickets_from_coverage(coverage_findings)
        auth_ticket = [t for t in tickets if "refresh_token" in t["title"]][0]
        assert "src/auth.py" in auth_ticket["files"]

    def test_ticket_body_has_acceptance_criteria(self, coverage_findings):
        tickets = tickets_from_coverage(coverage_findings)
        for t in tickets:
            assert "Acceptance Criteria" in t["body"]


# ── Security finding → ticket ────────────────────────────────────────────────


class TestSecurityFindingGeneratesTicket:
    def test_generates_tickets_for_findings(self, security_findings):
        tickets = tickets_from_security(security_findings)
        assert len(tickets) >= 1

    def test_high_severity_gets_critical_priority(self, security_findings):
        tickets = tickets_from_security(security_findings)
        high_tickets = [t for t in tickets if "hardcoded" in t["title"].lower() or "AWS" in t["title"]]
        assert any(t["priority"] == "critical" for t in high_tickets)

    def test_medium_severity_gets_high_priority(self, security_findings):
        tickets = tickets_from_security(security_findings)
        medium_tickets = [t for t in tickets if "SQL" in t["title"]]
        assert any(t["priority"] == "high" for t in medium_tickets)

    def test_ticket_has_security_label(self, security_findings):
        tickets = tickets_from_security(security_findings)
        for t in tickets:
            assert "security" in t["labels"]
            assert "auto-generated" in t["labels"]

    def test_ticket_references_file(self, security_findings):
        tickets = tickets_from_security(security_findings)
        config_tickets = [t for t in tickets if "src/config.py" in t["files"]]
        assert len(config_tickets) >= 1

    def test_ticket_body_has_acceptance_criteria(self, security_findings):
        tickets = tickets_from_security(security_findings)
        for t in tickets:
            assert "Acceptance Criteria" in t["body"]

    def test_ticket_body_has_snippet(self, security_findings):
        tickets = tickets_from_security(security_findings)
        # At least one ticket should reference the pattern
        bodies = " ".join(t["body"] for t in tickets)
        assert "AKIA" in bodies or "AWS" in bodies


# ── Dry run ──────────────────────────────────────────────────────────────────


class TestDryRun:
    def test_dry_run_does_not_create_tickets(self, track_env, dup_findings, coverage_findings, security_findings):
        results = generate_tickets_from_findings(
            duplicates=dup_findings,
            coverage=coverage_findings,
            security=security_findings,
            dry_run=True,
        )
        # Should return ticket dicts but not write files
        assert len(results) > 0
        tickets_dir = track_env / "tickets"
        assert len(list(tickets_dir.glob("T-*.md"))) == 0


# ── Deduplication (no duplicate tickets) ─────────────────────────────────────


class TestDuplicateTicketNotCreatedTwice:
    def test_skips_if_equivalent_ticket_exists(self, track_env, dup_findings):
        """Creating tickets twice should not duplicate them."""
        results1 = generate_tickets_from_findings(
            duplicates=dup_findings,
            dry_run=False,
        )
        results2 = generate_tickets_from_findings(
            duplicates=dup_findings,
            dry_run=False,
        )
        # Second run should create 0 new tickets
        assert len(results2) == 0

    def test_first_run_creates_tickets(self, track_env, dup_findings):
        results = generate_tickets_from_findings(
            duplicates=dup_findings,
            dry_run=False,
        )
        assert len(results) >= 1


# ── Full generate_tickets_from_findings ──────────────────────────────────────


class TestGenerateTicketsFromFindings:
    def test_generates_from_all_types(self, track_env, dup_findings, coverage_findings, security_findings):
        results = generate_tickets_from_findings(
            duplicates=dup_findings,
            coverage=coverage_findings,
            security=security_findings,
            dry_run=True,
        )
        labels = set()
        for t in results:
            labels.update(t["labels"])
        assert "dedup" in labels
        assert "testing" in labels
        assert "security" in labels

    def test_generates_only_specified_type(self, track_env, dup_findings):
        results = generate_tickets_from_findings(
            duplicates=dup_findings,
            dry_run=True,
        )
        for t in results:
            assert "dedup" in t["labels"]

    def test_creates_ticket_files_when_not_dry_run(self, track_env, dup_findings):
        results = generate_tickets_from_findings(
            duplicates=dup_findings,
            dry_run=False,
        )
        tickets_dir = track_env / "tickets"
        md_files = list(tickets_dir.glob("T-*.md"))
        assert len(md_files) == len(results)

    def test_created_tickets_have_backlog_status(self, track_env, dup_findings):
        results = generate_tickets_from_findings(
            duplicates=dup_findings,
            dry_run=False,
        )
        from agent_track.services.frontmatter import parse_frontmatter
        tickets_dir = track_env / "tickets"
        for f in tickets_dir.glob("T-*.md"):
            meta, _ = parse_frontmatter(f.read_text())
            assert meta["status"] == "backlog"

    def test_created_tickets_have_track_analyze_creator(self, track_env, dup_findings):
        results = generate_tickets_from_findings(
            duplicates=dup_findings,
            dry_run=False,
        )
        from agent_track.services.frontmatter import parse_frontmatter
        tickets_dir = track_env / "tickets"
        for f in tickets_dir.glob("T-*.md"):
            meta, _ = parse_frontmatter(f.read_text())
            assert meta["created_by"] == "track-analyze"
