"""PreToolUse hook handler — sensitive file protection."""

from __future__ import annotations

import json
import re
import sys
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

from agent_track.services import paths
from agent_track.services.utils import now_iso

# Default sensitive file patterns
DEFAULT_SENSITIVE_PATTERNS = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "**/credentials.json",
    "**/service-account*.json",
    "**/.ssh/*",
    "**/id_rsa*",
    "**/id_ed25519*",
    "**/secrets.*",
    "**/*secret*",
    "**/.aws/credentials",
    "**/.netrc",
]

# Patterns to detect sensitive file references in bash commands
_BASH_SENSITIVE_RE = re.compile(
    r"(?:^|\s)(?:cat|head|tail|less|more|cp|mv|echo\s+.*?>|source|\.)\s+"
    r"[\"']?([^\s\"'|;>&]+)"
)


def _load_config() -> dict:
    """Load track config, defaulting to warn mode."""
    if paths.CONFIG_FILE.exists():
        try:
            return json.loads(paths.CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _is_sensitive(file_path: str, patterns: list[str] | None = None) -> bool:
    """Check if a file path matches any sensitive pattern."""
    if patterns is None:
        patterns = DEFAULT_SENSITIVE_PATTERNS

    name = PurePosixPath(file_path).name
    for pattern in patterns:
        # Match against filename
        if fnmatch(name, pattern):
            return True
        # Match against full path
        if fnmatch(file_path, pattern):
            return True
    return False


def _extract_sensitive_from_bash(command: str) -> str | None:
    """Extract a sensitive file reference from a bash command, if any."""
    # Check if the command string itself contains a sensitive filename
    for match in _BASH_SENSITIVE_RE.finditer(command):
        candidate = match.group(1)
        if _is_sensitive(candidate):
            return candidate

    # Simple check: does the command mention any sensitive-looking filename?
    words = re.split(r'[\s|;&]+', command)
    for word in words:
        word = word.strip("\"'")
        if word and _is_sensitive(word):
            return word
    return None


def _log_access(
    session_id: str,
    tool: str,
    file_path: str,
    action: str,
) -> None:
    """Append an entry to the security access log."""
    paths.SECURITY_DIR.mkdir(parents=True, exist_ok=True)
    log_file = paths.SECURITY_DIR / "access-log.jsonl"
    entry = {
        "ts": now_iso(),
        "session_id": session_id,
        "tool": tool,
        "file": file_path,
        "action": action,
    }
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def handle_pre_tool_use(event: dict) -> None:
    """Handle a PreToolUse event. Check for sensitive file access."""
    session_id = event.get("session_id", "")
    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input", {})

    config = _load_config()
    mode = config.get("sensitive_mode", "warn")

    # Determine the file path to check
    sensitive_file: str | None = None

    if tool_name in ("Write", "Edit", "Read"):
        file_path = tool_input.get("file_path", "")
        if file_path and _is_sensitive(file_path):
            sensitive_file = file_path
    elif tool_name == "Bash":
        command = tool_input.get("command", "")
        sensitive_file = _extract_sensitive_from_bash(command)

    if not sensitive_file:
        return  # Not a sensitive file — pass through

    # Log the access
    action = mode  # "warn" or "block"
    _log_access(session_id, tool_name, sensitive_file, action)

    if mode == "block":
        # Output deny decision and exit 2
        response = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f".track: Access to {sensitive_file} blocked by "
                    f"sensitive file protection"
                ),
            }
        }
        print(json.dumps(response), file=sys.stdout)
        sys.exit(2)
    # warn mode — just log, exit 0 (handled by returning normally)
