"""Tests for agent terminal launch functionality."""

from __future__ import annotations

import os
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from agent_track.launch import (
    build_launch_command,
    launch_agent,
    PLATFORM_MACOS,
    PLATFORM_LINUX,
)


class TestBuildLaunchCommand:
    def test_macos_generates_osascript(self):
        cmd, args = build_launch_command(
            ticket_id="T-0001",
            project_dir="/tmp/myproject",
            platform=PLATFORM_MACOS,
        )
        assert cmd == "osascript"
        # The args should contain an AppleScript that references the ticket
        script = " ".join(args)
        assert "T-0001" in script
        assert "/tmp/myproject" in script

    def test_macos_script_contains_claude_invocation(self):
        cmd, args = build_launch_command(
            ticket_id="T-0001",
            project_dir="/tmp/myproject",
            platform=PLATFORM_MACOS,
        )
        script = " ".join(args)
        assert "claude" in script.lower()

    def test_linux_uses_track_terminal_env(self):
        cmd, args = build_launch_command(
            ticket_id="T-0001",
            project_dir="/tmp/myproject",
            platform=PLATFORM_LINUX,
            terminal="kitty",
        )
        assert cmd == "kitty"

    def test_linux_defaults_to_gnome_terminal(self):
        cmd, args = build_launch_command(
            ticket_id="T-0001",
            project_dir="/tmp/myproject",
            platform=PLATFORM_LINUX,
        )
        assert cmd == "gnome-terminal"

    def test_linux_command_contains_ticket_id(self):
        cmd, args = build_launch_command(
            ticket_id="T-0042",
            project_dir="/tmp/proj",
            platform=PLATFORM_LINUX,
        )
        full = " ".join(args)
        assert "T-0042" in full

    def test_macos_iterm_support(self):
        cmd, args = build_launch_command(
            ticket_id="T-0001",
            project_dir="/tmp/proj",
            platform=PLATFORM_MACOS,
            terminal="iterm",
        )
        assert cmd == "osascript"
        script = " ".join(args)
        assert "iTerm" in script


class TestLaunchAgent:
    @patch("agent_track.launch.subprocess.Popen")
    def test_launch_calls_subprocess(self, mock_popen):
        mock_popen.return_value = MagicMock(pid=12345)
        pid = launch_agent(
            ticket_id="T-0001",
            project_dir="/tmp/proj",
            platform=PLATFORM_LINUX,
        )
        assert mock_popen.called
        assert pid == 12345

    @patch("agent_track.launch.subprocess.Popen")
    def test_launch_returns_pid(self, mock_popen):
        mock_popen.return_value = MagicMock(pid=99)
        pid = launch_agent(
            ticket_id="T-0005",
            project_dir="/tmp/proj",
            platform=PLATFORM_LINUX,
        )
        assert pid == 99


class TestLaunchAPI:
    """Tests for the /api/launch endpoint integration."""

    @pytest.fixture
    def track_env(self, tmp_path, monkeypatch):
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

        home = tmp_path / "home"
        home.mkdir()
        (home / "locks").mkdir()
        (home / "agents").mkdir()
        monkeypatch.setattr("agent_track.services.paths.PROJECT_HOME", home)
        monkeypatch.setattr("agent_track.services.paths.LOCKS_DIR", home / "locks")
        monkeypatch.setattr("agent_track.services.paths.AGENTS_DIR", home / "agents")

        # Create a ticket to launch against
        from agent_track.services.models import write_ticket
        meta = {
            "id": "T-0001",
            "title": "Test ticket",
            "status": "backlog",
            "priority": "medium",
            "created": "2026-04-15T10:00:00Z",
            "created_by": "human",
            "claimed_by": None,
            "claimed_at": None,
            "labels": [],
            "branch": None,
            "files": [],
            "depends_on": [],
        }
        write_ticket(meta, "## Description\n\nTest.\n", track_dir / "tickets" / "T-0001.md")
        return track_dir

    def test_launch_api_returns_ticket_id(self, track_env):
        from agent_track.launch import handle_launch_request

        with patch("agent_track.launch.launch_agent", return_value=12345):
            result = handle_launch_request(
                ticket_id="T-0001",
                project_dir=str(track_env.parent),
            )
        assert result["ticket_id"] == "T-0001"
        assert result["pid"] == 12345

    def test_launch_api_returns_error_for_missing_ticket(self, track_env):
        from agent_track.launch import handle_launch_request

        result = handle_launch_request(
            ticket_id="T-9999",
            project_dir=str(track_env.parent),
        )
        assert "error" in result
