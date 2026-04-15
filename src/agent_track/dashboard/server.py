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
from agent_track.dashboard.render import render_dashboard, render_graph_page, render_ticket_detail
from agent_track.services.models import all_agents, all_tickets, parse_board_entries


# ── Data helpers for hook-captured state ─────────────────────────────────────

from agent_track.dashboard.helpers import read_jsonl as _read_jsonl


def _get_sessions() -> list[dict]:
    """List all agent sessions (from ephemeral agents dir)."""
    results = []
    if not paths.AGENTS_DIR.exists():
        return results
    for f in sorted(paths.AGENTS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            results.append({
                "session_id": data.get("session_id", f.stem),
                "agent_id": data.get("id"),
                "status": data.get("status"),
                "model": data.get("model"),
                "registered_at": data.get("registered_at"),
                "last_heartbeat": data.get("last_heartbeat"),
                "current_ticket": data.get("current_ticket"),
            })
        except (json.JSONDecodeError, OSError):
            pass
    return results


def _get_session_activity(session_id: str, limit: int = 50) -> list[dict]:
    """Read activity log for a specific session."""
    activity_file = paths.SESSIONS_DIR / session_id / "activity.jsonl"
    entries = _read_jsonl(activity_file)
    return entries[:limit]


def _get_conflicts(limit: int = 50) -> list[dict]:
    """Read conflict log."""
    return _read_jsonl(paths.SECURITY_DIR / "conflicts.jsonl")[:limit]


def _get_security_alerts(limit: int = 50) -> list[dict]:
    """Read security access log."""
    return _read_jsonl(paths.SECURITY_DIR / "access-log.jsonl")[:limit]


# ── Graph & analysis data helpers ─────────────────────────────────────────────


def _get_graph_data(graph_type: str) -> dict | None:
    """Read a graph JSON file. graph_type is 'file' or 'symbol'."""
    filename = f"{graph_type}-graph.json"
    path = paths.GRAPH_DIR / filename
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _get_analysis_data(analysis_type: str) -> dict | None:
    """Read an analysis JSON file. analysis_type is 'duplicates', 'test-coverage', 'security'."""
    path = paths.ANALYSIS_DIR / f"{analysis_type}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _get_agent_file_activity(project_root: str) -> dict:
    """Map file paths to the agent most recently touching them.

    Scans all active agent sessions, reads their activity.jsonl,
    and returns {relative_file_path: {agent, last_active, tool}}.
    Only includes active/idle agents.
    """
    result: dict[str, dict] = {}

    if not paths.AGENTS_DIR.exists():
        return result

    for agent_file in paths.AGENTS_DIR.glob("*.json"):
        try:
            agent_data = json.loads(agent_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        if agent_data.get("status") not in ("active", "idle"):
            continue

        agent_id = agent_data.get("id", "?")
        session_id = agent_data.get("session_id", agent_file.stem)
        activity_file = paths.SESSIONS_DIR / session_id / "activity.jsonl"
        entries = _read_jsonl(activity_file)

        for entry in entries:
            file_path = entry.get("file")
            if not file_path:
                continue
            ts = entry.get("ts", "")
            tool = entry.get("tool", "")

            # Convert absolute path to relative
            if file_path.startswith(project_root):
                rel = file_path[len(project_root):].lstrip("/")
            else:
                rel = file_path

            # Keep the most recent entry per file
            if rel not in result or ts > result[rel].get("last_active", ""):
                result[rel] = {
                    "agent": agent_id,
                    "last_active": ts,
                    "tool": tool,
                }

    return result


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
        elif path == "/api/agents/activity":
            graph_data = _get_graph_data("file")
            project_root = graph_data["project_root"] if graph_data else str(paths.TRACK_DIR.parent)
            self._json(_get_agent_file_activity(project_root))
        elif path == "/api/sessions":
            self._json(_get_sessions())
        elif path.startswith("/api/sessions/") and path.endswith("/activity"):
            sid = path.split("/")[3]
            self._json(_get_session_activity(sid))
        elif path == "/api/conflicts":
            self._json(_get_conflicts())
        elif path == "/api/security/alerts":
            self._json(_get_security_alerts())
        elif path == "/graph":
            self._html(render_graph_page())
        elif path == "/api/graph/file":
            data = _get_graph_data("file")
            self._json(data if data else {"error": "No graph data. Run `track analyze` first."})
        elif path == "/api/graph/symbol":
            data = _get_graph_data("symbol")
            self._json(data if data else {"error": "No graph data. Run `track analyze` first."})
        elif path == "/api/analysis/duplicates":
            data = _get_analysis_data("duplicates")
            self._json(data if data else {"error": "No analysis data."})
        elif path == "/api/analysis/coverage":
            data = _get_analysis_data("test-coverage")
            self._json(data if data else {"error": "No analysis data."})
        elif path == "/api/analysis/security":
            data = _get_analysis_data("security")
            self._json(data if data else {"error": "No analysis data."})
        elif path == "/api/events":
            self._sse()
        elif path.endswith(".css"):
            self._static(path, "text/css")
        elif path.endswith(".js"):
            self._static(path, "application/javascript")
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

    def _sse(self) -> None:
        """Server-Sent Events endpoint for real-time dashboard updates."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        # Send an initial heartbeat
        try:
            self.wfile.write(b"event: connected\ndata: {}\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _static(self, url_path: str, content_type: str) -> None:
        """Serve static files from the dashboard directory."""
        static_dir = Path(__file__).parent
        # Strip leading slash, prevent directory traversal
        rel = url_path.lstrip("/")
        if ".." in rel:
            self.send_error(403)
            return
        file_path = static_dir / rel
        if not file_path.is_file():
            self.send_error(404)
            return
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
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
