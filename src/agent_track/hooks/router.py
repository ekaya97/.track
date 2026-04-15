"""Hook subcommand router — reads JSON from stdin, dispatches to handlers."""

from __future__ import annotations

import json
import sys


def _read_stdin() -> dict | None:
    """Read and parse JSON from stdin. Returns None on failure."""
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return None
        return json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return None


def cmd_hook_session_start(_args) -> None:
    """Handle SessionStart hook event."""
    event = _read_stdin()
    if not event or not event.get("session_id"):
        return
    from agent_track.hooks.session_start import handle_session_start

    handle_session_start(event)


def cmd_hook_post_tool_use(_args) -> None:
    """Handle PostToolUse / PostToolUseFailure hook event."""
    event = _read_stdin()
    if not event or not event.get("session_id"):
        return
    from agent_track.hooks.post_tool_use import handle_post_tool_use

    handle_post_tool_use(event)


def cmd_hook_pre_tool_use(_args) -> None:
    """Handle PreToolUse hook event."""
    event = _read_stdin()
    if not event or not event.get("session_id"):
        return
    from agent_track.hooks.pre_tool_use import handle_pre_tool_use

    handle_pre_tool_use(event)


def cmd_hook_session_end(_args) -> None:
    """Handle SessionEnd hook event."""
    event = _read_stdin()
    if not event or not event.get("session_id"):
        return
    from agent_track.hooks.session_end import handle_session_end

    handle_session_end(event)
