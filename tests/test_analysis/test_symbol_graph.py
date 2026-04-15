"""Tests for symbol-level graph resolution across files."""

from __future__ import annotations

import pytest

from agent_track.analysis.parsers.python_parser import (
    ParseResult,
    parse_python_file,
)
from agent_track.analysis.symbol_graph import ResolvedCallEdge, resolve_symbol_graph


def _make_results(*file_sources: tuple[str, str]) -> list[ParseResult]:
    """Parse multiple (file_path, source) pairs into ParseResults."""
    return [parse_python_file(src, fp) for fp, src in file_sources]


class TestSymbolGraph:
    def test_direct_call_edge(self):
        """Direct call within the same file resolves to file::function."""
        results = _make_results(
            (
                "src/app.py",
                (
                    "def helper():\n"
                    "    pass\n"
                    "\n"
                    "def main():\n"
                    "    helper()\n"
                ),
            ),
        )
        edges = resolve_symbol_graph(results)
        assert any(
            e.caller == "src/app.py::main"
            and e.callee == "src/app.py::helper"
            for e in edges
        )

    def test_attribute_call_edge(self):
        """Module attribute calls resolve via import table."""
        results = _make_results(
            (
                "src/app.py",
                (
                    "import db\n"
                    "\n"
                    "def main():\n"
                    "    db.connect()\n"
                ),
            ),
            (
                "src/db.py",
                "def connect():\n    pass\n",
            ),
        )
        edges = resolve_symbol_graph(results)
        assert any(
            e.caller == "src/app.py::main"
            and e.callee == "src/db.py::connect"
            for e in edges
        )

    def test_method_call_within_class(self):
        """self.method() resolves to the same class."""
        results = _make_results(
            (
                "src/service.py",
                (
                    "class Service:\n"
                    "    def validate(self):\n"
                    "        pass\n"
                    "    def run(self):\n"
                    "        self.validate()\n"
                ),
            ),
        )
        edges = resolve_symbol_graph(results)
        assert any(
            e.caller == "src/service.py::Service.run"
            and e.callee == "src/service.py::Service.validate"
            for e in edges
        )

    def test_imported_function_call_resolved(self):
        """from auth import refresh_token; refresh_token() resolves across files."""
        results = _make_results(
            (
                "src/app.py",
                (
                    "from auth import refresh_token\n"
                    "\n"
                    "def main():\n"
                    "    refresh_token()\n"
                ),
            ),
            (
                "src/auth.py",
                "def refresh_token():\n    pass\n",
            ),
        )
        edges = resolve_symbol_graph(results)
        assert any(
            e.caller == "src/app.py::main"
            and e.callee == "src/auth.py::refresh_token"
            for e in edges
        )

    def test_unresolved_call_creates_dangling_edge(self):
        """Calls to unknown functions get target ?::name."""
        results = _make_results(
            (
                "src/app.py",
                (
                    "def main():\n"
                    "    unknown_func()\n"
                ),
            ),
        )
        edges = resolve_symbol_graph(results)
        assert any(
            e.caller == "src/app.py::main"
            and e.callee == "?::unknown_func"
            for e in edges
        )

    def test_nested_function_calls(self):
        """Calls inside nested expressions are captured."""
        results = _make_results(
            (
                "src/app.py",
                (
                    "def process():\n"
                    "    pass\n"
                    "\n"
                    "def transform():\n"
                    "    pass\n"
                    "\n"
                    "def main():\n"
                    "    result = transform(process())\n"
                ),
            ),
        )
        edges = resolve_symbol_graph(results)
        callers_callees = [(e.caller, e.callee) for e in edges]
        assert ("src/app.py::main", "src/app.py::process") in callers_callees
        assert ("src/app.py::main", "src/app.py::transform") in callers_callees

    def test_call_inside_conditional(self):
        """Calls inside if/else blocks are still captured."""
        results = _make_results(
            (
                "src/app.py",
                (
                    "def check():\n"
                    "    pass\n"
                    "\n"
                    "def main():\n"
                    "    if True:\n"
                    "        check()\n"
                ),
            ),
        )
        edges = resolve_symbol_graph(results)
        assert any(
            e.caller == "src/app.py::main"
            and e.callee == "src/app.py::check"
            for e in edges
        )

    def test_no_duplicate_edges(self):
        """Multiple calls to the same function produce only one edge."""
        results = _make_results(
            (
                "src/app.py",
                (
                    "def helper():\n"
                    "    pass\n"
                    "\n"
                    "def main():\n"
                    "    helper()\n"
                    "    helper()\n"
                    "    helper()\n"
                ),
            ),
        )
        edges = resolve_symbol_graph(results)
        matching = [
            e
            for e in edges
            if e.caller == "src/app.py::main"
            and e.callee == "src/app.py::helper"
        ]
        assert len(matching) == 1
