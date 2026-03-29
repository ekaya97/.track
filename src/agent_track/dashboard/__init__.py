"""Web dashboard package: HTTP server, HTML rendering, serve/stop commands."""

from agent_track.dashboard.server import cmd_serve, cmd_stop

__all__ = ["cmd_serve", "cmd_stop"]
