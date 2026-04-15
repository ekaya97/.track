"""Tests for the file watcher (track analyze --watch)."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_track.analysis.watcher import FileWatcher


class TestFileWatcher:
    def test_detects_new_file(self, tmp_path):
        """Watcher should detect newly created files."""
        watcher = FileWatcher(tmp_path)
        watcher.snapshot()

        # Create a new file
        (tmp_path / "new.py").write_text("x = 1\n")

        changes = watcher.poll()
        assert any(str(p).endswith("new.py") for p in changes["added"])

    def test_detects_modified_file(self, tmp_path):
        """Watcher should detect modified files."""
        f = tmp_path / "mod.py"
        f.write_text("x = 1\n")

        watcher = FileWatcher(tmp_path)
        watcher.snapshot()

        # Modify the file (ensure mtime changes)
        time.sleep(0.05)
        f.write_text("x = 2\n")

        changes = watcher.poll()
        assert any(str(p).endswith("mod.py") for p in changes["modified"])

    def test_detects_deleted_file(self, tmp_path):
        """Watcher should detect deleted files."""
        f = tmp_path / "gone.py"
        f.write_text("x = 1\n")

        watcher = FileWatcher(tmp_path)
        watcher.snapshot()

        f.unlink()

        changes = watcher.poll()
        assert any(str(p).endswith("gone.py") for p in changes["deleted"])

    def test_ignores_non_code_files(self, tmp_path):
        """Watcher should skip non-code files."""
        watcher = FileWatcher(tmp_path)
        watcher.snapshot()

        (tmp_path / "readme.md").write_text("# hi\n")
        (tmp_path / "data.json").write_text("{}\n")

        changes = watcher.poll()
        assert len(changes["added"]) == 0

    def test_no_changes_returns_empty(self, tmp_path):
        """Watcher returns empty sets when nothing changed."""
        (tmp_path / "stable.py").write_text("x = 1\n")
        watcher = FileWatcher(tmp_path)
        watcher.snapshot()

        changes = watcher.poll()
        assert len(changes["added"]) == 0
        assert len(changes["modified"]) == 0
        assert len(changes["deleted"]) == 0

    def test_debounce_prevents_rapid_triggers(self, tmp_path):
        """Debounce should coalesce rapid changes."""
        watcher = FileWatcher(tmp_path, debounce_ms=200)
        watcher.snapshot()

        (tmp_path / "a.py").write_text("x = 1\n")

        # First poll returns changes
        changes = watcher.poll()
        assert len(changes["added"]) == 1

        # Take a new snapshot
        watcher.snapshot()

        # Immediately poll again — no new changes
        changes = watcher.poll()
        assert len(changes["added"]) == 0

    def test_skips_default_dirs(self, tmp_path):
        """Watcher should skip .git, node_modules, etc."""
        watcher = FileWatcher(tmp_path)
        watcher.snapshot()

        nm = tmp_path / "node_modules" / "pkg"
        nm.mkdir(parents=True)
        (nm / "index.js").write_text("x = 1;\n")

        changes = watcher.poll()
        assert len(changes["added"]) == 0
