"""CLI smoke tests using subprocess."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def track_dir(tmp_path):
    """Provide a temp directory with TRACK_DIR and TRACK_HOME set."""
    env = os.environ.copy()
    env["TRACK_DIR"] = str(tmp_path / ".track")
    env["TRACK_HOME"] = str(tmp_path / ".track-home")
    return tmp_path, env


def _run(
    args: list[str], env: dict, cwd: Path | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "agent_track.cli", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
    )


class TestCLISmoke:
    def test_version(self, track_dir):
        _, env = track_dir
        result = _run(["--version"], env)
        assert result.returncode == 0
        assert "0.1.0" in result.stdout

    def test_init(self, track_dir):
        tmp_path, env = track_dir
        result = _run(["init"], env)
        assert result.returncode == 0
        assert "Initialized" in result.stdout
        track = tmp_path / ".track"
        assert (track / "tickets").is_dir()
        assert (track / "BOARD.md").exists()
        assert (track / "CONVENTIONS.md").exists()
        # Agents dir is in ephemeral home
        assert "Ephemeral state:" in result.stdout

    def test_create_and_list(self, track_dir):
        tmp_path, env = track_dir
        _run(["init"], env)
        result = _run(["create", "--title", "Test ticket", "--priority", "high"], env)
        assert result.returncode == 0
        assert "T-0001" in result.stdout

        result = _run(["list"], env)
        assert result.returncode == 0
        assert "Test ticket" in result.stdout

    def test_register_and_claim(self, track_dir):
        tmp_path, env = track_dir
        _run(["init"], env)
        _run(["create", "--title", "A ticket"], env)

        result = _run(["register", "--agent", "agent-alpha"], env)
        assert result.returncode == 0
        assert "agent-alpha" in result.stdout

        result = _run(["claim", "T-0001", "--agent", "agent-alpha"], env)
        assert result.returncode == 0
        assert "Claimed" in result.stdout

    def test_update_status(self, track_dir):
        tmp_path, env = track_dir
        _run(["init"], env)
        _run(["create", "--title", "Status test"], env)
        _run(["register", "--agent", "agent-alpha"], env)
        _run(["claim", "T-0001", "--agent", "agent-alpha"], env)

        result = _run(
            ["update", "T-0001", "--status", "in-progress", "--agent", "agent-alpha"],
            env,
        )
        assert result.returncode == 0
        assert "Updated" in result.stdout

    def test_log_and_show(self, track_dir):
        tmp_path, env = track_dir
        _run(["init"], env)
        _run(["create", "--title", "Log test"], env)
        _run(["register", "--agent", "agent-alpha"], env)
        _run(["claim", "T-0001", "--agent", "agent-alpha"], env)

        result = _run(
            ["log", "T-0001", "--agent", "agent-alpha", "-m", "Progress note"], env
        )
        assert result.returncode == 0

        result = _run(["show", "T-0001"], env)
        assert result.returncode == 0
        assert "Progress note" in result.stdout

    def test_board_post_and_read(self, track_dir):
        tmp_path, env = track_dir
        _run(["init"], env)
        _run(["register", "--agent", "agent-alpha"], env)

        result = _run(["board", "--agent", "agent-alpha", "-m", "Hello board"], env)
        assert result.returncode == 0

        result = _run(["board", "--last", "5"], env)
        assert result.returncode == 0
        assert "Hello board" in result.stdout

    def test_heartbeat(self, track_dir):
        tmp_path, env = track_dir
        _run(["init"], env)
        _run(["register", "--agent", "agent-alpha"], env)

        result = _run(["heartbeat", "--agent", "agent-alpha"], env)
        assert result.returncode == 0
        assert "Heartbeat" in result.stdout

    def test_deregister(self, track_dir):
        tmp_path, env = track_dir
        _run(["init"], env)
        _run(["register", "--agent", "agent-alpha"], env)

        result = _run(["deregister", "--agent", "agent-alpha"], env)
        assert result.returncode == 0
        assert "Deregistered" in result.stdout

    def test_stale_no_agents(self, track_dir):
        tmp_path, env = track_dir
        _run(["init"], env)
        result = _run(["stale"], env)
        assert result.returncode == 0
        assert "No stale agents" in result.stdout

    def test_walkup_discovery(self, track_dir):
        """Test that track finds .track/ when run from a subdirectory."""
        tmp_path, env = track_dir
        # Remove the TRACK_DIR override so walk-up discovery kicks in
        env.pop("TRACK_DIR", None)

        # Create .track/ in tmp_path
        def run_direct(cmd_args):
            return subprocess.run(
                [sys.executable, "-m", "agent_track.cli", *cmd_args],
                capture_output=True,
                text=True,
                env=env,
                cwd=tmp_path,
            )

        run_direct(["init"])
        run_direct(["create", "--title", "Walk-up test"])

        # Run from a nested subdirectory
        nested = tmp_path / "sub" / "deep"
        nested.mkdir(parents=True)
        result = subprocess.run(
            [sys.executable, "-m", "agent_track.cli", "list"],
            capture_output=True,
            text=True,
            env=env,
            cwd=nested,
        )
        assert result.returncode == 0
        assert "Walk-up test" in result.stdout
