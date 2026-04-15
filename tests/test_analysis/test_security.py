"""Tests for the static security scanner."""

from __future__ import annotations

import pytest

from agent_track.analysis.security import scan_security


def _files(*file_sources: tuple[str, str]) -> list[tuple[str, str]]:
    return list(file_sources)


class TestHardcodedSecrets:
    def test_detect_aws_key_pattern(self):
        files = _files(
            ("src/config.py", 'AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n'),
        )
        result = scan_security(files)
        findings = result["findings"]
        assert any(
            f["type"] == "hardcoded_secret" and "AKIA" in f["pattern"]
            for f in findings
        )

    def test_detect_github_token_pattern(self):
        files = _files(
            ("src/config.py", 'GITHUB_TOKEN = "ghp_ABCDEFabcdef1234567890abcdef12345678"\n'),
        )
        result = scan_security(files)
        findings = result["findings"]
        assert any(
            f["type"] == "hardcoded_secret" and "ghp_" in f["pattern"]
            for f in findings
        )

    def test_detect_high_entropy_string(self):
        files = _files(
            ("src/config.py", 'SECRET = "aK3mZ9xQ2wR7nB5cV8jL4hF6gD0eY1pT"\n'),
        )
        result = scan_security(files)
        findings = result["findings"]
        assert any(f["type"] == "hardcoded_secret" for f in findings)

    def test_ignore_low_entropy_string(self):
        files = _files(
            ("src/config.py", 'NAME = "hello world this is a test"\n'),
        )
        result = scan_security(files)
        findings = [f for f in result["findings"] if f["type"] == "hardcoded_secret"]
        assert len(findings) == 0


class TestDangerousPatterns:
    def test_detect_eval_with_variable(self):
        files = _files(
            ("src/utils.py", "def run(code):\n    result = eval(code)\n"),
        )
        result = scan_security(files)
        findings = result["findings"]
        assert any(
            f["type"] == "dangerous_pattern" and "eval" in f["pattern"]
            for f in findings
        )

    def test_ignore_eval_with_literal(self):
        files = _files(
            ("src/utils.py", "result = eval('1 + 2')\n"),
        )
        result = scan_security(files)
        findings = [
            f for f in result["findings"]
            if f["type"] == "dangerous_pattern" and "eval" in f["pattern"]
        ]
        assert len(findings) == 0

    def test_detect_sql_injection_pattern(self):
        files = _files(
            ("src/db.py", 'def query(name):\n    sql = f"SELECT * FROM users WHERE name = {name}"\n'),
        )
        result = scan_security(files)
        findings = result["findings"]
        assert any(
            f["type"] == "dangerous_pattern" and "SQL" in f["pattern"]
            for f in findings
        )

    def test_detect_pickle_loads(self):
        files = _files(
            ("src/utils.py", "import pickle\ndef load(data):\n    return pickle.loads(data)\n"),
        )
        result = scan_security(files)
        findings = result["findings"]
        assert any(
            f["type"] == "dangerous_pattern" and "pickle" in f["pattern"].lower()
            for f in findings
        )

    def test_detect_unsafe_yaml_load(self):
        files = _files(
            ("src/config.py", "import yaml\ndef parse(text):\n    return yaml.load(text)\n"),
        )
        result = scan_security(files)
        findings = result["findings"]
        assert any(
            f["type"] == "dangerous_pattern" and "yaml" in f["pattern"].lower()
            for f in findings
        )


class TestFiltering:
    def test_skip_test_files(self):
        files = _files(
            ("tests/test_config.py", 'SECRET = "AKIAIOSFODNN7EXAMPLE"\n'),
        )
        result = scan_security(files)
        findings = [f for f in result["findings"] if f["type"] == "hardcoded_secret"]
        assert len(findings) == 0

    def test_skip_comments(self):
        files = _files(
            ("src/config.py", '# AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n'),
        )
        result = scan_security(files)
        findings = [f for f in result["findings"] if f["type"] == "hardcoded_secret"]
        assert len(findings) == 0


class TestOutput:
    def test_severity_levels_correct(self):
        files = _files(
            ("src/config.py", 'AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n'),
            ("src/utils.py", "def run(code):\n    result = eval(code)\n"),
        )
        result = scan_security(files)
        severities = {f["severity"] for f in result["findings"]}
        # AWS key should be high, eval should be medium
        assert "high" in severities

    def test_output_format(self):
        files = _files(
            ("src/config.py", 'AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n'),
        )
        result = scan_security(files)
        assert "generated_at" in result
        assert "findings" in result
        assert "stats" in result
        assert "files_scanned" in result["stats"]
        for f in result["findings"]:
            assert "type" in f
            assert "severity" in f
            assert "file" in f
            assert "line" in f
            assert "pattern" in f
