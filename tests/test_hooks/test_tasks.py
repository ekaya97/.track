"""Tests for task capture and ticket directory migration."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent_track.services import paths
from agent_track.services.models import read_ticket, write_ticket, all_tickets, next_ticket_id


# ── Ticket directory migration tests (unit) ──────────────────────────────────


@pytest.fixture
def track_unit(tmp_path, monkeypatch):
    """Set up temp dirs with monkeypatch for unit tests."""
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


def _write_flat_ticket(track_dir: Path, ticket_id: str = "T-0001", title: str = "Test"):
    """Write a flat ticket file (old format) directly."""
    content = f"""---
id: {ticket_id}
title: {title}
status: backlog
priority: medium
created: 2026-04-15T10:00:00Z
created_by: human
claimed_by: null
claimed_at: null
labels: []
branch: null
files: []
depends_on: []
---

## Description

Test ticket.

## Work Log
"""
    (track_dir / "tickets" / f"{ticket_id}.md").write_text(content, encoding="utf-8")


class TestTicketDirectoryMigration:
    def test_read_flat_ticket_still_works(self, track_unit):
        """Flat ticket files (old format) should still be readable."""
        track_dir, _ = track_unit
        _write_flat_ticket(track_dir)
        meta, body, path = read_ticket("T-0001")
        assert meta["id"] == "T-0001"
        assert meta["title"] == "Test"

    def test_read_directory_ticket(self, track_unit):
        """Directory-format tickets should be readable."""
        track_dir, _ = track_unit
        ticket_dir = track_dir / "tickets" / "T-0001"
        ticket_dir.mkdir()
        content = """---
id: T-0001
title: Dir ticket
status: backlog
priority: medium
created: 2026-04-15T10:00:00Z
created_by: human
claimed_by: null
claimed_at: null
labels: []
branch: null
files: []
depends_on: []
---

## Description

Directory format ticket.
"""
        (ticket_dir / "ticket.md").write_text(content, encoding="utf-8")
        meta, body, path = read_ticket("T-0001")
        assert meta["id"] == "T-0001"
        assert meta["title"] == "Dir ticket"
        assert path == ticket_dir / "ticket.md"

    def test_all_tickets_finds_both_formats(self, track_unit):
        """all_tickets should find both flat files and directory tickets."""
        track_dir, _ = track_unit
        # Flat ticket
        _write_flat_ticket(track_dir, "T-0001", "Flat")
        # Directory ticket
        ticket_dir = track_dir / "tickets" / "T-0002"
        ticket_dir.mkdir()
        content = """---
id: T-0002
title: Directory
status: backlog
priority: medium
created: 2026-04-15T10:00:00Z
created_by: human
claimed_by: null
claimed_at: null
labels: []
branch: null
files: []
depends_on: []
---

## Description

