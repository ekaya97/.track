"""Python AST parser — extract imports, symbols, and call edges."""

from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass, field
from pathlib import PurePosixPath


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class ImportEdge:
    """An import statement found in a source file."""

    source_file: str
    target_module: str
    names: list[str]
    level: int = 0  # 0 = absolute, 1 = from ., 2 = from .., etc.


@dataclass
class Symbol:
    """A symbol (function, class, constant) defined in a source file."""

    name: str
    type: str  # "function", "async_function", "class", "constant"
    line_start: int
    line_end: int
    hash: str = ""
    decorators: list[str] = field(default_factory=list)
    # Class-specific
    methods: list[str] = field(default_factory=list)
    bases: list[str] = field(default_factory=list)


@dataclass
class CallEdge:
    """A function/method call found inside a symbol body."""

    caller: str  # "module" or "ClassName.method" or function name
    callee: str  # called name, e.g. "process", "self.validate", "os.path.join"
    line: int = 0


@dataclass
class ParseResult:
    """Complete parse result for a single Python file."""

    file_path: str
    language: str
    imports: list[ImportEdge]
    symbols: list[Symbol]
    calls: list[CallEdge]
    lines: int
    parse_errors: list[str]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _hash_node(node: ast.AST, source: str) -> str:
    """Compute a content hash for an AST node."""
    segment = ast.get_source_segment(source, node) or ast.dump(node)
    return hashlib.sha256(segment.encode()).hexdigest()[:12]


def _decorator_name(node: ast.expr) -> str:
    """Extract decorator name from an AST node."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _call_name(node)
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    return ""


def _call_name(node: ast.expr) -> str:
    """Extract dotted call name from an AST expression."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        if prefix:
            return f"{prefix}.{node.attr}"
        return node.attr
    return ""


def resolve_relative_import(
    file_path: str, level: int, module: str | None
) -> str:
    """Resolve a relative import to a dotted module path.

    Args:
        file_path: The file containing the import (e.g. "src/pkg/mod.py").
        level: Number of dots (1 = from ., 2 = from .., etc.).
        module: The module after the dots (e.g. "utils" in ``from .utils``).

    Returns:
        Dotted module path (e.g. "src.pkg.utils").
    """
    parts = PurePosixPath(file_path).parts
    # Remove the filename to get the package directory parts
    pkg_parts = list(parts[:-1])
    # Go up `level` directories (level=1 stays in same package)
    up = level - 1
    if up > 0:
        pkg_parts = pkg_parts[:-up] if up < len(pkg_parts) else []
    base = ".".join(pkg_parts)
    if module:
        return f"{base}.{module}" if base else module
    return base


# ── Main parser ───────────────────────────────────────────────────────────────


def parse_python_file(source: str, file_path: str) -> ParseResult:
    """Parse Python source code and extract imports, symbols, and calls.

    Args:
        source: Python source code string.
        file_path: Relative file path (for import resolution context).

    Returns:
        ParseResult with extracted information. On syntax errors,
        returns an empty result with the error in parse_errors.
    """
    result = ParseResult(
        file_path=file_path,
        language="python",
        imports=[],
        symbols=[],
        calls=[],
        lines=len(source.splitlines()) if source.strip() else 0,
        parse_errors=[],
    )

    if not source.strip():
        return result

    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError as exc:
        result.parse_errors.append(f"SyntaxError: {exc}")
        return result

    _extract_imports(tree, file_path, result)
    _extract_symbols(tree, source, result)
    _extract_calls(tree, result)

    return result


def _extract_imports(
    tree: ast.Module, file_path: str, result: ParseResult
) -> None:
    """Extract import statements from the AST."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                result.imports.append(
                    ImportEdge(
                        source_file=file_path,
                        target_module=alias.name,
                        names=[alias.asname or alias.name],
                        level=0,
                    )
                )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = [alias.name for alias in node.names]
            level = node.level or 0
            target = module
            if level > 0:
                target = resolve_relative_import(file_path, level, module or None)
            result.imports.append(
                ImportEdge(
                    source_file=file_path,
                    target_module=target,
                    names=names,
                    level=level,
                )
            )


def _extract_symbols(
    tree: ast.Module, source: str, result: ParseResult
) -> None:
    """Extract top-level symbols (functions, classes, constants)."""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            sym_type = (
                "async_function"
                if isinstance(node, ast.AsyncFunctionDef)
                else "function"
            )
            result.symbols.append(
                Symbol(
                    name=node.name,
                    type=sym_type,
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                    hash=_hash_node(node, source),
                    decorators=[_decorator_name(d) for d in node.decorator_list],
                )
            )
        elif isinstance(node, ast.ClassDef):
            methods = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.append(item.name)
            bases = []
            for base in node.bases:
                name = _call_name(base)
                if name:
                    bases.append(name)
            result.symbols.append(
                Symbol(
                    name=node.name,
                    type="class",
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                    hash=_hash_node(node, source),
                    decorators=[_decorator_name(d) for d in node.decorator_list],
                    methods=methods,
                    bases=bases,
                )
            )
        elif isinstance(node, ast.Assign):
            # Module-level constant: X = <value>
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    result.symbols.append(
                        Symbol(
                            name=target.id,
                            type="constant",
                            line_start=node.lineno,
                            line_end=node.end_lineno or node.lineno,
                        )
                    )


def _extract_calls(tree: ast.Module, result: ParseResult) -> None:
    """Extract call edges from function/method bodies."""
    # Map top-level functions and class methods to their call sites
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _extract_calls_from_body(node.name, node, result)
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    caller = f"{node.name}.{item.name}"
                    _extract_calls_from_body(caller, item, result)


def _extract_calls_from_body(
    caller: str, node: ast.AST, result: ParseResult
) -> None:
    """Walk an AST node and extract all Call expressions."""
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            name = _call_name(child.func)
            if name:
                result.calls.append(
                    CallEdge(
                        caller=caller,
                        callee=name,
                        line=child.lineno,
                    )
                )
