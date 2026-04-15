"""HTML rendering functions for the dashboard."""

from __future__ import annotations

import html as html_mod
import json
from datetime import datetime, timezone
from pathlib import Path

from agent_track.services import paths
from agent_track.services.models import (
    all_agents,
    all_tickets,
    parse_board_entries,
    read_ticket,
)
from agent_track.dashboard.helpers import read_jsonl

_STATIC_DIR = Path(__file__).parent
_FAVICON_SVG = (
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
    "%3Crect width='32' height='32' rx='6' fill='%23fff'/%3E"
    "%3Ctext x='16' y='23' text-anchor='middle' font-family='monospace' "
    "font-size='18' font-weight='700' fill='%23000'%3E.t%3C/text%3E%3C/svg%3E"
)

_css_cache: str | None = None
_js_cache: str | None = None


def _load_css() -> str:
    global _css_cache
    if _css_cache is None:
        _css_cache = (_STATIC_DIR / "style.css").read_text(encoding="utf-8")
    return _css_cache


def _load_js() -> str:
    global _js_cache
    if _js_cache is None:
        _js_cache = (_STATIC_DIR / "script.js").read_text(encoding="utf-8")
    return _js_cache


def _get_agent_todos(agent_id: str) -> list[dict]:
    """Find the latest todo list for an agent by scanning their session activity."""
    if not paths.AGENTS_DIR.exists():
        return []
    # Find session(s) for this agent
    for f in paths.AGENTS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("id") == agent_id:
                sid = data.get("session_id", f.stem)
                activity_file = paths.SESSIONS_DIR / sid / "activity.jsonl"
                entries = read_jsonl(activity_file)
                # Walk backwards for the latest TodoWrite
                for entry in reversed(entries):
                    if entry.get("tool") == "TodoWrite" and "todos" in entry:
                        return entry["todos"]
        except (json.JSONDecodeError, OSError):
            pass
    return []


# ── HTML Helpers ───────────────────────────────────────────────────────────────


def _h(text: str) -> str:
    return html_mod.escape(str(text)) if text else ""


def _time_ago(iso_str: str | None) -> str:
    if not iso_str:
        return "never"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        diff = datetime.now(timezone.utc) - dt
        secs = int(diff.total_seconds())
        if secs < 60:
            return f"{secs}s ago"
        if secs < 3600:
            return f"{secs // 60}m ago"
        if secs < 86400:
            return f"{secs // 3600}h ago"
        return f"{secs // 86400}d ago"
    except (ValueError, TypeError):
        return "?"


def _priority_badge(priority: str) -> str:
    icons = {"critical": "!!!", "high": "!!", "medium": "!", "low": "&mdash;"}
    return f'<span class="badge badge-{_h(priority)}">{icons.get(priority, "")} {_h(priority)}</span>'


def _board_entry_class(tag: str) -> str:
    if "claimed" in tag:
        return "board-entry-claimed"
    if "status:" in tag:
        return "board-entry-status"
    return {
        "registered": "board-entry-registered",
        "deregistered": "board-entry-deregistered",
        "created": "board-entry-created",
        "blocked": "board-entry-blocked",
        "question": "board-entry-question",
    }.get(tag, "")


# ── Page Rendering ─────────────────────────────────────────────────────────────


def render_page(title: str, body: str) -> str:
    return (
        f"<!DOCTYPE html>\n"
        f'<html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f'<link rel="icon" href="data:image/svg+xml,{_FAVICON_SVG}">\n'
        f"<title>{_h(title)}</title><style>{_load_css()}</style></head>\n"
        f"<body>{body}<script>{_load_js()}</script></body></html>"
    )


_graph_js_cache: str | None = None


def _load_graph_js() -> str:
    global _graph_js_cache
    if _graph_js_cache is None:
        gjs = _STATIC_DIR / "graph.js"
        _graph_js_cache = gjs.read_text(encoding="utf-8") if gjs.exists() else ""
    return _graph_js_cache


