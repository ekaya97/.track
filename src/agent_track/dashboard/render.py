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
from agent_track.dashboard.helpers import effective_status, read_jsonl

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
    """Render the full-screen graph-first dashboard."""
    graph_js = _load_graph_js()
    tickets = all_tickets()
    agents = all_agents()
    board_entries = parse_board_entries(limit=10)
    # Compute effective status for all agents
    for a in agents:
        a["_effective_status"] = effective_status(a)
    active_agents = [a for a in agents if a["_effective_status"] in ("active", "idle")]

    # Mini kanban counts
    counts: dict[str, int] = {s: 0 for s in paths.STATUSES}
    for meta, _, _ in tickets:
        s = meta.get("status", "backlog")
        if s in counts:
            counts[s] += 1
    total_tickets = sum(counts.values())

    # Agent pills HTML
    agent_pills = ""
    for a in active_agents:
        tid = a.get("current_ticket") or ""
        es = a["_effective_status"]
        dot_cls = "dot-active" if es == "active" else "dot-idle"
        agent_pills += (
            f'<div class="agent-pill" data-agent="{_h(a["id"])}">'
            f'<span class="agent-pill-dot {dot_cls}"></span>'
            f'<span class="agent-pill-name">{_h(a["id"])}</span>'
            f'<span class="agent-pill-status">{_h(es)}</span>'
            f'<span class="agent-pill-ticket">{_h(tid)}</span>'
            f'</div>'
        )
    if not active_agents:
        agent_pills = '<div class="text-muted" style="font-size:12px">No active agents</div>'

    # Board HTML
    board_html = ""
    for e in board_entries:
        ts = e.get("timestamp", "?")
        short_ts = ts[11:16] if len(ts) > 16 else ts
        agent_name = e.get("agent", "?")
        ticket_ref = e.get("ticket", "")
        msg = e.get("message", "")
        ticket_str = f" · {_h(ticket_ref)}" if ticket_ref and ticket_ref != "system" else ""
        board_html += (
            f'<div class="board-item">'
            f'<div class="board-item-header">'
            f'<span class="board-item-who">{_h(agent_name)}{ticket_str}</span>'
            f'<span class="board-item-when">{_h(short_ts)}</span>'
            f'</div>'
            f'<div class="board-item-msg">{_h(msg)}</div>'
            f'</div>'
        )
    if not board_entries:
        board_html = '<div class="text-muted" style="font-size:12px;padding:8px">No messages</div>'

    # Mini kanban HTML
    kanban_mini = ""
    status_labels = {"backlog": "BKL", "claimed": "CLM", "in-progress": "WIP", "review": "REV", "done": "DON"}
    for s in paths.STATUSES:
        c = counts[s]
        active_cls = " mini-active" if c > 0 and s in ("claimed", "in-progress") else ""
        kanban_mini += f'<div class="mini-status{active_cls}"><span class="mini-count">{c}</span><span class="mini-label">{status_labels.get(s, s)}</span></div>'

    body = (
        # Header
        '<div class="dash-header">'
        '<div class="dash-header-left">'
        '<div class="header-logo">.t</div>'
        '<span class="header-title">.track</span>'
        '</div>'
        '<div class="dash-header-right">'
        f'<div class="header-stat"><span class="stat-value">{total_tickets}</span> tickets</div>'
        f'<div class="header-stat"><span class="stat-dot stat-dot-{"green" if active_agents else "muted"}"></span>'
        f'<span class="stat-value">{len(active_agents)}</span> agents</div>'
        '<a href="/kanban" class="nav-link">Kanban</a>'
        '<button class="theme-toggle" onclick="toggleTheme()" title="Toggle theme">&#9788;</button>'
        '</div>'
        '</div>'

        # Three-column layout
        '<div class="dash-layout">'

        # Left sidebar
        '<div class="dash-sidebar" id="left-sidebar">'
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
        '<div class="sidebar-section">'
        f'<div class="sidebar-title">Agents <span class="sidebar-count">{len(active_agents)}</span></div>'
        f'{agent_pills}'
        '</div>'
        '<div class="sidebar-section">'
        '<div class="sidebar-title">Tickets</div>'
        f'<div class="mini-kanban">{kanban_mini}</div>'
        '</div>'
        '</div>'

        # Graph canvas
        '<div class="graph-canvas" id="graph-container"></div>'

        # Right panel (collapsed by default)
        '<div class="dash-panel" id="right-panel">'
        '<div class="panel-inner">'
        '<div class="sidebar-section" id="inspector">'
        '<div class="sidebar-title">Inspector <button class="panel-close" onclick="closePanel()">&#10005;</button></div>'
        '<div class="inspector-content"><span class="text-muted">Click a node to inspect</span></div>'
        '</div>'
        '<div class="sidebar-section" id="panel-board">'
        f'<div class="sidebar-title">Board <span class="sidebar-count">{len(board_entries)}</span></div>'
        f'{board_html}'
        '</div>'
        '</div>'
        '</div>'

        '</div>'  # end dash-layout
    )

    # Theme init script (runs before d3)
    theme_script = """<script>
(function(){
  var s=localStorage.getItem('track-theme');
  if(!s){s=window.matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light'}
  document.documentElement.setAttribute('data-theme',s);
  updateThemeIcon(s);
})();
function toggleTheme(){
  var c=document.documentElement.getAttribute('data-theme');
  var n=c==='dark'?'light':'dark';
  document.documentElement.setAttribute('data-theme',n);
  localStorage.setItem('track-theme',n);
  updateThemeIcon(n);
}
function updateThemeIcon(t){
  var b=document.querySelector('.theme-toggle');
  if(b)b.innerHTML=t==='dark'?'&#9790;':'&#9788;';
}
function closePanel(){
  document.getElementById('right-panel').classList.remove('panel-open');
}
function openPanel(){
  document.getElementById('right-panel').classList.add('panel-open');
}
</script>"""

    # Inline d3
    d3_path = _STATIC_DIR / "d3.v7.min.js"
    d3_inline = d3_path.read_text(encoding="utf-8") if d3_path.exists() else ""
    d3_script = f"<script>{d3_inline}</script>" if d3_inline else '<script src="https://d3js.org/d3.v7.min.js"></script>'
    graph_script = f"<script>{graph_js}</script>" if graph_js else ""

    return (
        f"<!DOCTYPE html>\n"
        f'<html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f'<link rel="icon" href="data:image/svg+xml,{_FAVICON_SVG}">\n'
        f"<title>.track</title>"
        f"<style>{_load_css()}</style>"
        f"<style>{_graph_css()}</style>"
        f"</head>\n<body>{theme_script}{body}{d3_script}{graph_script}</body></html>"
    )