Dir ticket.
"""
        (ticket_dir / "ticket.md").write_text(content, encoding="utf-8")

        tickets = all_tickets()
        ids = [m["id"] for m, _, _ in tickets]
        assert "T-0001" in ids
        assert "T-0002" in ids

    def test_next_ticket_id_counts_both_formats(self, track_unit):
        track_dir, _ = track_unit
        _write_flat_ticket(track_dir, "T-0002", "Flat")
        ticket_dir = track_dir / "tickets" / "T-0005"
        ticket_dir.mkdir()
        (ticket_dir / "ticket.md").write_text("---\nid: T-0005\ntitle: X\nstatus: backlog\npriority: medium\ncreated: 2026-04-15T10:00:00Z\ncreated_by: human\n---\n\nBody")
        assert next_ticket_id() == "T-0006"

    def test_migrate_flat_to_directory(self, track_unit):
        """migrate_ticket should convert flat file to directory format."""
        track_dir, _ = track_unit
        from agent_track.services.models import migrate_ticket_to_dir
        _write_flat_ticket(track_dir, "T-0001", "Migrate me")

        result = migrate_ticket_to_dir("T-0001")
        assert result.is_dir()
        assert (result / "ticket.md").exists()
        assert not (track_dir / "tickets" / "T-0001.md").exists()
        # Tasks dir should be created
        assert (result / "tasks").is_dir()

    def test_migration_preserves_ticket_content(self, track_unit):
        track_dir, _ = track_unit
        from agent_track.services.models import migrate_ticket_to_dir
        _write_flat_ticket(track_dir, "T-0001", "Preserve me")

        migrate_ticket_to_dir("T-0001")
        meta, body, path = read_ticket("T-0001")
        assert meta["title"] == "Preserve me"
        assert "## Description" in body

    def test_migration_idempotent(self, track_unit):
        """Migrating an already-directory ticket should be a no-op."""
        track_dir, _ = track_unit
        from agent_track.services.models import migrate_ticket_to_dir

        # Create directory ticket directly
        ticket_dir = track_dir / "tickets" / "T-0001"
        ticket_dir.mkdir()
        (ticket_dir / "ticket.md").write_text("---\nid: T-0001\ntitle: Already dir\nstatus: backlog\npriority: medium\ncreated: 2026-04-15T10:00:00Z\ncreated_by: human\n---\n\nBody")
        (ticket_dir / "tasks").mkdir()

        result = migrate_ticket_to_dir("T-0001")
        assert result == ticket_dir
        meta, _, _ = read_ticket("T-0001")
        assert meta["title"] == "Already dir"


# ── Task capture tests (integration via subprocess) ──────────────────────────


@pytest.fixture
def track_integration(tmp_path):
    """Provide temp dirs with a pre-registered agent and a ticket."""
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

    sid = "sess_task_test"
    agent = {
        "id": "agent-alpha",
        "session_id": sid,
        "registered_at": "2026-04-15T10:00:00Z",
        "last_heartbeat": "2026-04-15T10:00:00Z",
        "status": "active",
        "current_ticket": "T-0001",
        "capabilities": [],
        "files_touched": [],
        "history": [],
    }
    (home / "agents" / f"{sid}.json").write_text(json.dumps(agent))
    (home / "sessions" / sid).mkdir()

    # Create a ticket (directory format)
    ticket_dir = track / "tickets" / "T-0001"
    ticket_dir.mkdir()
    (ticket_dir / "tasks").mkdir()
    (ticket_dir / "ticket.md").write_text(
        "---\nid: T-0001\ntitle: Test ticket\nstatus: in-progress\npriority: medium\n"
        "created: 2026-04-15T10:00:00Z\ncreated_by: human\nclaimed_by: agent-alpha\n"
        "claimed_at: 2026-04-15T10:05:00Z\nlabels: []\nbranch: null\nfiles: []\ndepends_on: []\n"
        "---\n\n## Description\n\nTest.\n"
    )

    env = os.environ.copy()
    env["TRACK_DIR"] = str(track)
    env["TRACK_HOME"] = str(home)
    return tmp_path, track, home, env, sid


def _run_hook(subcommand: str, payload: dict, env: dict, cwd: Path | None = None):
    return subprocess.run(
        [sys.executable, "-m", "agent_track.cli", "hook", subcommand],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
    )


class TestTaskCapture:
    def test_task_created_writes_task_file(self, track_integration):
        tmp_path, track, home, env, sid = track_integration
        payload = {
            "hook_event_name": "TaskCreated",
            "session_id": sid,
            "cwd": str(tmp_path),
            "task_id": "task-001",
            "task_subject": "Implement auth refresh",
            "task_description": "Add token refresh logic",
            "permission_mode": "default",
        }
        result = _run_hook("post-tool-use", payload, env, tmp_path)
        assert result.returncode == 0

        # Task should be written under the ticket's tasks dir
        task_file = track / "tickets" / "T-0001" / "tasks" / "task-001.json"
        assert task_file.exists()
        task = json.loads(task_file.read_text())
        assert task["subject"] == "Implement auth refresh"
        assert task["status"] == "pending"

    def test_task_created_without_ticket_writes_to_session(self, track_integration):
        tmp_path, track, home, env, sid = track_integration
        # Remove current_ticket from agent
        agent_file = home / "agents" / f"{sid}.json"
        data = json.loads(agent_file.read_text())
        data["current_ticket"] = None
        agent_file.write_text(json.dumps(data))

        payload = {
            "hook_event_name": "TaskCreated",
            "session_id": sid,
            "cwd": str(tmp_path),
            "task_id": "task-orphan",
            "task_subject": "Orphan task",
            "task_description": "No ticket associated",
            "permission_mode": "default",
        }
        _run_hook("post-tool-use", payload, env, tmp_path)

        # Should be in session dir
        task_file = home / "sessions" / sid / "tasks" / "task-orphan.json"
        assert task_file.exists()

    def test_task_completed_updates_status(self, track_integration):
        tmp_path, track, home, env, sid = track_integration
        # First create a task
        task_dir = track / "tickets" / "T-0001" / "tasks"
        task = {
            "task_id": "task-001",
            "subject": "Do the thing",
            "status": "pending",
            "created_at": "2026-04-15T10:30:00Z",
            "session_id": sid,
            "agent": "agent-alpha",
        }
        (task_dir / "task-001.json").write_text(json.dumps(task))

        # Complete it
        payload = {
            "hook_event_name": "TaskCompleted",
            "session_id": sid,
            "cwd": str(tmp_path),
            "task_id": "task-001",
            "task_subject": "Do the thing",
            "permission_mode": "default",
        }
        _run_hook("post-tool-use", payload, env, tmp_path)

        updated = json.loads((task_dir / "task-001.json").read_text())
        assert updated["status"] == "completed"
        assert "completed_at" in updated
