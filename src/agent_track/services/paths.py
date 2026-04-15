"""Path constants, configuration, and .track/ directory discovery."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# ── Project-local paths (git-tracked, shared across worktrees) ────────────────

TRACK_DIR: Path = Path(".track")
TICKETS_DIR: Path = TRACK_DIR / "tickets"
ARCHIVE_DIR: Path = TRACK_DIR / "archive"
BOARD_FILE: Path = TRACK_DIR / "BOARD.md"
CONVENTIONS_FILE: Path = TRACK_DIR / "CONVENTIONS.md"
CONFIG_FILE: Path = TRACK_DIR / "config.json"

# ── Ephemeral paths (per-machine, never committed) ───────────────────────────

HOME_DIR: Path = Path.home() / ".track"
PROJECT_HOME: Path = HOME_DIR / "projects"

# Per-project ephemeral state (resolved at runtime)
AGENTS_DIR: Path = HOME_DIR / "agents"
SESSIONS_DIR: Path = HOME_DIR / "sessions"
SECURITY_DIR: Path = HOME_DIR / "security"
LOCKS_DIR: Path = HOME_DIR / "locks"
LOCKS_FILE: Path = HOME_DIR / "locks.json"
SERVER_PID_FILE: Path = HOME_DIR / "locks" / "server.pid"

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


def _project_key(project_root: Path) -> str:
    """Derive a project key from the project root path.

    Converts /Users/eneskaya/Projects/myproject → -Users-eneskaya-Projects-myproject
    Same convention as ~/.claude/projects/.
    """
    return str(project_root).replace("/", "-").lstrip("-")


def _git_toplevel() -> Path | None:
    """Get the git repository root, resolving worktrees to the main repo."""
    try:
        # git rev-parse --show-toplevel returns the worktree root.
        # For the common dir (shared across worktrees), use --git-common-dir
        # and go up one level. But for our purpose — project identity — the
        # toplevel of the *main* worktree is what we want.
        result = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            git_common = Path(result.stdout.strip())
            # .git dir is at <project_root>/.git, so parent is project root
            # For worktrees, git-common-dir points to the main repo's .git
            if git_common.name == ".git":
                return git_common.parent
            # Bare repos or unusual layouts — fall back to toplevel
            result2 = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result2.returncode == 0:
                return Path(result2.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


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


def _resolve_project_home(track_dir: Path) -> Path:
    """Resolve the ephemeral home directory for this project.

    Uses git toplevel for worktree-safe identity, falls back to
    the parent of .track/.
    """
    env_home = os.environ.get("TRACK_HOME")
    if env_home:
        return Path(env_home).resolve()

    project_root = _git_toplevel() or track_dir.parent
    key = _project_key(project_root)
    home = Path.home() / ".track" / "projects" / key
    return home


def _set_paths(track_dir: Path) -> None:
    """Set all module-level path variables from a given .track/ root."""
    global TRACK_DIR, TICKETS_DIR, ARCHIVE_DIR
    global BOARD_FILE, CONVENTIONS_FILE, CONFIG_FILE
    global HOME_DIR, PROJECT_HOME
    global AGENTS_DIR, SESSIONS_DIR, SECURITY_DIR
    global LOCKS_DIR, LOCKS_FILE, SERVER_PID_FILE

    # Project-local (git-tracked)
    TRACK_DIR = track_dir
    TICKETS_DIR = TRACK_DIR / "tickets"
    ARCHIVE_DIR = TRACK_DIR / "archive"
    BOARD_FILE = TRACK_DIR / "BOARD.md"
    CONVENTIONS_FILE = TRACK_DIR / "CONVENTIONS.md"
    CONFIG_FILE = TRACK_DIR / "config.json"

    # Ephemeral (per-machine, in ~/.track/projects/{key}/)
    PROJECT_HOME = _resolve_project_home(track_dir)
    AGENTS_DIR = PROJECT_HOME / "agents"
    SESSIONS_DIR = PROJECT_HOME / "sessions"
    SECURITY_DIR = PROJECT_HOME / "security"
    LOCKS_DIR = PROJECT_HOME / "locks"
    LOCKS_FILE = PROJECT_HOME / "locks.json"
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
