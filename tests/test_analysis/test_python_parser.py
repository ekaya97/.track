"""Tests for Python AST parser — imports, symbols, and call edges."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_track.analysis.parsers.python_parser import (
    CallEdge,
    ImportEdge,
    ParseResult,
    Symbol,
    parse_python_file,
    resolve_relative_import,
)


def _parse(source: str, file_path: str = "src/example.py") -> ParseResult:
    """Helper: parse a source string as if it came from file_path."""
    return parse_python_file(source, file_path)


# ── Import extraction ─────────────────────────────────────────────────────────


class TestImportExtraction:
    def test_extract_import_statement(self):
        result = _parse("import os\nimport sys\n")
        assert len(result.imports) == 2
        assert any(e.target_module == "os" for e in result.imports)
        assert any(e.target_module == "sys" for e in result.imports)

    def test_extract_from_import(self):
        result = _parse("from os.path import join, exists\n")
        assert len(result.imports) == 1
        edge = result.imports[0]
        assert edge.target_module == "os.path"
        assert "join" in edge.names
        assert "exists" in edge.names

    def test_extract_relative_import(self):
        result = _parse("from . import sibling\n", file_path="src/pkg/mod.py")
        assert len(result.imports) == 1
        edge = result.imports[0]
        assert edge.level == 1
        assert "sibling" in edge.names

    def test_extract_multiple_import_styles(self):
        source = (
            "import json\n"
            "from pathlib import Path\n"
            "from . import utils\n"
        )
        result = _parse(source, file_path="src/pkg/mod.py")
        assert len(result.imports) == 3


# ── Relative import resolution ────────────────────────────────────────────────


class TestRelativeImportResolution:
    def test_resolve_relative_import_single_dot(self):
        # from . import sibling  (in src/pkg/mod.py → src/pkg)
        resolved = resolve_relative_import(
            file_path="src/pkg/mod.py", level=1, module=None
        )
        assert resolved == "src.pkg"

    def test_resolve_relative_import_double_dot(self):
        # from ..utils import helper  (in src/pkg/sub/mod.py → src/pkg)
        resolved = resolve_relative_import(
            file_path="src/pkg/sub/mod.py", level=2, module="utils"
        )
        assert resolved == "src.pkg.utils"

    def test_resolve_relative_import_with_module(self):
        # from .utils import helper  (in src/pkg/mod.py → src/pkg.utils)
        resolved = resolve_relative_import(
            file_path="src/pkg/mod.py", level=1, module="utils"
        )
        assert resolved == "src.pkg.utils"

    def test_resolve_relative_import_top_level(self):
        # from . import foo  (in mod.py → top level)
        resolved = resolve_relative_import(
            file_path="mod.py", level=1, module=None
        )
        assert resolved == ""


# ── Symbol extraction ─────────────────────────────────────────────────────────


class TestSymbolExtraction:
    def test_extract_function_def(self):
        source = "def hello():\n    return 'world'\n"
        result = _parse(source)
        funcs = [s for s in result.symbols if s.type == "function"]
        assert len(funcs) == 1
        assert funcs[0].name == "hello"

    def test_extract_async_function_def(self):
        source = "async def fetch_data():\n    await something()\n"
        result = _parse(source)
        funcs = [s for s in result.symbols if s.type == "async_function"]
        assert len(funcs) == 1
        assert funcs[0].name == "fetch_data"

    def test_extract_class_def(self):
        source = (
            "class MyClass(Base):\n"
            "    def method(self):\n"
            "        pass\n"
        )
        result = _parse(source)
        classes = [s for s in result.symbols if s.type == "class"]
        assert len(classes) == 1
        cls = classes[0]
        assert cls.name == "MyClass"
        assert "Base" in cls.bases

    def test_extract_class_methods(self):
        source = (
            "class Foo:\n"
            "    def bar(self):\n"
            "        pass\n"
            "    async def baz(self):\n"
            "        pass\n"
        )
        result = _parse(source)
        cls = [s for s in result.symbols if s.type == "class"][0]
        assert "bar" in cls.methods
        assert "baz" in cls.methods

    def test_extract_module_constants(self):
        source = "MAX_RETRIES = 3\nDEFAULT_TIMEOUT = 30\n"
        result = _parse(source)
        consts = [s for s in result.symbols if s.type == "constant"]
        names = {c.name for c in consts}
        assert "MAX_RETRIES" in names
        assert "DEFAULT_TIMEOUT" in names

    def test_symbol_includes_line_range(self):
        source = (
            "x = 1\n"              # line 1
            "\n"                    # line 2
            "def foo():\n"          # line 3
            "    a = 1\n"           # line 4
            "    return a\n"        # line 5
        )
        result = _parse(source)
        func = [s for s in result.symbols if s.name == "foo"][0]
        assert func.line_start == 3
        assert func.line_end == 5

    def test_extract_decorated_function(self):
        source = (
            "@staticmethod\n"
            "def helper():\n"
            "    pass\n"
        )
        result = _parse(source)
        func = [s for s in result.symbols if s.name == "helper"][0]
        assert "staticmethod" in func.decorators


# ── Call edge extraction ──────────────────────────────────────────────────────


class TestCallExtraction:
    def test_extract_function_calls(self):
        source = (
            "def main():\n"
            "    result = process(data)\n"
            "    save(result)\n"
        )
        result = _parse(source)
        call_names = [c.callee for c in result.calls]
        assert "process" in call_names
        assert "save" in call_names

    def test_extract_method_calls(self):
        source = (
            "class Foo:\n"
            "    def run(self):\n"
            "        self.validate()\n"
            "        self.save()\n"
        )
        result = _parse(source)
        call_names = [c.callee for c in result.calls]
        assert "self.validate" in call_names
        assert "self.save" in call_names

    def test_extract_attribute_call(self):
        source = (
            "def main():\n"
            "    db.connect()\n"
            "    os.path.join('a', 'b')\n"
        )
        result = _parse(source)
        call_names = [c.callee for c in result.calls]
        assert "db.connect" in call_names
        assert "os.path.join" in call_names


# ── Error handling & edge cases ───────────────────────────────────────────────


class TestEdgeCases:
    def test_syntax_error_file_skipped_gracefully(self):
        source = "def broken(\n    # missing closing paren and colon"
        result = _parse(source)
        assert len(result.symbols) == 0
        assert len(result.imports) == 0
        assert len(result.parse_errors) > 0

    def test_empty_file_returns_empty_result(self):
        result = _parse("")
        assert result.file_path == "src/example.py"
        assert result.language == "python"
        assert result.imports == []
        assert result.symbols == []
        assert result.calls == []
        assert result.lines == 0
        assert result.parse_errors == []

    def test_parse_result_counts_lines(self):
        source = "a = 1\nb = 2\nc = 3\n"
        result = _parse(source)
        assert result.lines == 3
