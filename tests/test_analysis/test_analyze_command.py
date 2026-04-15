"""Tests for track analyze command scaffolding and directory walker."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def track_dir(tmp_path):
    """Provide a temp directory with TRACK_DIR and TRACK_HOME set."""
    env = os.environ.copy()
    env["TRACK_DIR"] = str(tmp_path / ".track")
    env["TRACK_HOME"] = str(tmp_path / ".track-home")
    return tmp_path, env


@pytest.fixture
def initialized(track_dir):
    """Provide an initialized .track/ environment with a project tree."""
    tmp_path, env = track_dir
    _run(["init"], env, cwd=tmp_path)
    return tmp_path, env


def _run(
    args: list[str], env: dict, cwd: Path | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "agent_track.cli", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
    )


def _make_project_tree(root: Path) -> None:
    """Create a realistic project tree for testing the walker."""
    # Python files
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.py").write_text("import os\n")
    (root / "src" / "utils.py").write_text("def helper(): pass\n")
    (root / "src" / "sub").mkdir()
    (root / "src" / "sub" / "__init__.py").write_text("")
    (root / "src" / "sub" / "module.py").write_text("x = 1\n")

    # JS/TS files
    (root / "frontend").mkdir()
    (root / "frontend" / "app.js").write_text("console.log('hi');\n")
    (root / "frontend" / "App.tsx").write_text("export default App;\n")
    (root / "frontend" / "utils.mjs").write_text("export const x = 1;\n")
    (root / "frontend" / "types.ts").write_text("type Foo = string;\n")
    (root / "frontend" / "legacy.jsx").write_text("const C = () => <div/>;\n")

    # Directories that should be skipped
    (root / "node_modules" / "pkg").mkdir(parents=True)
    (root / "node_modules" / "pkg" / "index.js").write_text("module.exports = {};\n")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "foo.cpython-311.pyc").write_bytes(b"\x00")
    (root / ".venv" / "lib").mkdir(parents=True)
    (root / ".venv" / "lib" / "site.py").write_text("")
    (root / "venv" / "lib").mkdir(parents=True)
    (root / "venv" / "lib" / "site.py").write_text("")
    (root / ".git" / "objects").mkdir(parents=True)
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n")

    # Non-code files (should not appear in language detection)
    (root / "README.md").write_text("# Hello\n")
    (root / "data.json").write_text("{}\n")


class TestAnalyzeCommand:
    def test_analyze_creates_graph_directory(self, initialized):
        tmp_path, env = initialized
        _make_project_tree(tmp_path)
        result = _run(["analyze"], env, cwd=tmp_path)
        assert result.returncode == 0
        graph_dir = tmp_path / ".track" / "graph"
        assert graph_dir.is_dir()

    def test_analyze_creates_analysis_directory(self, initialized):
        tmp_path, env = initialized
        _make_project_tree(tmp_path)
        result = _run(["analyze"], env, cwd=tmp_path)
        assert result.returncode == 0
        analysis_dir = tmp_path / ".track" / "analysis"
        assert analysis_dir.is_dir()

    def test_analyze_respects_gitignore(self, initialized):
        """Files matching .gitignore patterns should be excluded."""
        tmp_path, env = initialized
        _make_project_tree(tmp_path)

        # Write a .gitignore that excludes *.log files
        (tmp_path / ".gitignore").write_text("*.log\nbuild/\n")
        (tmp_path / "debug.log").write_text("log data")
        (tmp_path / "build").mkdir()
        (tmp_path / "build" / "output.py").write_text("x = 1\n")

        result = _run(["analyze", "--format", "json"], env, cwd=tmp_path)
        assert result.returncode == 0
        # The output should not include ignored files
        assert "debug.log" not in result.stdout
        assert "build/output.py" not in result.stdout
        # But should include non-ignored files
        assert "src/main.py" in result.stdout

    def test_analyze_skips_track_dir(self, initialized):
        """The .track/ directory itself should never be walked."""
        tmp_path, env = initialized
        _make_project_tree(tmp_path)

        # Put a Python file inside .track/ that should not be found
        (tmp_path / ".track" / "sneaky.py").write_text("x = 1\n")

        result = _run(["analyze", "--format", "json"], env, cwd=tmp_path)
        assert result.returncode == 0
        assert "sneaky.py" not in result.stdout

    def test_analyze_detects_python_files(self, initialized):
        """Walker should find .py files."""
        tmp_path, env = initialized
        _make_project_tree(tmp_path)

        result = _run(["analyze", "--format", "json"], env, cwd=tmp_path)
        assert result.returncode == 0
        assert "src/main.py" in result.stdout
        assert "src/utils.py" in result.stdout
        assert "src/sub/module.py" in result.stdout

    def test_analyze_detects_js_ts_files(self, initialized):
        """Walker should find .js, .jsx, .mjs, .ts, .tsx files."""
        tmp_path, env = initialized
        _make_project_tree(tmp_path)

        result = _run(["analyze", "--format", "json"], env, cwd=tmp_path)
        assert result.returncode == 0
        assert "frontend/app.js" in result.stdout
        assert "frontend/App.tsx" in result.stdout
        assert "frontend/utils.mjs" in result.stdout
        assert "frontend/types.ts" in result.stdout
        assert "frontend/legacy.jsx" in result.stdout


class TestLanguageDetection:
    def test_language_detection_by_extension(self):
        from agent_track.analysis import detect_language

        assert detect_language(Path("foo.py")) == "python"
        assert detect_language(Path("bar.js")) == "javascript"
        assert detect_language(Path("baz.jsx")) == "javascript"
        assert detect_language(Path("qux.mjs")) == "javascript"
        assert detect_language(Path("hello.ts")) == "typescript"
        assert detect_language(Path("world.tsx")) == "typescript"
        assert detect_language(Path("readme.md")) is None
        assert detect_language(Path("data.json")) is None

    def test_language_detection_case_insensitive(self):
        from agent_track.analysis import detect_language

        assert detect_language(Path("Foo.PY")) == "python"
        assert detect_language(Path("Bar.JS")) == "javascript"
        assert detect_language(Path("Baz.TS")) == "typescript"


class TestDirectoryWalker:
    def test_directory_walker_returns_sorted_files(self, tmp_path):
        """Walked files should be sorted by relative path."""
        from agent_track.analysis import walk_project

        (tmp_path / "b.py").write_text("x = 1\n")
        (tmp_path / "a.py").write_text("x = 2\n")
        (tmp_path / "c").mkdir()
        (tmp_path / "c" / "d.py").write_text("x = 3\n")

        files = walk_project(tmp_path)
        rel_paths = [str(f.relative_to(tmp_path)) for f in files]
        assert rel_paths == sorted(rel_paths)

    def test_directory_walker_skips_default_dirs(self, tmp_path):
        """Default skip dirs: .track/, .git/, node_modules/, __pycache__/, venv/, .venv/."""
        from agent_track.analysis import walk_project

        (tmp_path / "good.py").write_text("x = 1\n")
        for d in [".track", ".git", "node_modules", "__pycache__", "venv", ".venv"]:
            p = tmp_path / d
            p.mkdir(parents=True, exist_ok=True)
            (p / "bad.py").write_text("x = 1\n")

        files = walk_project(tmp_path)
        rel = [str(f.relative_to(tmp_path)) for f in files]
        assert "good.py" in rel
        for d in [".track", ".git", "node_modules", "__pycache__", "venv", ".venv"]:
            assert not any(r.startswith(d) for r in rel), f"{d}/ should be skipped"

    def test_directory_walker_respects_gitignore(self, tmp_path):
        """Walker should parse .gitignore and skip matching files."""
        from agent_track.analysis import walk_project

        (tmp_path / ".gitignore").write_text("*.log\nbuild/\n")
        (tmp_path / "app.py").write_text("x = 1\n")
        (tmp_path / "debug.log").write_text("log stuff")
        (tmp_path / "build").mkdir()
        (tmp_path / "build" / "out.py").write_text("x = 1\n")

        files = walk_project(tmp_path)
        rel = [str(f.relative_to(tmp_path)) for f in files]
        assert "app.py" in rel
        assert "debug.log" not in rel
        assert "build/out.py" not in rel

    def test_directory_walker_only_returns_code_files(self, tmp_path):
        """Walker should only return files with known code extensions."""
        from agent_track.analysis import walk_project

        (tmp_path / "app.py").write_text("x = 1\n")
        (tmp_path / "readme.md").write_text("# hi\n")
        (tmp_path / "data.json").write_text("{}\n")
        (tmp_path / "style.css").write_text("body {}\n")
        (tmp_path / "index.js").write_text("x = 1;\n")

        files = walk_project(tmp_path)
        rel = [str(f.relative_to(tmp_path)) for f in files]
        assert "app.py" in rel
        assert "index.js" in rel
        assert "readme.md" not in rel
        assert "data.json" not in rel
        assert "style.css" not in rel

    def test_directory_walker_handles_nested_gitignore(self, tmp_path):
        """Nested .gitignore files should be respected in their scope."""
        from agent_track.analysis import walk_project

        (tmp_path / ".gitignore").write_text("*.log\n")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("x = 1\n")
        (tmp_path / "src" / "generated.py").write_text("x = 2\n")
        (tmp_path / "src" / ".gitignore").write_text("generated.py\n")

        files = walk_project(tmp_path)
        rel = [str(f.relative_to(tmp_path)) for f in files]
        assert "src/app.py" in rel
        assert "src/generated.py" not in rel

    def test_directory_walker_empty_project(self, tmp_path):
        """Walker returns empty list for project with no code files."""
        from agent_track.analysis import walk_project

        (tmp_path / "readme.md").write_text("# hi\n")
        files = walk_project(tmp_path)
        assert files == []
