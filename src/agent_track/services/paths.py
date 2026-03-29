"""Path constants, configuration, and .track/ directory discovery."""

from __future__ import annotations

import os
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────

TRACK_DIR: Path = Path(".track")
TICKETS_DIR: Path = TRACK_DIR / "tickets"
AGENTS_DIR: Path = TRACK_DIR / "agents"
LOCKS_DIR: Path = TRACK_DIR / "locks"
ARCHIVE_DIR: Path = TRACK_DIR / "archive"
BOARD_FILE: Path = TRACK_DIR / "BOARD.md"
CONVENTIONS_FILE: Path = TRACK_DIR / "CONVENTIONS.md"
SERVER_PID_FILE: Path = LOCKS_DIR / "server.pid"

# ── Configuration ──────────────────────────────────────────────────────────────

STATUSES = ["backlog", "claimed", "in-progress", "review", "done"]
PRIORITIES = ["critical", "high", "medium", "low"]
HEARTBEAT_STALE_MINUTES = 30
DEFAULT_PORT = 7777

NATO = [
    "alpha",
    "bravo",
    "charlie",
    "delta",
    "echo",
    "foxtrot",
    "golf",
    "hotel",
    "india",
    "juliet",
    "kilo",
    "lima",
    "mike",
    "november",
    "oscar",
    "papa",
    "quebec",
    "romeo",
    "sierra",
    "tango",
    "uniform",
    "victor",
    "whiskey",
    "xray",
    "yankee",
    "zulu",
]


# ── Discovery ──────────────────────────────────────────────────────────────────


def _find_track_dir() -> Path:
    """Discover an existing .track/ directory.

    Resolution order:
    1. TRACK_DIR environment variable (absolute path)
    2. Walk up from CWD looking for a .track/ directory
    3. Fall back to CWD/.track
    """
    env = os.environ.get("TRACK_DIR")
    if env:
        return Path(env).resolve()

    current = Path.cwd().resolve()
    while True:
        candidate = current / ".track"
        if candidate.is_dir():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent

    return Path.cwd().resolve() / ".track"


def _set_paths(track_dir: Path) -> None:
    """Set all module-level path variables from a given .track/ root."""
    global TRACK_DIR, TICKETS_DIR, AGENTS_DIR, LOCKS_DIR, ARCHIVE_DIR
    global BOARD_FILE, CONVENTIONS_FILE, SERVER_PID_FILE

    TRACK_DIR = track_dir
    TICKETS_DIR = TRACK_DIR / "tickets"
    AGENTS_DIR = TRACK_DIR / "agents"
    LOCKS_DIR = TRACK_DIR / "locks"
    ARCHIVE_DIR = TRACK_DIR / "archive"
    BOARD_FILE = TRACK_DIR / "BOARD.md"
    CONVENTIONS_FILE = TRACK_DIR / "CONVENTIONS.md"
    SERVER_PID_FILE = LOCKS_DIR / "server.pid"


def resolve_paths(use_cwd: bool = False) -> None:
    """Set module-level path variables.

    Args:
        use_cwd: If True, use CWD/.track (for `track init`) instead of
                 walking up to find an existing .track/ directory.
                 The TRACK_DIR env var always takes priority regardless.
    """
    env = os.environ.get("TRACK_DIR")
    if env:
        _set_paths(Path(env).resolve())
    elif use_cwd:
        _set_paths(Path.cwd().resolve() / ".track")
    else:
        _set_paths(_find_track_dir())
