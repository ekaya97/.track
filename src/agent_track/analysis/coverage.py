"""Static test coverage mapper — map tests to source without running them."""

from __future__ import annotations

import ast
import re
from datetime import datetime, timezone
from pathlib import PurePosixPath

# ── Test file patterns ────────────────────────────────────────────────────────

_PY_TEST_PATTERNS = [
    re.compile(r"(^|/)test_[^/]+\.py$"),    # test_*.py
    re.compile(r"(^|/)[^/]+_test\.py$"),     # *_test.py
    re.compile(r"(^|/)tests/[^/]+\.py$"),    # tests/*.py
]

_JS_TEST_PATTERNS = [
    re.compile(r"\.test\.[jt]sx?$"),         # *.test.js, *.test.ts, etc.
    re.compile(r"\.spec\.[jt]sx?$"),         # *.spec.js, *.spec.ts, etc.
    re.compile(r"__tests__/[^/]+\.[jt]sx?$"),  # __tests__/*.js
]


def _is_test_file(path: str) -> bool:
    for pat in _PY_TEST_PATTERNS + _JS_TEST_PATTERNS:
        if pat.search(path):
            return True
    return False


def _is_source_file(path: str) -> bool:
    return path.endswith(".py") and not _is_test_file(path)


# ── Import and call extraction (lightweight) ─────────────────────────────────


def _extract_imports_and_calls(source: str) -> tuple[set[str], set[str]]:
    """Extract imported module names and called function names from Python source."""
    imports: set[str] = set()
    calls: set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return imports, calls

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
                imports.add(alias.name)  # full dotted path
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split(".")[0])
                imports.add(node.module)  # full dotted path
            for alias in node.names:
                calls.add(alias.name)  # imported names are potential calls
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)

    return imports, calls


def _infer_tested_module(test_path: str) -> str | None:
    """Infer what module a test file is meant to test from its name.

    tests/test_auth.py → auth
    test_auth.py → auth
    """
    stem = PurePosixPath(test_path).stem
    if stem.startswith("test_"):
        return stem[5:]
    if stem.endswith("_test"):
        return stem[:-5]
    return None


# ── Main entry point ─────────────────────────────────────────────────────────


def analyze_coverage(files: list[tuple[str, str]]) -> dict:
    """Analyze static test coverage across files.

    Args:
        files: List of (file_path, source_code) tuples.

    Returns:
        Coverage analysis dict with untested files/functions and suspicious tests.
    """
    test_files: list[tuple[str, str]] = []
    source_files: list[tuple[str, str]] = []

    for path, source in files:
        if _is_test_file(path):
            test_files.append((path, source))
        elif _is_source_file(path):
            source_files.append((path, source))

    # Parse source files for functions
    source_functions: dict[str, list[dict]] = {}  # file → [{name, line_start, line_end}]
    source_module_names: dict[str, str] = {}  # module_name → file_path
    for path, source in source_files:
        p = PurePosixPath(path)
        stem = p.stem
        source_module_names[stem] = path
        # Register full dotted path: src/agent_track/cli.py → agent_track.cli
        dotted = str(p.with_suffix("")).replace("/", ".")
        source_module_names[dotted] = path
        # Also without common prefix: src.agent_track.cli → agent_track.cli
        for prefix in ("src.",):
            if dotted.startswith(prefix):
                source_module_names[dotted[len(prefix):]] = path
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        funcs = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs.append({
                    "name": node.name,
                    "line_start": node.lineno,
                    "line_end": node.end_lineno or node.lineno,
                })
        source_functions[path] = funcs

    # Analyze test files
    tested_source_files: set[str] = set()
    tested_functions: set[tuple[str, str]] = set()  # (file, func_name)
    suspicious_tests: list[dict] = []

    for test_path, test_source in test_files:
        if not test_path.endswith(".py"):
            # JS/TS test files count but we don't parse them deeply
            continue

        imports, calls = _extract_imports_and_calls(test_source)

        # Check which source modules this test imports
        imported_source_files: set[str] = set()
        for mod_name in imports:
            if mod_name in source_module_names:
                sf = source_module_names[mod_name]
                imported_source_files.add(sf)
                tested_source_files.add(sf)

        # Check which source functions this test calls
        for sf in imported_source_files:
            for func in source_functions.get(sf, []):
                if func["name"] in calls:
                    tested_functions.add((sf, func["name"]))

        # Check for suspicious tests (name suggests a module but doesn't import it)
        expected_module = _infer_tested_module(test_path)
        if expected_module and expected_module in source_module_names:
            expected_file = source_module_names[expected_module]
            if expected_file not in imported_source_files:
                suspicious_tests.append({
                    "test_file": test_path,
                    "expected_import": expected_file,
                    "reason": f"name suggests {expected_module} but doesn't import it",
                })

    # Count JS/TS test files
    js_test_count = sum(
        1 for p, _ in test_files if not p.endswith(".py")
    )

    # Build untested lists
    untested_files = []
    for path, _ in source_files:
        if path not in tested_source_files:
            func_names = [f["name"] for f in source_functions.get(path, [])]
            untested_files.append({"file": path, "functions": func_names})

    untested_functions = []
    for path in tested_source_files:
        for func in source_functions.get(path, []):
            if (path, func["name"]) not in tested_functions:
                untested_functions.append({
                    "file": path,
                    "name": func["name"],
                    "line_start": func["line_start"],
                    "line_end": func["line_end"],
                })

    # Coverage ratio
    total_source = len(source_files)
    files_with_tests = len(tested_source_files)
    coverage_ratio = files_with_tests / total_source if total_source > 0 else 0.0

    total_funcs = sum(len(fl) for fl in source_functions.values())
    funcs_with_tests = len(tested_functions)
    funcs_without_tests = total_funcs - funcs_with_tests

    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "coverage": {
            "files_with_tests": files_with_tests,
            "files_without_tests": total_source - files_with_tests,
            "functions_with_tests": funcs_with_tests,
            "functions_without_tests": funcs_without_tests,
            "test_files": len(test_files),
            "coverage_ratio": round(coverage_ratio, 2),
        },
        "untested_files": untested_files,
        "untested_functions": untested_functions,
        "suspicious_tests": suspicious_tests,
    }