def render_graph_page() -> str:
    """Render the interactive d3 force-directed graph page."""
    graph_js = _load_graph_js()

    body = (
        '<div class="header"><div class="header-left">'
        '<div class="header-logo">.t</div><h1>.track — The Score</h1></div>'
        '<div class="header-stats">'
        '<a href="/" class="tab-link">Kanban</a>'
        '<a href="/graph" class="tab-link tab-active">Graph</a>'
        '</div></div>'
        '<div class="graph-layout">'
        '<div class="graph-sidebar">'
        '<div class="sidebar-section">'
        '<div class="sidebar-title">Overlays</div>'
        '<label class="overlay-toggle"><input type="checkbox" id="overlay-agents" checked> Agents</label>'
        '<label class="overlay-toggle"><input type="checkbox" id="overlay-dupes"> Duplicates</label>'
        '<label class="overlay-toggle"><input type="checkbox" id="overlay-tests"> Tests</label>'
        '<label class="overlay-toggle"><input type="checkbox" id="overlay-security"> Security</label>'
        '</div>'
        '<div class="sidebar-section">'
        '<div class="sidebar-title">Filters</div>'
        '<select id="filter-dir" class="graph-select"><option value="">All directories</option></select>'
        '<select id="filter-lang" class="graph-select"><option value="">All languages</option></select>'
        '</div>'
        '<div class="sidebar-section" id="inspector">'
        '<div class="sidebar-title">Inspector</div>'
        '<div class="inspector-content"><span class="text-muted">Click a node to inspect</span></div>'
        '</div>'
        '</div>'
        '<div class="graph-canvas" id="graph-container"></div>'
        '</div>'
    )

    # Inline d3 from CDN + graph.js
    d3_script = '<script src="https://d3js.org/d3.v7.min.js"></script>'
    graph_script = f"<script>{graph_js}</script>" if graph_js else ""

    page_html = (
        f"<!DOCTYPE html>\n"
        f'<html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f'<link rel="icon" href="data:image/svg+xml,{_FAVICON_SVG}">\n'
        f"<title>.track — The Score</title>"
        f"<style>{_load_css()}</style>"
        f"<style>{_graph_css()}</style>"
        f"</head>\n<body>{body}{d3_script}{graph_script}</body></html>"
    )
    return page_html


def _graph_css() -> str:
    """Additional CSS for the graph page."""
    return """
.tab-link { display:inline-flex; padding:4px 12px; border-radius:var(--radius-full);
  font-size:12px; font-weight:600; color:var(--text-muted); text-decoration:none;
  font-family:var(--font-mono); }
.tab-link:hover { color:var(--primary); opacity:1; }
.tab-active { background:var(--primary); color:var(--primary-fg) !important; }

.graph-layout { display:grid; grid-template-columns:220px 1fr; gap:0;
  height:calc(100vh - 100px); border:1px solid var(--border); border-radius:var(--radius-lg);
  overflow:hidden; background:var(--surface); }
.graph-sidebar { padding:16px; border-right:1px solid var(--border);
  overflow-y:auto; background:var(--surface); }
.sidebar-section { margin-bottom:20px; }
.sidebar-title { font-size:11px; font-weight:600; text-transform:uppercase;
  letter-spacing:0.06em; color:var(--text-muted); margin-bottom:8px;
  padding-bottom:6px; border-bottom:1px solid var(--divider); }
.overlay-toggle { display:flex; align-items:center; gap:8px; font-size:13px;
  padding:4px 0; cursor:pointer; color:var(--text); }
.overlay-toggle input { accent-color:var(--accent); }
.graph-select { width:100%; padding:6px 8px; margin-bottom:6px;
  background:var(--bg); border:1px solid var(--border); border-radius:var(--radius-sm);
  font-size:12px; font-family:var(--font-mono); color:var(--text); }
.inspector-content { font-size:12px; color:var(--text-secondary); line-height:1.6; }
.inspector-content .file-name { font-weight:600; font-family:var(--font-mono);
  color:var(--primary); font-size:13px; margin-bottom:4px; }
.inspector-content .detail-row { display:flex; justify-content:space-between;
  padding:2px 0; }
.inspector-content .detail-label { color:var(--text-muted); }
.text-muted { color:var(--text-muted); }

.graph-canvas { position:relative; overflow:hidden; background:#1a1a2e; }
.graph-canvas svg { width:100%; height:100%; }

/* Node styles */
.node circle { stroke:#333; stroke-width:1; cursor:pointer; transition:opacity 0.2s; }
.node text { font-family:var(--font-mono); font-size:9px; fill:#999;
  pointer-events:none; }
.node:hover circle { stroke:var(--accent); stroke-width:2; }
.node.selected circle { stroke:#fff; stroke-width:2; }
.node.duplicate circle { fill:#ffd700 !important; }
.node.untested circle { stroke:#ff4444; stroke-width:2; stroke-dasharray:4,2; }
.node.security-finding circle { fill:#ff4444 !important; }
.node .agent-halo { fill:none; stroke:#00ff88; stroke-width:2; opacity:0; }
.node .agent-halo.active { opacity:0.8; animation:pulse 2s ease-in-out infinite; }
.node .agent-halo.fading { opacity:0.3; stroke-dasharray:4,3; }

.link { stroke-opacity:0.3; fill:none; }
.link.import { stroke:#555; stroke-width:1; }
.link.call { stroke:#666; stroke-width:0.5; stroke-dasharray:3,3; }
.link.highlighted { stroke:var(--accent); stroke-opacity:0.8; stroke-width:2; }

@keyframes pulse {
  0%, 100% { opacity:0.4; r:inherit; }
  50% { opacity:0.9; }
}

.tooltip { position:absolute; background:rgba(0,0,0,0.85); color:#fff; padding:6px 10px;
  border-radius:4px; font-size:11px; font-family:var(--font-mono); pointer-events:none;
  z-index:100; white-space:nowrap; }
"""


