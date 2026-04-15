"""Terminal spawning for agent launch — open a new terminal with Claude Code for a ticket."""

from __future__ import annotations

import os
import subprocess
import sys

PLATFORM_MACOS = "macos"
PLATFORM_LINUX = "linux"


def _detect_platform() -> str:
    """Detect the current platform."""
    if sys.platform == "darwin":
        return PLATFORM_MACOS
    return PLATFORM_LINUX


def _claude_prompt(ticket_id: str) -> str:
    """Build the Claude Code prompt for a ticket."""
    return (
        f"Claim ticket {ticket_id} using track claim. "
        f"Read the ticket with track show {ticket_id}. "
        f"Follow the acceptance criteria."
    )


def build_launch_command(
    *,
    ticket_id: str,
    project_dir: str,
    platform: str | None = None,
    terminal: str | None = None,
) -> tuple[str, list[str]]:
    """Build the command and args to spawn a terminal with Claude Code.

    Args:
        ticket_id: The ticket ID to work on.
        project_dir: Absolute path to the project root.
        platform: "macos" or "linux". Auto-detected if None.
        terminal: Terminal app override. On macOS: "iterm" for iTerm2.
                  On Linux: terminal binary name (default: gnome-terminal).

    Returns:
        Tuple of (executable, [args]).
    """
    if platform is None:
        platform = _detect_platform()

    prompt = _claude_prompt(ticket_id)
    shell_cmd = f"cd {project_dir} && claude --print '{prompt}'"

    if platform == PLATFORM_MACOS:
        if terminal == "iterm":
            script = f'''
            tell application "iTerm"
                create window with default profile
                tell current session of current window
                    write text "cd {project_dir} && claude --print '{prompt}'"
                end tell
                activate
            end tell
            '''
        else:
            # Default: Terminal.app
            script = f'''
            tell application "Terminal"
                do script "cd {project_dir} && claude --print '{prompt}'"
                activate
            end tell
            '''
        return "osascript", ["-e", script]

    # Linux
    term = terminal or os.environ.get("TRACK_TERMINAL", "gnome-terminal")
    return term, ["--", "bash", "-c", shell_cmd]


def launch_agent(
    *,
    ticket_id: str,
    project_dir: str,
    platform: str | None = None,
    terminal: str | None = None,
) -> int:
    """Spawn a terminal with Claude Code for a ticket.

    Returns:
        The PID of the spawned process.
    """
    cmd, args = build_launch_command(
        ticket_id=ticket_id,
        project_dir=project_dir,
        platform=platform,
        terminal=terminal,
    )
    proc = subprocess.Popen([cmd] + args)
    return proc.pid


def handle_launch_request(
    *,
    ticket_id: str,
    project_dir: str,
    platform: str | None = None,
    terminal: str | None = None,
) -> dict:
    """Handle a launch request (from the dashboard API).

    Returns:
        Dict with ticket_id and pid on success, or error on failure.
    """
    from agent_track.services.models import read_ticket

    # Verify ticket exists
    try:
        read_ticket(ticket_id)
    except SystemExit:
        return {"error": f"Ticket {ticket_id} not found."}

    pid = launch_agent(
        ticket_id=ticket_id,
        project_dir=project_dir,
        platform=platform,
        terminal=terminal,
    )
    return {"ticket_id": ticket_id, "pid": pid}
