"""Tests for track init updates — hooks.json generation, new dirs."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def track_env(tmp_path):
    """Provide a temp directory for init tests."""
    env = os.environ.copy()
    env["TRACK_DIR"] = str(tmp_path / ".track")
    env["TRACK_HOME"] = str(tmp_path / ".track-home")
    return tmp_path, env


def _run(args: list[str], env: dict, cwd: Path | None = None):
    return subprocess.run(
        [sys.executable, "-m", "agent_track.cli", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
    )


class TestInitHooks:
    def test_init_creates_ephemeral_dirs(self, track_env):
        tmp_path, env = track_env
        _run(["init"], env)
        home = tmp_path / ".track-home"
        assert (home / "agents").is_dir()
        assert (home / "sessions").is_dir()
        assert (home / "security").is_dir()
        assert (home / "locks").is_dir()

    def test_init_generates_hooks_json(self, track_env):
        tmp_path, env = track_env
        _run(["init"], env)
        hooks_file = tmp_path / ".track" / "hooks.json"
        assert hooks_file.exists()
        hooks = json.loads(hooks_file.read_text())
        assert "hooks" in hooks
        # Should have our four hook types
        hook_keys = set(hooks["hooks"].keys())
        assert "SessionStart" in hook_keys
        assert "PreToolUse" in hook_keys
        assert "PostToolUse" in hook_keys
        assert "SessionEnd" in hook_keys

    def test_init_hooks_json_has_correct_commands(self, track_env):
        tmp_path, env = track_env
        _run(["init"], env)
        hooks = json.loads((tmp_path / ".track" / "hooks.json").read_text())
        # Check commands reference track hook subcommands
        for key, entries in hooks["hooks"].items():
            for entry in entries:
                for hook in entry["hooks"]:
                    assert "track hook" in hook["command"]

    def test_init_does_not_overwrite_existing_hooks_json(self, track_env):
        tmp_path, env = track_env
        _run(["init"], env)
        hooks_file = tmp_path / ".track" / "hooks.json"

        # Modify hooks.json
        custom = {"hooks": {"custom": [{"command": "my-hook"}]}}
        hooks_file.write_text(json.dumps(custom))

        # Re-init
        _run(["init"], env)

        # Should NOT overwrite
        hooks = json.loads(hooks_file.read_text())
        assert "custom" in hooks["hooks"]

    def test_init_writes_default_config(self, track_env):
        tmp_path, env = track_env
        _run(["init"], env)
        config_file = tmp_path / ".track" / "config.json"
        assert config_file.exists()
        config = json.loads(config_file.read_text())
        assert config["sensitive_mode"] == "warn"

    def test_init_idempotent(self, track_env):
        tmp_path, env = track_env
        _run(["init"], env)
        result = _run(["init"], env)
        assert result.returncode == 0
        assert "Initialized" in result.stdout
