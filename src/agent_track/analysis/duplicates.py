"""Deduplication engine — find exact and near-duplicate functions."""

from __future__ import annotations

import ast
import hashlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone


# ── Minimum function size (lines) to consider ────────────────────────────────
MIN_LINES = 5

# ── Near-duplicate similarity threshold ───────────────────────────────────────
NEAR_THRESHOLD = 0.85

# ── Paths to skip (test files produce noisy near-duplicates) ──────────────────
import re
_TEST_PATH_RE = re.compile(
    r"(^|/)(test_|tests/|__tests__/)|(_test|\.test|\.spec)\.[^/]+$"
)


# ── AST normalization ────────────────────────────────────────────────────────


class _Normalizer(ast.NodeTransformer):
    """Normalize an AST subtree for structural comparison.

    - Replace variable names with positional placeholders (_v0, _v1, ...)
    - Replace literals with type placeholders (_STR, _INT, _FLOAT, _BOOL)
    - Remove docstrings and type annotations
    """

    def __init__(self) -> None:
        self._name_map: dict[str, str] = {}
        self._counter = 0

    def _get_placeholder(self, name: str) -> str:
        if name not in self._name_map:
            self._name_map[name] = f"_v{self._counter}"
            self._counter += 1
        return self._name_map[name]

    def visit_Name(self, node: ast.Name) -> ast.Name:
        node.id = self._get_placeholder(node.id)
        return self.generic_visit(node)

    def visit_arg(self, node: ast.arg) -> ast.arg:
        node.arg = self._get_placeholder(node.arg)
        node.annotation = None
        return self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        node.name = "_func"
        node.decorator_list = []
        node.returns = None
        # Remove docstring
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            node.body = node.body[1:]
        return self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_Constant(self, node: ast.Constant) -> ast.Constant:
        if isinstance(node.value, str):
            node.value = "_STR"
        elif isinstance(node.value, bool):
            node.value = "_BOOL"
        elif isinstance(node.value, int):
            node.value = "_INT"
        elif isinstance(node.value, float):
            node.value = "_FLOAT"
        return node

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AnnAssign:
        node.annotation = ast.Constant(value="_TYPE")
        return self.generic_visit(node)


