"""Tests for ticket, agent, and board I/O."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_track.services import paths
from agent_track.services.models import (
    all_agents,
    all_tickets,
    next_ticket_id,
    parse_board_entries,
    post_to_board,
    read_agent,
    read_ticket,
    write_agent,
    write_ticket,
)


@pytest.fixture(autouse=True)
def track_env(tmp_path, monkeypatch):
    """Set up a temporary .track/ directory for every test."""
    track_dir = tmp_path / ".track"
    monkeypatch.setattr(paths, "TRACK_DIR", track_dir)
    monkeypatch.setattr(paths, "TICKETS_DIR", track_dir / "tickets")
    monkeypatch.setattr(paths, "AGENTS_DIR", track_dir / "agents")
    monkeypatch.setattr(paths, "LOCKS_DIR", track_dir / "locks")
    monkeypatch.setattr(paths, "ARCHIVE_DIR", track_dir / "archive")
    monkeypatch.setattr(paths, "BOARD_FILE", track_dir / "BOARD.md")
    monkeypatch.setattr(paths, "CONVENTIONS_FILE", track_dir / "CONVENTIONS.md")
    monkeypatch.setattr(paths, "SERVER_PID_FILE", track_dir / "locks" / "server.pid")
    for d in [
        track_dir,
        track_dir / "tickets",
        track_dir / "agents",
        track_dir / "locks",
        track_dir / "archive",
    ]:
        d.mkdir(parents=True, exist_ok=True)
    return track_dir


def _create_ticket(
    ticket_id: str = "T-0001", title: str = "Test ticket", status: str = "backlog"
) -> Path:
    meta = {
        "id": ticket_id,
        "title": title,
        "status": status,
        "priority": "medium",
        "created": "2026-01-01T00:00:00Z",
        "created_by": "human",
        "claimed_by": None,
        "claimed_at": None,
        "labels": [],
        "branch": None,
        "files": [],
        "depends_on": [],
    }
    body = "## Description\n\nTest."
    path = paths.TICKETS_DIR / f"{ticket_id}.md"
    write_ticket(meta, body, path)
    return path


class TestTicketIO:
    def test_write_and_read(self):
        _create_ticket()
        meta, body, path = read_ticket("T-0001")
        assert meta["id"] == "T-0001"
        assert meta["title"] == "Test ticket"
        assert "## Description" in body

    def test_read_missing_ticket(self):
        with pytest.raises(SystemExit):
            read_ticket("T-9999")

    def test_all_tickets(self):
        _create_ticket("T-0001")
        _create_ticket("T-0002", title="Second ticket")
        tickets = all_tickets()
        assert len(tickets) == 2

    def test_next_ticket_id_empty(self):
        assert next_ticket_id() == "T-0001"

    def test_next_ticket_id_increments(self):
        _create_ticket("T-0003")
        assert next_ticket_id() == "T-0004"


class TestAgentIO:
    def test_write_and_read(self):
        data = {
            "id": "agent-alpha",
            "registered_at": "2026-01-01T00:00:00Z",
            "last_heartbeat": "2026-01-01T00:00:00Z",
            "status": "active",
            "current_ticket": None,
            "capabilities": ["python"],
            "session_id": None,
            "worktree": None,
            "files_modified": [],
            "history": [],
        }
        write_agent(data)
        loaded = read_agent("agent-alpha")
        assert loaded["id"] == "agent-alpha"
        assert loaded["capabilities"] == ["python"]

    def test_read_missing_agent(self):
        with pytest.raises(SystemExit):
            read_agent("agent-nonexistent")

    def test_all_agents(self):
        for name in ["alpha", "bravo"]:
            write_agent({"id": f"agent-{name}", "status": "active"})
        agents = all_agents()
        assert len(agents) == 2


class TestBoardIO:
    def test_post_and_parse(self):
        post_to_board("agent-alpha", "T-0001", "note", "Hello from the board")
        entries = parse_board_entries()
        assert len(entries) == 1
        assert entries[0]["agent"] == "agent-alpha"
        assert entries[0]["ticket"] == "T-0001"
        assert entries[0]["message"] == "Hello from the board"

    def test_multiple_posts(self):
        post_to_board("agent-alpha", "T-0001", "note", "First message")
        post_to_board("agent-bravo", "T-0002", "claimed", "Claiming T-0002")
        entries = parse_board_entries()
        assert len(entries) == 2

    def test_empty_board(self):
        entries = parse_board_entries()
        assert entries == []

    def test_board_limit(self):
        for i in range(5):
            post_to_board("agent-alpha", "T-0001", "note", f"Message {i}")
        entries = parse_board_entries(limit=3)
        assert len(entries) == 3
