"""File watcher for incremental analysis (track analyze --watch)."""

from __future__ import annotations

import time
from pathlib import Path

from agent_track.analysis import walk_project


class FileWatcher:
    """Polls for file changes in a project directory.

    Uses mtime-based change detection with configurable debounce.
    """

    def __init__(self, root: Path, debounce_ms: int = 500) -> None:
        self.root = root.resolve()
        self.debounce_ms = debounce_ms
        self._snapshot: dict[Path, float] = {}
        self._last_poll: float = 0.0

    def snapshot(self) -> None:
        """Take a snapshot of current file mtimes."""
        self._snapshot = {}
        for f in walk_project(self.root):
            try:
                self._snapshot[f] = f.stat().st_mtime
            except OSError:
                pass
        self._last_poll = time.monotonic()

    def poll(self) -> dict[str, list[Path]]:
        """Check for changes since last snapshot.

        Returns dict with 'added', 'modified', 'deleted' lists.
        """
        current: dict[Path, float] = {}
        for f in walk_project(self.root):
            try:
                current[f] = f.stat().st_mtime
            except OSError:
                pass

        added: list[Path] = []
        modified: list[Path] = []
        deleted: list[Path] = []

        # New or modified files
        for f, mtime in current.items():
            if f not in self._snapshot:
                added.append(f)
            elif mtime != self._snapshot[f]:
                modified.append(f)

        # Deleted files
        for f in self._snapshot:
            if f not in current:
                deleted.append(f)

        return {"added": added, "modified": modified, "deleted": deleted}

    def has_changes(self) -> bool:
        """Quick check if anything changed since last snapshot."""
        changes = self.poll()
        return bool(changes["added"] or changes["modified"] or changes["deleted"])


def watch_and_analyze(root: Path, callback: callable, debounce_ms: int = 500) -> None:
    """Watch a project directory and call callback on changes.

    This is the main loop for `track analyze --watch`. It polls for changes,
    debounces rapid modifications, and re-runs analysis incrementally.

    Args:
        root: Project root directory.
        callback: Called with (added, modified, deleted) file lists.
        debounce_ms: Minimum time between analysis runs.
    """
    watcher = FileWatcher(root, debounce_ms=debounce_ms)
    watcher.snapshot()

    print(f"Watching {root} for changes (Ctrl+C to stop)...")

    try:
        while True:
            time.sleep(debounce_ms / 1000.0)
            changes = watcher.poll()
            if changes["added"] or changes["modified"] or changes["deleted"]:
                callback(changes["added"], changes["modified"], changes["deleted"])
                watcher.snapshot()
    except KeyboardInterrupt:
        print("\nStopped watching.")