def _normalize_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Normalize a function AST node and return its string representation."""
    import copy

    normalized = _Normalizer().visit(copy.deepcopy(node))
    ast.fix_missing_locations(normalized)
    return ast.dump(normalized, annotate_fields=False)


def _structural_hash(normalized: str) -> str:
    """Compute SHA-256 hash of a normalized AST representation."""
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


# ── Near-duplicate comparison ─────────────────────────────────────────────────


def _tree_tokens(dump: str) -> list[str]:
    """Tokenize an AST dump into comparable tokens."""
    # Split on parentheses and commas for a rough token list
    result: list[str] = []
    current = ""
    for ch in dump:
        if ch in "(),[] ":
            if current:
                result.append(current)
                current = ""
        else:
            current += ch
    if current:
        result.append(current)
    return result


def _similarity(tokens_a: list[str], tokens_b: list[str]) -> float:
    """Compute similarity between two token lists using LCS ratio."""
    if not tokens_a or not tokens_b:
        return 0.0
    # Use a simplified LCS-length approach for speed
    m, n = len(tokens_a), len(tokens_b)
    # For very long functions, use sampling to stay fast
    if m > 500 or n > 500:
        # Sample approach: compare first 500 tokens
        tokens_a = tokens_a[:500]
        tokens_b = tokens_b[:500]
        m, n = len(tokens_a), len(tokens_b)

    # Optimized LCS using two rows
    prev = [0] * (n + 1)
    for i in range(1, m + 1):
        curr = [0] * (n + 1)
        for j in range(1, n + 1):
            if tokens_a[i - 1] == tokens_b[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = max(prev[j], curr[j - 1])
        prev = curr
    lcs_len = prev[n]
    return (2.0 * lcs_len) / (m + n)


# ── Function extraction ──────────────────────────────────────────────────────


@dataclass
class _FuncInfo:
    file: str
    name: str
    line_start: int
    line_end: int
    lines: int
    normalized: str
    struct_hash: str
    tokens: list[str]


def _extract_functions(files: list[tuple[str, str]]) -> list[_FuncInfo]:
    """Extract and normalize all non-trivial functions from source files.

    Skips test files to reduce noise — test functions tend to have similar
    structure (setup, assert) that produces many false near-duplicates.
    """
    funcs: list[_FuncInfo] = []
    for file_path, source in files:
        if _TEST_PATH_RE.search(file_path):
            continue
        try:
            tree = ast.parse(source, filename=file_path)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                line_start = node.lineno
                line_end = node.end_lineno or node.lineno
                num_lines = line_end - line_start + 1
                if num_lines < MIN_LINES:
                    continue

                normalized = _normalize_function(node)
                tokens = _tree_tokens(normalized)
                funcs.append(
                    _FuncInfo(
                        file=file_path,
                        name=node.name,
                        line_start=line_start,
                        line_end=line_end,
                        lines=num_lines,
                        normalized=normalized,
                        struct_hash=_structural_hash(normalized),
                        tokens=tokens,
                    )
                )
    return funcs


# ── Main entry point ─────────────────────────────────────────────────────────


def find_duplicates(files: list[tuple[str, str]]) -> dict:
    """Find exact and near-duplicate functions across files.

    Args:
        files: List of (file_path, source_code) tuples.

    Returns:
        Dict with clusters, stats, and generated_at timestamp.
    """
    funcs = _extract_functions(files)
    clusters: list[dict] = []

    # ── Exact duplicates (hash buckets) ───────────────────────────────────
    hash_groups: dict[str, list[_FuncInfo]] = defaultdict(list)
    for f in funcs:
        hash_groups[f.struct_hash].append(f)

    exact_hashes: set[str] = set()
    for h, group in hash_groups.items():
        if len(group) >= 2:
            exact_hashes.add(h)
            total_lines = sum(f.lines for f in group)
            clusters.append(
                {
                    "hash": h,
                    "type": "exact",
                    "functions": [
                        {
                            "file": f.file,
                            "name": f.name,
                            "line_start": f.line_start,
                            "line_end": f.line_end,
                            "lines": f.lines,
                        }
                        for f in group
                    ],
                    "suggested_action": "Extract to shared utility function",
                }
            )

    # ── Near duplicates ───────────────────────────────────────────────────
    # Only compare non-exact-duplicate functions of similar size
    non_exact = [f for f in funcs if f.struct_hash not in exact_hashes]
    seen_pairs: set[tuple[str, str]] = set()

    for i, a in enumerate(non_exact):
        for j in range(i + 1, len(non_exact)):
            b = non_exact[j]
            # Size filter: line count within 50%
            max_lines = max(a.lines, b.lines)
            min_lines = min(a.lines, b.lines)
            if min_lines < max_lines * 0.5:
                continue

            pair_key = (
                f"{a.file}::{a.name}::{a.line_start}",
                f"{b.file}::{b.name}::{b.line_start}",
            )
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            sim = _similarity(a.tokens, b.tokens)
            if sim > NEAR_THRESHOLD:
                clusters.append(
                    {
                        "hash": None,
                        "type": "near",
                        "similarity": round(sim, 2),
                        "functions": [
                            {
                                "file": a.file,
                                "name": a.name,
                                "line_start": a.line_start,
                                "line_end": a.line_end,
                                "lines": a.lines,
                            },
                            {
                                "file": b.file,
                                "name": b.name,
                                "line_start": b.line_start,
                                "line_end": b.line_end,
                                "lines": b.lines,
                            },
                        ],
                        "suggested_action": "Review for possible consolidation",
                    }
                )

    # ── Stats ─────────────────────────────────────────────────────────────
    exact_clusters = [c for c in clusters if c["type"] == "exact"]
    near_clusters = [c for c in clusters if c["type"] == "near"]
    total_dup_lines = sum(
        sum(f["lines"] for f in c["functions"])
        for c in exact_clusters
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "clusters": clusters,
        "stats": {
            "functions_analyzed": len(funcs),
            "exact_clusters": len(exact_clusters),
            "near_clusters": len(near_clusters),
            "total_duplicate_lines": total_dup_lines,
        },
    }