def render_dashboard(agent_filter: str | None = None) -> str:
    tickets = all_tickets()
    agents = all_agents()
    board_entries = parse_board_entries(limit=20)

    by_status: dict[str, list] = {s: [] for s in paths.STATUSES}
    for meta, body, path in tickets:
        if agent_filter and meta.get("claimed_by") != agent_filter:
            continue
        s = meta.get("status", "backlog")
        if s in by_status:
            by_status[s].append(meta)

    active_agents = [a for a in agents if a.get("status") in ("active", "idle")]
    total = sum(len(v) for v in by_status.values())

    header = (
        f'<div class="header"><div class="header-left">'
        f'<div class="header-logo">.t</div><h1>.track</h1></div>'
        f'<div class="header-stats">'
        f'<div class="stat"><span class="stat-value">{total}</span> tickets</div>'
        f'<div class="stat"><span class="stat-dot stat-dot-{"green" if active_agents else "muted"}"></span>'
        f'<span class="stat-value">{len(active_agents)}</span> agents</div>'
        f'<div class="stat" style="color:var(--text-muted);font-family:var(--font-mono);font-size:11px">'
        f"{datetime.now(timezone.utc).strftime('%H:%M:%S')}</div>"
        f'<a href="/" style="padding:4px 12px;border-radius:999px;font-size:12px;font-weight:600;'
        f'background:var(--primary);color:var(--primary-fg);font-family:var(--font-mono);text-decoration:none">Kanban</a>'
        f'<a href="/graph" style="padding:4px 12px;border-radius:999px;font-size:12px;font-weight:600;'
        f'color:var(--text-muted);font-family:var(--font-mono);text-decoration:none">Graph</a>'
        f"</div></div>"
    )

    filter_html = ""
    if agent_filter:
        filter_html = (
            f'<div class="filter-bar">Filtering by <strong>{_h(agent_filter)}</strong>'
            f' <a href="/" class="filter-clear">&times; Clear</a></div>'
        )

    kanban = '<div class="kanban">'
    for status in paths.STATUSES:
        items = by_status[status]
        kanban += (
            f'<div class="kanban-col"><div class="col-header">'
            f'<span class="col-title">{_h(status)}</span>'
            f'<span class="col-count">{len(items)}</span></div>'
        )
        kanban += '<div class="kanban-col-cards">'
        if not items:
            kanban += '<div class="empty"><div class="empty-icon">&mdash;</div></div>'
        for t in items:
            priority = t.get("priority", "medium")
            tid = t.get("id", "?")
            agent = t.get("claimed_by")
            labels = t.get("labels") or []
            kanban += (
                f'<a href="/ticket?id={_h(tid)}" class="card">'
                f'<div class="card-top"><span class="card-id">{_h(tid)}</span>'
                f"{_priority_badge(priority)}</div>"
                f'<div class="card-title">{_h(t.get("title", "?"))}</div>'
                f'<div class="card-footer">'
            )
            if agent:
                kanban += f'<span class="badge badge-agent">{_h(agent)}</span>'
            for lbl in labels:
                kanban += f'<span class="badge badge-label">{_h(lbl)}</span>'
            kanban += "</div></a>"
        kanban += "</div></div>"
    kanban += "</div>"

    agents_html = (
        f'<div class="panel"><div class="panel-header">'
        f'<span class="panel-title">Agents</span>'
        f'<span class="panel-count">{len(active_agents)} active</span></div>'
    )
    if not active_agents:
        agents_html += '<div class="empty">No active agents</div>'
    for a in active_agents:
        st = a.get("status", "active")
        hb = _time_ago(a.get("last_heartbeat"))
        ticket = a.get("current_ticket")
        caps = a.get("capabilities", [])
        n_files = len(a.get("files_modified", []))
        is_selected = agent_filter == a["id"]
        card_cls = "agent-card agent-card-selected" if is_selected else "agent-card"
        agents_html += (
            f'<a href="/?agent={_h(a["id"])}" class="{card_cls}"><div class="agent-top">'
            f'<span class="agent-name">{_h(a["id"])}</span>'
            f'<span class="badge badge-status-{_h(st)}">{_h(st)}</span></div>'
            f'<div class="agent-detail-row">'
            f'<span class="agent-detail">Ticket: <strong style="color:var(--primary);font-family:var(--font-mono)">'
            f"{_h(ticket) if ticket else '--'}</strong></span>"
            f'<span class="agent-detail">Heartbeat: {_h(hb)}</span>'
            f'<span class="agent-detail">Files: {n_files}</span></div>'
        )
        if caps:
            agents_html += (
                '<div style="margin-top:4px">'
                + " ".join(
                    f'<span class="badge badge-label">{_h(c)}</span>' for c in caps
                )
                + "</div>"
            )
        agents_html += "</a>"
    agents_html += "</div>"

    file_map: dict[str, list[tuple[str, str]]] = {}
    for a in active_agents:
        for fm in a.get("files_modified", []):
            fpath = fm.get("path", "?")
            file_map.setdefault(fpath, []).append((a["id"], fm.get("ticket", "?")))
    n_conflicts = sum(1 for owners in file_map.values() if len(owners) > 1)
    files_html = (
        f'<div class="panel"><div class="panel-header">'
        f'<span class="panel-title">File Ownership</span>'
        f'<span class="panel-count">{len(file_map)} files'
        f"{f' &middot; {n_conflicts} conflicts' if n_conflicts else ''}</span></div>"
    )
    if not file_map:
        files_html += '<div class="empty">No files tracked</div>'
    else:
        for fpath in sorted(file_map.keys()):
            owners = file_map[fpath]
            is_conflict = len(owners) > 1
            cls = "file-entry file-conflict" if is_conflict else "file-entry"
            path_html = (
                f'<span class="conflict-icon">&#9888;</span> {_h(fpath)}'
                if is_conflict
                else _h(fpath)
            )
            owner_strs = [f"{aid} ({t})" for aid, t in owners]
            files_html += (
                f'<div class="{cls}"><span class="file-path">{path_html}</span>'
                f'<span class="file-owner">{_h(" / ".join(owner_strs))}</span></div>'
            )
    files_html += "</div>"

    board_html = (
        f'<div class="panel board-full"><div class="panel-header">'
        f'<span class="panel-title">Board</span>'
        f'<span class="panel-count">{len(board_entries)} messages</span></div>'
    )
    if not board_entries:
        board_html += '<div class="empty">Board is empty</div>'
    for e in board_entries:
        ts = e.get("timestamp", "?")
        short_ts = ts[11:16] if len(ts) > 16 else ts
        tag = e.get("tag", "note")
        entry_cls = _board_entry_class(tag)
        ticket_ref = e.get("ticket", "")
        agent_name = e.get("agent", "?")
        ticket_link = (
            f' &middot; <a href="/ticket?id={_h(ticket_ref)}">{_h(ticket_ref)}</a>'
            if ticket_ref and ticket_ref != "system"
            else ""
        )
        board_html += (
            f'<div class="board-entry {entry_cls}">'
            f'<div class="board-entry-header-row">'
            f'<span class="board-who"><strong>{_h(agent_name)}</strong>{ticket_link}</span>'
            f'<span class="board-when"><span class="board-tag">{_h(tag)}</span> {_h(short_ts)}</span></div>'
            f'<div class="board-msg">{_h(e.get("message", ""))}</div></div>'
        )
    board_html += "</div>"

    return render_page(
        ".track/ Dashboard",
        f"{header}{filter_html}{kanban}<div class='panels'>{agents_html}{files_html}</div>"
        f"<div class='panels'>{board_html}</div>",
    )


