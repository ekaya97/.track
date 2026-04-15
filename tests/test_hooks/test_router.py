"""Tests for hook subcommand router — stdin parsing and dispatch."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def track_env(tmp_path):
    """Provide temp project-local and ephemeral directories with env configured."""
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
    env = os.environ.copy()
    env["TRACK_DIR"] = str(track)
    env["TRACK_HOME"] = str(home)
    return tmp_path, track, home, env


def _run_hook(
    subcommand: str, stdin_data: str, env: dict, cwd: Path | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "agent_track.cli", "hook", subcommand],
        input=stdin_data,
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
    )


class TestHookRouter:
    def test_session_start_reads_stdin_and_dispatches(self, track_env):
        tmp_path, track, home, env = track_env
        payload = json.dumps({
            "hook_event_name": "SessionStart",
            "session_id": "sess_test_001",
            "cwd": str(tmp_path),
            "source": "startup",
            "model": "claude-sonnet-4-6",
            "transcript_path": "/tmp/transcript.jsonl",
            "permission_mode": "default",
        })
        result = _run_hook("session-start", payload, env, tmp_path)
        assert result.returncode == 0

    def test_post_tool_use_reads_stdin_and_dispatches(self, track_env):
        tmp_path, track, home, env = track_env
        # Pre-register an agent so post-tool-use has something to update
        agent = {
            "id": "agent-alpha",
            "session_id": "sess_test_002",
            "registered_at": "2026-04-15T10:00:00Z",
            "last_heartbeat": "2026-04-15T10:00:00Z",
            "status": "active",
            "current_ticket": None,
            "capabilities": [],
            "files_touched": [],
            "history": [],
        }
        (home / "agents" / "sess_test_002.json").write_text(json.dumps(agent))
        (home / "sessions" / "sess_test_002").mkdir()

        payload = json.dumps({
            "hook_event_name": "PostToolUse",
            "session_id": "sess_test_002",
            "cwd": str(tmp_path),
            "tool_name": "Read",
            "tool_use_id": "toolu_01ABC",
            "tool_input": {"file_path": "/tmp/foo.py"},
            "tool_response": {"success": True},
            "permission_mode": "default",
        })
        result = _run_hook("post-tool-use", payload, env, tmp_path)
        assert result.returncode == 0

    def test_pre_tool_use_reads_stdin_and_dispatches(self, track_env):
        tmp_path, track, home, env = track_env
        payload = json.dumps({
            "hook_event_name": "PreToolUse",
            "session_id": "sess_test_003",
            "cwd": str(tmp_path),
            "tool_name": "Write",
            "tool_use_id": "toolu_01DEF",
            "tool_input": {"file_path": "/tmp/foo.py", "content": "hello"},
            "permission_mode": "default",
        })
        result = _run_hook("pre-tool-use", payload, env, tmp_path)
        assert result.returncode == 0

    def test_session_end_reads_stdin_and_dispatches(self, track_env):
        tmp_path, track, home, env = track_env
        payload = json.dumps({
            "hook_event_name": "SessionEnd",
            "session_id": "sess_test_004",
            "cwd": str(tmp_path),
            "source": "prompt_input_exit",
            "transcript_path": "/tmp/transcript.jsonl",
            "permission_mode": "default",
        })
        result = _run_hook("session-end", payload, env, tmp_path)
        assert result.returncode == 0

    def test_invalid_json_exits_zero(self, track_env):
        """Hook must never crash the agent — invalid input exits cleanly."""
        _, _, _, env = track_env
        result = _run_hook("session-start", "not valid json{{{", env)
        assert result.returncode == 0

    def test_empty_stdin_exits_zero(self, track_env):
        _, _, _, env = track_env
        result = _run_hook("session-start", "", env)
        assert result.returncode == 0

    def test_missing_session_id_exits_zero(self, track_env):
        _, _, _, env = track_env
        payload = json.dumps({"hook_event_name": "SessionStart", "cwd": "/tmp"})
        result = _run_hook("session-start", payload, env)
        assert result.returncode == 0

    def test_hook_subcommand_exists(self, track_env):
        """Verify `track hook` is a valid subcommand group."""
        _, _, _, env = track_env
        result = subprocess.run(
            [sys.executable, "-m", "agent_track.cli", "hook", "--help"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0
        assert "session-start" in result.stdout
        assert "post-tool-use" in result.stdout
        assert "pre-tool-use" in result.stdout
        assert "session-end" in result.stdout
