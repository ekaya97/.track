"""Tests for the static test coverage mapper."""

from __future__ import annotations

import pytest

from agent_track.analysis.coverage import analyze_coverage


def _files(*file_sources: tuple[str, str]) -> list[tuple[str, str]]:
    return list(file_sources)


class TestTestFileIdentification:
    def test_identifies_python_test_files(self):
        files = _files(
            ("tests/test_auth.py", "import auth\ndef test_login():\n    auth.login()\n"),
            ("src/auth.py", "def login():\n    pass\n"),
        )
        result = analyze_coverage(files)
        assert result["coverage"]["test_files"] == 1

    def test_identifies_js_test_files(self):
        files = _files(
            ("src/auth.test.js", "import { login } from './auth';\ntest('login', () => { login(); });\n"),
            ("src/auth.spec.ts", "import { login } from './auth';\ndescribe('auth', () => {});\n"),
            ("src/__tests__/auth.js", "const auth = require('../auth');\n"),
            ("src/auth.js", "function login() {}\n"),
        )
        result = analyze_coverage(files)
        assert result["coverage"]["test_files"] == 3


class TestCoverageMapping:
    def test_maps_test_imports_to_source(self):
        files = _files(
            ("src/auth.py", "def login():\n    pass\ndef logout():\n    pass\n"),
            ("tests/test_auth.py", "from auth import login\ndef test_login():\n    login()\n"),
        )
        result = analyze_coverage(files)
        assert result["coverage"]["files_with_tests"] >= 1

    def test_flags_untested_source_file(self):
        files = _files(
            ("src/auth.py", "def login():\n    pass\n"),
            ("src/middleware.py", "def rate_limit():\n    pass\n"),
            ("tests/test_auth.py", "from auth import login\ndef test_login():\n    login()\n"),
        )
        result = analyze_coverage(files)
        untested = [u["file"] for u in result["untested_files"]]
        assert "src/middleware.py" in untested
        assert "src/auth.py" not in untested

    def test_flags_untested_source_function(self):
        files = _files(
            ("src/auth.py", "def login():\n    pass\ndef logout():\n    pass\n"),
            ("tests/test_auth.py", "from auth import login\ndef test_login():\n    login()\n"),
        )
        result = analyze_coverage(files)
        untested_funcs = [
            (u["file"], u["name"]) for u in result["untested_functions"]
        ]
        assert ("src/auth.py", "logout") in untested_funcs

    def test_tested_function_not_flagged(self):
        files = _files(
            ("src/auth.py", "def login():\n    pass\n"),
            ("tests/test_auth.py", "from auth import login\ndef test_login():\n    login()\n"),
        )
        result = analyze_coverage(files)
        untested_funcs = [
            (u["file"], u["name"]) for u in result["untested_functions"]
        ]
        assert ("src/auth.py", "login") not in untested_funcs

    def test_flags_suspicious_test_name_mismatch(self):
        files = _files(
            ("src/auth.py", "def login():\n    pass\n"),
            ("tests/test_auth.py", "import os\ndef test_something():\n    os.getcwd()\n"),
        )
        result = analyze_coverage(files)
        suspicious = [s["test_file"] for s in result["suspicious_tests"]]
        assert "tests/test_auth.py" in suspicious

    def test_coverage_ratio_calculation(self):
        files = _files(
            ("src/a.py", "def func_a():\n    pass\n"),
            ("src/b.py", "def func_b():\n    pass\n"),
            ("tests/test_a.py", "from a import func_a\ndef test_a():\n    func_a()\n"),
        )
        result = analyze_coverage(files)
        ratio = result["coverage"]["coverage_ratio"]
        # 1 of 2 source files tested
        assert 0.0 < ratio < 1.0


class TestEdgeCases:
    def test_handles_no_test_files(self):
        files = _files(
            ("src/auth.py", "def login():\n    pass\n"),
        )
        result = analyze_coverage(files)
        assert result["coverage"]["test_files"] == 0
        assert result["coverage"]["coverage_ratio"] == 0.0

    def test_handles_no_source_files(self):
        files = _files(
            ("tests/test_auth.py", "def test_something():\n    pass\n"),
        )
        result = analyze_coverage(files)
        assert result["coverage"]["files_with_tests"] == 0
        assert result["coverage"]["files_without_tests"] == 0