def render_ticket_detail(ticket_id: str) -> str:
    try:
        meta, body, path = read_ticket(ticket_id)
    except SystemExit:
        return render_page(
            "Not Found",
            '<div class="ticket-detail"><div class="empty" style="padding:48px">'
            '<div class="empty-icon">?</div>Ticket not found.<br>'
            '<a href="/" class="back-link" style="display:inline-flex;margin-top:12px">'
            "&larr; Back</a></div></div>",
        )

    status = meta.get("status", "?")
    priority = meta.get("priority", "?")
    meta_rows = ""
    for label, key in [
        ("ID", "id"),
        ("Created", "created"),
        ("Created by", "created_by"),
        ("Claimed by", "claimed_by"),
        ("Claimed at", "claimed_at"),
        ("Branch", "branch"),
    ]:
        val = meta.get(key)
        meta_rows += (
            f'<div class="meta-key">{_h(label)}</div>'
            f'<div class="meta-val">{_h(str(val) if val else "--")}</div>'
        )

    labels = meta.get("labels") or []
    labels_html = (
        " ".join(f'<span class="badge badge-label">{_h(lbl)}</span>' for lbl in labels)
        if labels
        else "--"
    )
    meta_rows += (
        f'<div class="meta-key">Labels</div><div class="meta-val">{labels_html}</div>'
    )
    files = meta.get("files") or []
    files_val = "<br>".join(_h(f) for f in files) if files else "--"
    meta_rows += (
        f'<div class="meta-key">Files</div><div class="meta-val">{files_val}</div>'
    )
    deps = meta.get("depends_on") or []
    deps_links = [f'<a href="/ticket?id={_h(d)}">{_h(d)}</a>' for d in deps]
    deps_val = " ".join(deps_links) if deps_links else "--"
    meta_rows += (
        f'<div class="meta-key">Depends on</div><div class="meta-val">{deps_val}</div>'
    )

    # ── Agent Todos ─────────────────────────────────────────────────────────
    todos_html = ""
    claimed_by = meta.get("claimed_by")
    if claimed_by:
        todos = _get_agent_todos(claimed_by)
        if todos:
            todos_html = (
                '<div class="panel" style="margin-top:16px">'
                '<div class="panel-header">'
                '<span class="panel-title">Agent Todos</span>'
                f'<span class="panel-count">{_h(claimed_by)}</span></div>'
            )
            for t in todos:
                status_icon = {
                    "completed": "&#10003;",
                    "in_progress": "&#9654;",
                    "pending": "&#9675;",
                }.get(t.get("status", ""), "&#9675;")
                status_cls = t.get("status", "pending").replace("_", "-")
                todos_html += (
                    f'<div class="todo-item todo-{_h(status_cls)}">'
                    f'<span class="todo-icon">{status_icon}</span>'
                    f'<span class="todo-content">{_h(t.get("content", ""))}</span>'
                    f'</div>'
                )
            todos_html += "</div>"

    status_badge_cls = (
        "active"
        if status in ("claimed", "in-progress")
        else "idle"
        if status == "review"
        else "deregistered"
        if status == "done"
        else "idle"
    )
    return render_page(
        f"{ticket_id} — .track/",
        f'<div class="ticket-detail">'
        f'<a href="/" class="back-link">&larr; Dashboard</a>'
        f'<div class="ticket-header"><h2>{_h(meta.get("title", "?"))}</h2>'
        f'<div class="ticket-header-meta">'
        f'<span class="badge badge-agent">{_h(meta.get("id", "?"))}</span>'
        f"{_priority_badge(priority)}"
        f'<span class="badge badge-status-{status_badge_cls}">{_h(status)}</span></div></div>'
        f'<div class="meta-grid">{meta_rows}</div>'
        f'{todos_html}'
        f'<div class="body-content">{_h(body)}</div></div>',
    )
