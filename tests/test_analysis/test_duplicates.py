"""Tests for the deduplication engine."""

from __future__ import annotations

import pytest

from agent_track.analysis.duplicates import find_duplicates


def _make_files(*file_sources: tuple[str, str]) -> list[tuple[str, str]]:
    """Return list of (file_path, source) tuples."""
    return list(file_sources)


class TestExactDuplicates:
    def test_exact_duplicate_detected(self):
        """Identical functions in different files are detected as exact duplicates."""
        files = _make_files(
            ("src/auth.py", "def validate(token):\n    if not token:\n        raise ValueError('bad')\n    cleaned = token.strip()\n    return len(cleaned) > 0\n"),
            ("src/api.py", "def validate(token):\n    if not token:\n        raise ValueError('bad')\n    cleaned = token.strip()\n    return len(cleaned) > 0\n"),
        )
        result = find_duplicates(files)
        exact = [c for c in result["clusters"] if c["type"] == "exact"]
        assert len(exact) >= 1
        funcs = exact[0]["functions"]
        files_found = {f["file"] for f in funcs}
        assert "src/auth.py" in files_found
        assert "src/api.py" in files_found

    def test_renamed_variables_still_match(self):
        """Functions with different variable names but same structure match."""
        files = _make_files(
            ("src/a.py", "def check(x):\n    y = x + 1\n    if y > 10:\n        return True\n    return False\n"),
            ("src/b.py", "def verify(val):\n    result = val + 1\n    if result > 10:\n        return True\n    return False\n"),
        )
        result = find_duplicates(files)
        exact = [c for c in result["clusters"] if c["type"] == "exact"]
        assert len(exact) >= 1

    def test_different_literals_still_match(self):
        """Functions with different literal values but same structure match."""
        files = _make_files(
            ("src/a.py", "def greet(name):\n    msg = 'Hello ' + name\n    print(msg)\n    result = len(msg)\n    return result + 42\n"),
            ("src/b.py", "def welcome(user):\n    text = 'Welcome ' + user\n    print(text)\n    result = len(text)\n    return result + 99\n"),
        )
        result = find_duplicates(files)
        exact = [c for c in result["clusters"] if c["type"] == "exact"]
        assert len(exact) >= 1

    def test_different_logic_no_match(self):
        """Functions with different logic should NOT match."""
        files = _make_files(
            ("src/a.py", "def add(x, y):\n    result = x + y\n    checked = result > 0\n    logged = str(checked)\n    return result + 1\n"),
            ("src/b.py", "def multiply(x, y):\n    z = x * y\n    w = z ** 2\n    print(w)\n    return z - w\n"),
        )
        result = find_duplicates(files)
        exact = [c for c in result["clusters"] if c["type"] == "exact"]
        # These two should not be in the same cluster
        for cluster in exact:
            files_in_cluster = {f["file"] for f in cluster["functions"]}
            assert not ({"src/a.py", "src/b.py"} <= files_in_cluster)


class TestNearDuplicates:
    def test_near_duplicate_detected(self):
        """Functions with >80% structural similarity are flagged as near duplicates."""
        files = _make_files(
            (
                "src/a.py",
                "def process(data):\n    result = []\n    for item in data:\n        if item > 0:\n            result.append(item)\n    return result\n",
            ),
            (
                "src/b.py",
                "def filter_pos(data):\n    result = []\n    for item in data:\n        if item > 0:\n            result.append(item)\n    return sorted(result)\n",
            ),
        )
        result = find_duplicates(files)
        near = [c for c in result["clusters"] if c["type"] == "near"]
        # Should find a near duplicate (the only difference is sorted() call)
        assert len(near) >= 1
        assert near[0]["similarity"] > 0.85


class TestFiltering:
    def test_trivial_functions_skipped(self):
        """Functions with < 5 lines should be skipped."""
        files = _make_files(
            ("src/a.py", "def tiny(x):\n    y = x + 1\n    return y\n"),
            ("src/b.py", "def tiny(x):\n    y = x + 1\n    return y\n"),
        )
        result = find_duplicates(files)
        # Trivial functions should not appear in clusters
        assert len(result["clusters"]) == 0

    def test_size_filter_prevents_false_matches(self):
        """Functions with very different sizes should not be compared for near-dups."""
        files = _make_files(
            ("src/a.py", "def short(x):\n    y = x + 1\n    return y\n"),
            (
                "src/b.py",
                "def long(x):\n    a = x + 1\n    b = a + 2\n    c = b + 3\n    d = c + 4\n    e = d + 5\n    f = e + 6\n    g = f + 7\n    h = g + 8\n    return h\n",
            ),
        )
        result = find_duplicates(files)
        near = [c for c in result["clusters"] if c["type"] == "near"]
        # Should not be flagged as near duplicates due to size difference
        assert len(near) == 0


class TestOutput:
    def test_output_format_correct(self):
        files = _make_files(
            ("src/a.py", "def check(x):\n    y = x + 1\n    if y > 10:\n        return True\n    return False\n"),
            ("src/b.py", "def verify(val):\n    result = val + 1\n    if result > 10:\n        return True\n    return False\n"),
        )
        result = find_duplicates(files)
        assert "generated_at" in result
        assert "clusters" in result
        assert "stats" in result
        assert isinstance(result["clusters"], list)

    def test_suggested_action_present(self):
        files = _make_files(
            ("src/a.py", "def check(x):\n    y = x + 1\n    if y > 10:\n        return True\n    return False\n"),
            ("src/b.py", "def verify(val):\n    result = val + 1\n    if result > 10:\n        return True\n    return False\n"),
        )
        result = find_duplicates(files)
        for cluster in result["clusters"]:
            assert "suggested_action" in cluster
            assert len(cluster["suggested_action"]) > 0

    def test_stats_accurate(self):
        files = _make_files(
            ("src/a.py", "def check(x):\n    y = x + 1\n    if y > 10:\n        return True\n    return False\n"),
            ("src/b.py", "def verify(val):\n    result = val + 1\n    if result > 10:\n        return True\n    return False\n"),
            ("src/c.py", "def unrelated(z):\n    for i in range(z):\n        print(i)\n    total = z * 2\n    return total\n"),
        )
        result = find_duplicates(files)
        stats = result["stats"]
        assert stats["functions_analyzed"] == 3
        assert stats["exact_clusters"] >= 1

    def test_handles_syntax_errors_in_functions(self):
        """Files with syntax errors should be skipped gracefully."""
        files = _make_files(
            ("src/good.py", "def check(x):\n    y = x + 1\n    if y > 10:\n        return True\n    return False\n"),
            ("src/bad.py", "def broken(\n    missing colon"),
        )
        result = find_duplicates(files)
        # Should not crash, and should still analyze the good file
        assert result["stats"]["functions_analyzed"] >= 1
