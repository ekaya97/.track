"""Tests for the d3 force graph dashboard page and analysis API endpoints."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_track.services import paths


@pytest.fixture(autouse=True)
def track_env(tmp_path, monkeypatch):
    """Set up temp project-local and ephemeral directories."""
    track_dir = tmp_path / ".track"
    home_dir = tmp_path / ".track-home"

    monkeypatch.setattr(paths, "TRACK_DIR", track_dir)
    monkeypatch.setattr(paths, "TICKETS_DIR", track_dir / "tickets")
    monkeypatch.setattr(paths, "ARCHIVE_DIR", track_dir / "archive")
    monkeypatch.setattr(paths, "BOARD_FILE", track_dir / "BOARD.md")
    monkeypatch.setattr(paths, "CONVENTIONS_FILE", track_dir / "CONVENTIONS.md")
    monkeypatch.setattr(paths, "CONFIG_FILE", track_dir / "config.json")
    monkeypatch.setattr(paths, "GRAPH_DIR", track_dir / "graph")
    monkeypatch.setattr(paths, "ANALYSIS_DIR", track_dir / "analysis")
    monkeypatch.setattr(paths, "AGENTS_DIR", home_dir / "agents")
    monkeypatch.setattr(paths, "SESSIONS_DIR", home_dir / "sessions")
    monkeypatch.setattr(paths, "SECURITY_DIR", home_dir / "security")
    monkeypatch.setattr(paths, "LOCKS_DIR", home_dir / "locks")
    monkeypatch.setattr(paths, "LOCKS_FILE", home_dir / "locks.json")
    monkeypatch.setattr(paths, "SERVER_PID_FILE", home_dir / "locks" / "server.pid")

    for d in [
        track_dir, track_dir / "tickets", track_dir / "archive",
        track_dir / "graph", track_dir / "analysis",
        home_dir / "agents", home_dir / "sessions",
        home_dir / "security", home_dir / "locks",
    ]:
        d.mkdir(parents=True, exist_ok=True)

    # Write a board file so render_dashboard doesn't fail
    (track_dir / "BOARD.md").write_text("")

    return track_dir, home_dir


def _write_graph_files(track_dir: Path):
    """Write sample graph and analysis JSON files."""
    file_graph = {
        "generated_at": "2026-04-15T10:00:00Z",
        "project_root": "/project",
        "stats": {"files": 2, "symbols": 3, "edges": 1, "languages": {"python": 2}},
        "nodes": [
            {"id": "src/app.py", "type": "file", "language": "python",
             "directory": "src", "symbols": [{"name": "main", "type": "function",
             "line_start": 1, "line_end": 3, "hash": "abc123"}], "lines": 10},
            {"id": "src/utils.py", "type": "file", "language": "python",
             "directory": "src", "symbols": [{"name": "helper", "type": "function",
             "line_start": 1, "line_end": 2, "hash": "def456"}], "lines": 5},
        ],
        "edges": [{"source": "src/app.py", "target": "src/utils.py", "type": "import"}],
    }
    symbol_graph = dict(file_graph)
    symbol_graph["edges"] = file_graph["edges"] + [
        {"source": "src/app.py::main", "target": "src/utils.py::helper", "type": "call"}
    ]

    (track_dir / "graph" / "file-graph.json").write_text(json.dumps(file_graph))
    (track_dir / "graph" / "symbol-graph.json").write_text(json.dumps(symbol_graph))

    duplicates = {
        "generated_at": "2026-04-15T10:00:00Z",
        "clusters": [],
        "stats": {"functions_analyzed": 3, "exact_clusters": 0,
                  "near_clusters": 0, "total_duplicate_lines": 0},
    }
    coverage = {
        "generated_at": "2026-04-15T10:00:00Z",
        "coverage": {"files_with_tests": 1, "files_without_tests": 1,
                     "functions_with_tests": 1, "functions_without_tests": 2,
                     "test_files": 1, "coverage_ratio": 0.5},
        "untested_files": [], "untested_functions": [], "suspicious_tests": [],
    }
    security = {
        "generated_at": "2026-04-15T10:00:00Z",
        "findings": [],
        "stats": {"files_scanned": 2, "findings_high": 0,
                  "findings_medium": 0, "findings_low": 0},
    }

    (track_dir / "analysis" / "duplicates.json").write_text(json.dumps(duplicates))
    (track_dir / "analysis" / "test-coverage.json").write_text(json.dumps(coverage))
    (track_dir / "analysis" / "security.json").write_text(json.dumps(security))


class TestGraphPage:
    def test_graph_page_renders(self, track_env):
        track_dir, _ = track_env
        _write_graph_files(track_dir)
        from agent_track.dashboard.render import render_graph_page
        html = render_graph_page()
        assert "<!DOCTYPE html>" in html
        assert "The Score" in html or "Graph" in html

    def test_graph_page_includes_d3_script(self, track_env):
        track_dir, _ = track_env
        _write_graph_files(track_dir)
        from agent_track.dashboard.render import render_graph_page
        html = render_graph_page()
        assert "d3" in html.lower() or "d3.js" in html.lower() or "d3-" in html


class TestGraphAPI:
    def test_api_graph_returns_file_graph(self, track_env):
        track_dir, _ = track_env
        _write_graph_files(track_dir)
        from agent_track.dashboard.server import _get_graph_data
        data = _get_graph_data("file")
        assert data is not None
        assert "nodes" in data
        assert len(data["nodes"]) == 2

    def test_api_graph_returns_symbol_graph(self, track_env):
        track_dir, _ = track_env
        _write_graph_files(track_dir)
        from agent_track.dashboard.server import _get_graph_data
        data = _get_graph_data("symbol")
        assert data is not None
        assert "edges" in data
        call_edges = [e for e in data["edges"] if e["type"] == "call"]
        assert len(call_edges) == 1

    def test_api_analysis_returns_duplicates(self, track_env):
        track_dir, _ = track_env
        _write_graph_files(track_dir)
        from agent_track.dashboard.server import _get_analysis_data
        data = _get_analysis_data("duplicates")
        assert data is not None
        assert "clusters" in data

    def test_api_analysis_returns_coverage(self, track_env):
        track_dir, _ = track_env
        _write_graph_files(track_dir)
        from agent_track.dashboard.server import _get_analysis_data
        data = _get_analysis_data("test-coverage")
        assert data is not None
        assert "coverage" in data

    def test_api_analysis_returns_security(self, track_env):
        track_dir, _ = track_env
        _write_graph_files(track_dir)
        from agent_track.dashboard.server import _get_analysis_data
        data = _get_analysis_data("security")
        assert data is not None
        assert "findings" in data

    def test_graph_data_matches_analyze_output(self, track_env):
        """Graph API data should match what track analyze writes."""
        track_dir, _ = track_env
        _write_graph_files(track_dir)
        from agent_track.dashboard.server import _get_graph_data
        data = _get_graph_data("file")
        raw = json.loads((track_dir / "graph" / "file-graph.json").read_text())
        assert data["stats"] == raw["stats"]
        assert len(data["nodes"]) == len(raw["nodes"])

    def test_api_graph_returns_none_when_missing(self, track_env):
        from agent_track.dashboard.server import _get_graph_data
        data = _get_graph_data("file")
        assert data is None

    def test_api_analysis_returns_none_when_missing(self, track_env):
        from agent_track.dashboard.server import _get_analysis_data
        data = _get_analysis_data("duplicates")
        assert data is None
