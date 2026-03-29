"""HTTP handler and server control (serve/stop commands)."""

from __future__ import annotations

import argparse
import http.server
import json
import os
import signal
import sys
from urllib.parse import parse_qs, urlparse

from agent_track.services import paths
from agent_track.dashboard.render import render_dashboard, render_ticket_detail
from agent_track.services.models import all_agents, all_tickets, parse_board_entries


class TrackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        if path == "/":
            self._html(render_dashboard(agent_filter=qs.get("agent", [None])[0]))
        elif path == "/ticket":
            self._html(render_ticket_detail(qs.get("id", [""])[0]))
        elif path == "/api/tickets":
            self._json([{k: v for k, v in m.items()} for m, b, p in all_tickets()])
        elif path == "/api/agents":
            self._json(all_agents())
        elif path == "/api/board":
            self._json(parse_board_entries(int(qs.get("limit", ["20"])[0])))
        elif path == "/api/files":
            fm: dict[str, list[dict[str, str]]] = {}
            for a in all_agents():
                if a.get("status") not in ("active", "idle"):
                    continue
                for f in a.get("files_modified", []):
                    fm.setdefault(f.get("path", "?"), []).append(
                        {"agent": a["id"], "ticket": f.get("ticket", "?")}
                    )
            self._json(fm)
        else:
            self.send_error(404)

    def _html(self, content: str) -> None:
        data = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj: object) -> None:
        data = json.dumps(obj, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        if args and str(args[0]).startswith("2"):
            return
        super().log_message(format, *args)


def cmd_serve(args: argparse.Namespace) -> None:
    """Start the dashboard web server."""
    port = args.port or paths.DEFAULT_PORT

    if paths.SERVER_PID_FILE.exists():
        try:
            old_pid = int(paths.SERVER_PID_FILE.read_text().strip())
            os.kill(old_pid, 0)
            print(
                f"Dashboard already running (PID {old_pid}). Use 'track stop' first.",
                file=sys.stderr,
            )
            sys.exit(1)
        except (OSError, ValueError):
            paths.SERVER_PID_FILE.unlink(missing_ok=True)

    if args.background:
        pid = os.fork()
        if pid > 0:
            paths.LOCKS_DIR.mkdir(parents=True, exist_ok=True)
            paths.SERVER_PID_FILE.write_text(str(pid), encoding="utf-8")
            print(f"Dashboard running at http://localhost:{port} (PID {pid})")
            return
        os.setsid()
        devnull = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull, 0)
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        os.close(devnull)
    else:
        paths.LOCKS_DIR.mkdir(parents=True, exist_ok=True)
        paths.SERVER_PID_FILE.write_text(str(os.getpid()), encoding="utf-8")

    try:
        server = http.server.HTTPServer(("0.0.0.0", port), TrackHandler)
    except OSError as e:
        if "Address already in use" in str(e):
            print(f"Error: Port {port} is already in use.", file=sys.stderr)
        else:
            print(f"Error: {e}", file=sys.stderr)
        paths.SERVER_PID_FILE.unlink(missing_ok=True)
        sys.exit(1)

    if not args.background:
        print(f"Dashboard running at http://localhost:{port}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        paths.SERVER_PID_FILE.unlink(missing_ok=True)
        if not args.background:
            print("\nDashboard stopped.")


def cmd_stop(_args: argparse.Namespace) -> None:
    """Stop a running dashboard server."""
    if not paths.SERVER_PID_FILE.exists():
        print("No dashboard server is running.")
        return

    try:
        pid = int(paths.SERVER_PID_FILE.read_text().strip())
    except (ValueError, OSError):
        print("Corrupt PID file. Removing it.", file=sys.stderr)
        paths.SERVER_PID_FILE.unlink(missing_ok=True)
        return

    try:
        os.kill(pid, signal.SIGTERM)
        print(f"Stopped dashboard (PID {pid}).")
    except ProcessLookupError:
        print(f"Process {pid} not found (already stopped).")
    except PermissionError:
        print(f"Permission denied to stop PID {pid}.", file=sys.stderr)
        sys.exit(1)

    paths.SERVER_PID_FILE.unlink(missing_ok=True)
