"""Tests for PreToolUse hook handler — sensitive file protection."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def track_env(tmp_path):
    """Provide temp directories for pre-tool-use tests."""
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


def _run_hook(payload: dict, env: dict, cwd: Path | None = None):
    return subprocess.run(
        [sys.executable, "-m", "agent_track.cli", "hook", "pre-tool-use"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
    )


def _make_event(
    tool_name: str = "Write",
    file_path: str = "/tmp/src/app.py",
    session_id: str = "sess_pre_test",
) -> dict:
    tool_input = {"file_path": file_path}
    if tool_name == "Write":
        tool_input["content"] = "hello"
    elif tool_name == "Edit":
        tool_input["old_string"] = "a"
        tool_input["new_string"] = "b"
    elif tool_name == "Bash":
        tool_input = {"command": f"cat {file_path}"}
    return {
        "hook_event_name": "PreToolUse",
        "session_id": session_id,
        "cwd": "/tmp",
        "tool_name": tool_name,
        "tool_use_id": "toolu_01ABC",
        "tool_input": tool_input,
        "permission_mode": "default",
    }


class TestPreToolUse:
    def test_write_to_env_triggers_warning(self, track_env):
        tmp_path, track, home, env = track_env
        payload = _make_event("Write", "/tmp/project/.env")
        result = _run_hook(payload, env, tmp_path)
        # In warn mode (default), exits 0 but logs
        assert result.returncode == 0
        access_log = home / "security" / "access-log.jsonl"
        assert access_log.exists()
        entry = json.loads(access_log.read_text().strip())
        assert entry["file"] == "/tmp/project/.env"
        assert entry["action"] == "warn"

    def test_write_to_env_blocked_in_block_mode(self, track_env):
        tmp_path, track, home, env = track_env
        # Set block mode via config
        (track / "config.json").write_text(json.dumps({"sensitive_mode": "block"}))
        payload = _make_event("Write", "/tmp/project/.env")
        result = _run_hook(payload, env, tmp_path)
        assert result.returncode == 2

    def test_write_to_pem_triggers_warning(self, track_env):
        tmp_path, track, home, env = track_env
        payload = _make_event("Write", "/tmp/certs/server.pem")
        result = _run_hook(payload, env, tmp_path)
        assert result.returncode == 0
        access_log = home / "security" / "access-log.jsonl"
        assert access_log.exists()

    def test_read_of_env_triggers_warning(self, track_env):
        tmp_path, track, home, env = track_env
        payload = _make_event("Read", "/tmp/project/.env")
        result = _run_hook(payload, env, tmp_path)
        assert result.returncode == 0
        access_log = home / "security" / "access-log.jsonl"
        assert access_log.exists()

    def test_normal_file_passes_through(self, track_env):
        tmp_path, track, home, env = track_env
        payload = _make_event("Write", "/tmp/src/app.py")
        result = _run_hook(payload, env, tmp_path)
        assert result.returncode == 0
        access_log = home / "security" / "access-log.jsonl"
        # No access log entry for normal files
        assert not access_log.exists()

    def test_nested_env_path_detected(self, track_env):
        tmp_path, track, home, env = track_env
        payload = _make_event("Write", "/tmp/project/.env.production")
        result = _run_hook(payload, env, tmp_path)
        access_log = home / "security" / "access-log.jsonl"
        assert access_log.exists()

    def test_bash_cat_env_detected(self, track_env):
        tmp_path, track, home, env = track_env
        payload = _make_event("Bash", "/tmp/project/.env")
        # Bash event with command referencing .env
        payload["tool_input"] = {"command": "cat .env"}
        result = _run_hook(payload, env, tmp_path)
        access_log = home / "security" / "access-log.jsonl"
        assert access_log.exists()

    def test_access_log_entry_created(self, track_env):
        tmp_path, track, home, env = track_env
        payload = _make_event("Edit", "/tmp/secrets.yaml")
        result = _run_hook(payload, env, tmp_path)
        access_log = home / "security" / "access-log.jsonl"
        assert access_log.exists()
        entry = json.loads(access_log.read_text().strip())
        assert "ts" in entry
        assert entry["session_id"] == "sess_pre_test"
        assert entry["tool"] == "Edit"

    def test_block_mode_returns_exit_2(self, track_env):
        tmp_path, track, home, env = track_env
        (track / "config.json").write_text(json.dumps({"sensitive_mode": "block"}))
        payload = _make_event("Write", "/tmp/id_rsa")
        result = _run_hook(payload, env, tmp_path)
        assert result.returncode == 2

    def test_warn_mode_returns_exit_0(self, track_env):
        tmp_path, track, home, env = track_env
        (track / "config.json").write_text(json.dumps({"sensitive_mode": "warn"}))
        payload = _make_event("Write", "/tmp/id_rsa")
        result = _run_hook(payload, env, tmp_path)
        assert result.returncode == 0

    def test_missing_config_uses_defaults(self, track_env):
        """No config.json → default warn mode."""
        tmp_path, track, home, env = track_env
        payload = _make_event("Write", "/tmp/.env")
        result = _run_hook(payload, env, tmp_path)
        assert result.returncode == 0  # warn mode = exit 0
        access_log = home / "security" / "access-log.jsonl"
        assert access_log.exists()
