"""Utility functions: timestamps, atomic writes, file locking."""

from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from agent_track.services import paths


def now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def atomic_write(path: Path, content: str) -> None:
    """Write content to a file atomically via rename."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.rename(path)


class ConcurrentAccessError(Exception):
    """Raised when a non-blocking lock cannot be acquired."""

    pass


@contextmanager
def file_lock(lock_name: str, blocking: bool = True):
    """Context manager for fcntl-based file locking."""
    paths.LOCKS_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = paths.LOCKS_DIR / lock_name
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    try:
        flags = fcntl.LOCK_EX
        if not blocking:
            flags |= fcntl.LOCK_NB
        try:
            fcntl.flock(fd, flags)
        except BlockingIOError:
            os.close(fd)
            raise ConcurrentAccessError(
                f"Lock '{lock_name}' is held by another process. Try again."
            )
        yield fd
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception:
            pass
        os.close(fd)