def _graph_css() -> str:
    """CSS for the graph-first dashboard."""
    return """
/* ── Theme ─────────────────────────────────────────────── */
[data-theme="dark"] {
  --bg:#1e1e1e; --surface:#252525; --surface-2:#333; --surface-3:#444;
  --text:#ccc; --text-secondary:#aaa; --text-muted:#777;
  --primary:#fff; --primary-fg:#000;
  --accent:#db924b; --border:#3a3a3a; --divider:#333;
  --graph-bg:#141422; --graph-node-text:#999;
  --success:#4caf50; --success-bg:rgba(76,175,80,.15);
  --warning:#ff9800; --danger:#ef5350; --info:#42a5f5;
  --shadow-sm:0 1px 3px rgba(0,0,0,.4);
}
[data-theme="light"] {
  --bg:#faf9f5; --surface:#f0f0f0; --surface-2:#e6e6e6; --surface-3:#dcdcdc;
  --text:#4a4a4a; --text-secondary:#737373; --text-muted:#8f8f8f;
  --primary:#000; --primary-fg:#fff;
  --accent:#db924b; --border:#d1d1d1; --divider:#e0e0e0;
  --graph-bg:#f0efe8; --graph-node-text:#666;
  --success:#388e3c; --success-bg:rgba(56,142,60,.1);
  --warning:#f57c00; --danger:#d32f2f; --info:#1976d2;
  --shadow-sm:0 1px 2px rgba(0,0,0,.08);
}
html:not([data-theme]) { color-scheme:light dark; }
@media(prefers-color-scheme:dark){ html:not([data-theme]){
  --bg:#1e1e1e;--surface:#252525;--text:#ccc;--graph-bg:#141422;
}}

body { margin:0; background:var(--bg); color:var(--text);
  font-family:'Inter',system-ui,sans-serif; overflow:hidden; height:100vh; }

/* ── Header ────────────────────────────────────────────── */
.dash-header { display:flex; align-items:center; justify-content:space-between;
  height:40px; padding:0 12px; background:var(--surface); border-bottom:1px solid var(--border);
  flex-shrink:0; }
.dash-header-left { display:flex; align-items:center; gap:8px; }
.header-logo { font-family:'IBM Plex Mono',monospace; font-weight:700; font-size:14px;
  background:var(--primary); color:var(--primary-fg); padding:2px 6px; border-radius:4px; }
.header-title { font-size:14px; font-weight:600; color:var(--text); }
.dash-header-right { display:flex; align-items:center; gap:16px; }
.header-stat { font-size:12px; color:var(--text-muted); font-family:'IBM Plex Mono',monospace;
  display:flex; align-items:center; gap:4px; }
.stat-value { font-weight:600; color:var(--text); }
.stat-dot { width:6px; height:6px; border-radius:50%; display:inline-block; }
.stat-dot-green { background:#4caf50; }
.stat-dot-muted { background:var(--text-muted); }
.theme-toggle { background:none; border:1px solid var(--border); border-radius:var(--radius-sm);
  color:var(--text); cursor:pointer; font-size:16px; width:28px; height:28px;
  display:flex; align-items:center; justify-content:center; }
.theme-toggle:hover { background:var(--surface-2); }

/* ── Nav links ────────────────────────────────────────── */
.nav-link { padding:4px 12px; border-radius:999px; font-size:12px; font-weight:600;
  color:var(--text-muted); font-family:'IBM Plex Mono',monospace; text-decoration:none; }
.nav-link:hover { color:var(--text); opacity:1; }
.nav-link-active { background:var(--primary); color:var(--primary-fg); }
.nav-link-active:hover { color:var(--primary-fg); }

/* ── Layout ────────────────────────────────────────────── */
.dash-layout { display:grid; grid-template-columns:220px 1fr 0; height:calc(100vh - 40px);
  transition:grid-template-columns .25s ease; }
.dash-layout.panel-open { grid-template-columns:220px 1fr 320px; }

/* ── Left sidebar ──────────────────────────────────────── */
.dash-sidebar { padding:12px; border-right:1px solid var(--border); overflow-y:auto;
  background:var(--surface); font-size:13px; }
.sidebar-section { margin-bottom:16px; }
.sidebar-title { font-size:10px; font-weight:700; text-transform:uppercase;
  letter-spacing:.08em; color:var(--text-muted); margin-bottom:6px;
  padding-bottom:4px; border-bottom:1px solid var(--divider);
  display:flex; align-items:center; justify-content:space-between; }
.sidebar-count { font-size:10px; font-weight:500; color:var(--text-muted);
  background:var(--surface-2); padding:1px 5px; border-radius:8px; }
.overlay-toggle { display:flex; align-items:center; gap:6px; font-size:12px;
  padding:3px 0; cursor:pointer; color:var(--text); }
.overlay-toggle input { accent-color:var(--accent); width:14px; height:14px; }
.graph-select { width:100%; padding:5px 6px; margin-bottom:4px;
  background:var(--bg); border:1px solid var(--border); border-radius:var(--radius-sm);
  font-size:11px; font-family:'IBM Plex Mono',monospace; color:var(--text); }
.text-muted { color:var(--text-muted); }

/* ── Agent pills ───────────────────────────────────────── */
.agent-pill { display:flex; align-items:center; gap:6px; padding:4px 6px;
  border-radius:var(--radius-sm); cursor:pointer; font-size:12px;
  transition:background .15s; }
.agent-pill:hover { background:var(--surface-2); }
.agent-pill-dot { width:8px; height:8px; border-radius:50%; flex-shrink:0; }
.agent-pill-dot.dot-active { background:var(--success); }
.agent-pill-dot.dot-idle { background:var(--warning); }
.agent-pill-status { font-size:9px; color:var(--text-muted); text-transform:uppercase; }
.agent-pill-name { font-family:'IBM Plex Mono',monospace; font-weight:500;
  color:var(--text); font-size:11px; }
.agent-pill-ticket { font-family:'IBM Plex Mono',monospace; color:var(--accent);
  font-size:10px; margin-left:auto; }

/* ── Mini kanban ───────────────────────────────────────── */
.mini-kanban { display:flex; gap:2px; }
.mini-status { flex:1; text-align:center; padding:4px 2px; border-radius:var(--radius-sm);
  background:var(--surface-2); }
.mini-status.mini-active { background:var(--success-bg); }
.mini-count { display:block; font-size:14px; font-weight:700; color:var(--text);
  font-family:'IBM Plex Mono',monospace; }
.mini-label { display:block; font-size:8px; font-weight:600; text-transform:uppercase;
  letter-spacing:.04em; color:var(--text-muted); }

/* ── Graph canvas ──────────────────────────────────────── */
.graph-canvas { position:relative; overflow:hidden; background:var(--graph-bg); }
.graph-canvas svg { width:100%; height:100%; }

/* ── Right panel ───────────────────────────────────────── */
.dash-panel { overflow:hidden; width:0; opacity:0; transition:opacity .2s ease;
  border-left:1px solid var(--border); background:var(--surface); }
.dash-panel.panel-open, .dash-layout.panel-open .dash-panel { width:auto; opacity:1; }
.panel-inner { padding:12px; overflow-y:auto; height:100%; }
.panel-close { background:none; border:none; color:var(--text-muted); cursor:pointer;
  font-size:14px; padding:0 2px; line-height:1; }
.panel-close:hover { color:var(--danger); }

/* ── Inspector ─────────────────────────────────────────── */
.inspector-content { font-size:12px; color:var(--text-secondary); line-height:1.6; }
.inspector-content .file-name { font-weight:600; font-family:'IBM Plex Mono',monospace;
  color:var(--primary); font-size:13px; margin-bottom:6px; word-break:break-all; }
.inspector-content .detail-row { display:flex; justify-content:space-between; padding:2px 0; }
.inspector-content .detail-label { color:var(--text-muted); font-size:11px; }
.inspector-content .detail-value { font-family:'IBM Plex Mono',monospace; font-size:11px; }
.inspector-section { margin-top:10px; padding-top:8px; border-top:1px solid var(--divider); }
.inspector-section-title { font-size:10px; font-weight:700; text-transform:uppercase;
  letter-spacing:.06em; color:var(--text-muted); margin-bottom:4px; }

/* ── Board items (right panel) ─────────────────────────── */
.board-item { padding:6px 0; border-bottom:1px solid var(--divider); font-size:11px; }
.board-item:last-child { border-bottom:none; }
.board-item-header { display:flex; justify-content:space-between; margin-bottom:2px; }
.board-item-who { font-weight:600; color:var(--text); font-family:'IBM Plex Mono',monospace;
  font-size:10px; }
.board-item-when { color:var(--text-muted); font-family:'IBM Plex Mono',monospace;
  font-size:10px; }
.board-item-msg { color:var(--text-secondary); font-size:11px; line-height:1.4; }

/* ── Graph nodes ───────────────────────────────────────── */
.node circle { stroke:#333; stroke-width:1; cursor:pointer; transition:opacity .2s; }
.node text { font-family:'IBM Plex Mono',monospace; font-size:9px; fill:var(--graph-node-text);
  pointer-events:none; }
.node:hover circle { stroke:var(--accent); stroke-width:2; }
.node.selected circle { stroke:#fff; stroke-width:2; }
.node.dimmed { opacity:.12; }
.node.duplicate circle { fill:#ffd700 !important; }
.node.untested circle { stroke:#ff4444; stroke-width:2; stroke-dasharray:4,2; }
.node.security-finding circle { fill:#ff4444 !important; }
.node .agent-halo { fill:none; stroke:#00ff88; stroke-width:2; opacity:0; }
.node .agent-halo.active { opacity:.8; animation:pulse 2s ease-in-out infinite; }
.node .agent-halo.fading { opacity:.3; stroke-dasharray:4,3; }

.link { stroke-opacity:.3; fill:none; }
.link.import { stroke:#555; stroke-width:1; }
.link.call { stroke:#666; stroke-width:.5; stroke-dasharray:3,3; }
.link.highlighted { stroke:var(--accent); stroke-opacity:.8; stroke-width:2; }

@keyframes pulse {
  0%,100% { opacity:.4; }
  50% { opacity:.9; }
}

.tooltip { position:absolute; background:rgba(0,0,0,.85); color:#fff; padding:6px 10px;
  border-radius:4px; font-size:11px; font-family:'IBM Plex Mono',monospace;
  pointer-events:none; z-index:100; white-space:nowrap; }
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
        f'<a href="/kanban" class="nav-link nav-link-active">Kanban</a>'
        f'<a href="/" class="nav-link">Graph</a>'
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
