"""Code analysis: directory walking, language detection, and graph building."""

from __future__ import annotations

import fnmatch
from pathlib import Path

# File extensions → language mapping
EXTENSION_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
}

# Directories always skipped during walking
SKIP_DIRS: set[str] = {
    ".track",
    ".git",
    "node_modules",
    "__pycache__",
    "venv",
    ".venv",
}


def detect_language(path: Path) -> str | None:
    """Detect programming language by file extension. Returns None if unknown."""
    return EXTENSION_MAP.get(path.suffix.lower())


def _parse_gitignore(gitignore_path: Path) -> list[str]:
    """Parse a .gitignore file and return a list of patterns."""
    if not gitignore_path.is_file():
        return []
    patterns = []
    for line in gitignore_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
    return patterns


def _is_ignored(
    rel_path: Path,
    is_dir: bool,
    gitignore_patterns: list[tuple[Path, list[str]]],
) -> bool:
    """Check if a relative path matches any gitignore pattern.

    gitignore_patterns is a list of (scope_dir, patterns) tuples where
    scope_dir is relative to the project root.
    """
    rel_str = str(rel_path)
    # For directories, also test with trailing slash
    rel_str_dir = rel_str + "/" if is_dir else rel_str

    for scope_dir, patterns in gitignore_patterns:
        # The path must be under the scope dir for the patterns to apply
        scope_str = str(scope_dir)
        if scope_str == ".":
            scoped_path = rel_str
            scoped_path_dir = rel_str_dir
        elif rel_str.startswith(scope_str + "/"):
            scoped_path = rel_str[len(scope_str) + 1 :]
            scoped_path_dir = rel_str_dir[len(scope_str) + 1 :]
        else:
            continue

        for pattern in patterns:
            # Directory-only patterns (trailing slash)
            if pattern.endswith("/"):
                pat = pattern.rstrip("/")
                if is_dir and (
                    fnmatch.fnmatch(scoped_path, pat)
                    or fnmatch.fnmatch(rel_path.name, pat)
                ):
                    return True
                continue

            # Match against full scoped path and also just the filename
            if fnmatch.fnmatch(scoped_path, pattern):
                return True
            if fnmatch.fnmatch(scoped_path_dir, pattern):
                return True
            if fnmatch.fnmatch(rel_path.name, pattern):
                return True

    return False


def walk_project(root: Path) -> list[Path]:
    """Walk a project directory, returning sorted code files.

    Respects .gitignore rules and skips default directories like
    .git/, node_modules/, __pycache__/, etc.

    Only returns files with recognized code extensions.
    """
    root = root.resolve()
    result: list[Path] = []

    # Collect gitignore patterns: list of (scope_relative_dir, patterns)
    gitignore_patterns: list[tuple[Path, list[str]]] = []

    # Parse root .gitignore
    root_patterns = _parse_gitignore(root / ".gitignore")
    if root_patterns:
        gitignore_patterns.append((Path("."), root_patterns))

    def _walk(directory: Path) -> None:
        try:
            entries = sorted(directory.iterdir(), key=lambda p: p.name)
        except PermissionError:
            return

        for entry in entries:
            rel = entry.relative_to(root)

            if entry.is_dir():
                # Skip hardcoded dirs
                if entry.name in SKIP_DIRS:
                    continue
                # Skip gitignored dirs
                if _is_ignored(rel, is_dir=True, gitignore_patterns=gitignore_patterns):
                    continue
                # Check for nested .gitignore
                nested_gi = entry / ".gitignore"
                nested_patterns = _parse_gitignore(nested_gi)
                if nested_patterns:
                    gitignore_patterns.append((rel, nested_patterns))
                _walk(entry)
            elif entry.is_file():
                # Skip gitignored files
                if _is_ignored(rel, is_dir=False, gitignore_patterns=gitignore_patterns):
                    continue
                # Only include recognized code files
                if detect_language(entry) is not None:
                    result.append(entry)

    _walk(root)
    result.sort(key=lambda p: str(p.relative_to(root)))
    return result
