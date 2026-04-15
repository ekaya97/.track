"""Tests for graph assembly — combining parse results into unified graph JSON."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from agent_track.analysis.parsers.python_parser import (
    CallEdge,
    ImportEdge,
    ParseResult,
    Symbol,
    parse_python_file,
)
from agent_track.analysis.graph import assemble_file_graph, assemble_symbol_graph, run_analysis


def _pr(
    file_path: str,
    source: str,
) -> ParseResult:
    return parse_python_file(source, file_path)


class TestGraphAssembly:
    def test_assembles_nodes_from_parse_results(self):
        results = [
            _pr("src/app.py", "def main():\n    pass\n"),
            _pr("src/utils.py", "def helper():\n    pass\n"),
        ]
        graph = assemble_file_graph(results, "/project")
        node_ids = [n["id"] for n in graph["nodes"]]
        assert "src/app.py" in node_ids
        assert "src/utils.py" in node_ids

    def test_assembles_import_edges(self):
        results = [
            _pr("src/app.py", "from utils import helper\ndef main():\n    pass\n"),
            _pr("src/utils.py", "def helper():\n    pass\n"),
        ]
        graph = assemble_file_graph(results, "/project")
        import_edges = [e for e in graph["edges"] if e["type"] == "import"]
        assert any(
            e["source"] == "src/app.py" and e["target"] == "src/utils.py"
            for e in import_edges
        )

    def test_assembles_call_edges(self):
        results = [
            _pr("src/app.py", "def helper():\n    pass\ndef main():\n    helper()\n"),
        ]
        graph = assemble_symbol_graph(results, "/project")
        call_edges = [e for e in graph["edges"] if e["type"] == "call"]
        assert any(
            e["source"] == "src/app.py::main"
            and e["target"] == "src/app.py::helper"
            for e in call_edges
        )

    def test_deduplicates_edges(self):
        results = [
            _pr(
                "src/app.py",
                "def helper():\n    pass\n\ndef main():\n    helper()\n    helper()\n",
            ),
        ]
        graph = assemble_symbol_graph(results, "/project")
        call_edges = [
            e
            for e in graph["edges"]
            if e["type"] == "call"
            and e["source"] == "src/app.py::main"
            and e["target"] == "src/app.py::helper"
        ]
        assert len(call_edges) == 1

    def test_writes_file_graph_json(self, tmp_path):
        results = [_pr("src/app.py", "x = 1\n")]
        graph_dir = tmp_path / "graph"
        graph_dir.mkdir()
        run_analysis(results, str(tmp_path), graph_dir=graph_dir)
        fg = graph_dir / "file-graph.json"
        assert fg.exists()
        data = json.loads(fg.read_text())
        assert "nodes" in data
        assert "edges" in data

    def test_writes_symbol_graph_json(self, tmp_path):
        results = [_pr("src/app.py", "def main():\n    pass\n")]
        graph_dir = tmp_path / "graph"
        graph_dir.mkdir()
        run_analysis(results, str(tmp_path), graph_dir=graph_dir)
        sg = graph_dir / "symbol-graph.json"
        assert sg.exists()
        data = json.loads(sg.read_text())
        assert "nodes" in data
        assert "edges" in data

    def test_stats_counts_correct(self):
        results = [
            _pr("src/app.py", "import os\ndef main():\n    pass\n\nclass Foo:\n    pass\n"),
            _pr("src/utils.py", "def helper():\n    pass\n"),
        ]
        graph = assemble_file_graph(results, "/project")
        stats = graph["stats"]
        assert stats["files"] == 2
        assert stats["symbols"] >= 3  # main, Foo, helper
        assert stats["languages"]["python"] == 2

    def test_handles_empty_project(self):
        graph = assemble_file_graph([], "/project")
        assert graph["stats"]["files"] == 0
        assert graph["nodes"] == []
        assert graph["edges"] == []

    def test_performance_100_files_under_2s(self):
        """Assembling a graph from 100 parsed files should be fast."""
        results = []
        for i in range(100):
            src = f"import os\ndef func_{i}():\n    os.path.join('a', 'b')\n"
            results.append(_pr(f"src/mod_{i:03d}.py", src))
        start = time.monotonic()
        graph = assemble_symbol_graph(results, "/project")
        elapsed = time.monotonic() - start
        assert elapsed < 2.0
        assert graph["stats"]["files"] == 100
