"""Symbol-level graph resolution — resolve call edges across files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from agent_track.analysis.parsers.python_parser import ParseResult


@dataclass(frozen=True)
class ResolvedCallEdge:
    """A resolved call edge: caller_file::caller_func → callee_file::callee_func."""

    caller: str  # e.g. "src/app.py::main"
    callee: str  # e.g. "src/auth.py::refresh_token" or "?::unknown"
    edge_type: str = "call"


def resolve_symbol_graph(results: list[ParseResult]) -> list[ResolvedCallEdge]:
    """Resolve raw call edges into cross-file symbol edges.

    Strategy (pragmatic, not perfect):
    - Build per-file name tables from imports
    - Build a global module→file and file→symbols lookup
    - Resolve direct calls to same-file symbols first, then imports
    - Resolve attribute calls (module.func) via import table
    - Resolve self.method() to same-class methods
    - Unresolved calls get target "?::name"
    - Deduplicate edges
    """
    # Build global lookups
    module_to_file = _build_module_to_file(results)
    file_symbols = _build_file_symbols(results)

    edges: set[ResolvedCallEdge] = set()

    for pr in results:
        # Build name table for this file: name → (file, symbol_name)
        name_table = _build_name_table(pr, module_to_file, file_symbols)
        # Class method lookup for self.X resolution
        class_methods = _build_class_methods(pr)

        for call in pr.calls:
            caller_qualified = f"{pr.file_path}::{call.caller}"
            callee = _resolve_callee(
                call.callee,
                call.caller,
                pr.file_path,
                name_table,
                file_symbols,
                class_methods,
                module_to_file,
            )
            edges.add(ResolvedCallEdge(caller=caller_qualified, callee=callee))

    return sorted(edges, key=lambda e: (e.caller, e.callee))


def _build_module_to_file(results: list[ParseResult]) -> dict[str, str]:
    """Map module dotted names to file paths.

    e.g. "src/auth.py" → module "auth" or "src.auth"
    """
    mapping: dict[str, str] = {}
    for pr in results:
        if pr.language != "python":
            continue
        p = PurePosixPath(pr.file_path)
        # Strip .py extension
        stem = str(p.with_suffix(""))
        # Register as dotted module path: src/auth → src.auth
        dotted = stem.replace("/", ".")
        mapping[dotted] = pr.file_path
        # Also register just the filename stem: auth
        mapping[p.stem] = pr.file_path
    return mapping


def _build_file_symbols(results: list[ParseResult]) -> dict[str, set[str]]:
    """Map file paths to sets of defined symbol names."""
    mapping: dict[str, set[str]] = {}
    for pr in results:
        names: set[str] = set()
        for sym in pr.symbols:
            names.add(sym.name)
            # Also add class methods as ClassName.method
            if sym.type == "class":
                for method in sym.methods:
                    names.add(f"{sym.name}.{method}")
        mapping[pr.file_path] = names
    return mapping


def _build_name_table(
    pr: ParseResult,
    module_to_file: dict[str, str],
    file_symbols: dict[str, set[str]],
) -> dict[str, tuple[str, str]]:
    """Build a name → (file, symbol) table from imports.

    For `from auth import refresh_token`, maps:
        "refresh_token" → ("src/auth.py", "refresh_token")

    For `import db`, maps:
        "db" → ("src/db.py", "<module>")  (attribute calls resolved separately)
    """
    table: dict[str, tuple[str, str]] = {}

    for imp in pr.imports:
        target_file = module_to_file.get(imp.target_module)

        if imp.level == 0 and not imp.names[0].startswith("_"):
            # `import foo` — names contains [foo] or [alias]
            if target_file and len(imp.names) == 1 and imp.names[0] == imp.target_module.split(".")[-1]:
                # Plain import: `import db`
                table[imp.names[0]] = (target_file, "<module>")
            else:
                # `from foo import bar, baz`
                if target_file:
                    for name in imp.names:
                        if name in file_symbols.get(target_file, set()):
                            table[name] = (target_file, name)
        else:
            # Relative import or from-import
            if target_file:
                for name in imp.names:
                    if name in file_symbols.get(target_file, set()):
                        table[name] = (target_file, name)

    return table


def _build_class_methods(pr: ParseResult) -> dict[str, dict[str, str]]:
    """Map ClassName → {method_name: ClassName.method_name} for self.X resolution."""
    mapping: dict[str, dict[str, str]] = {}
    for sym in pr.symbols:
        if sym.type == "class":
            mapping[sym.name] = {m: f"{sym.name}.{m}" for m in sym.methods}
    return mapping


def _resolve_callee(
    callee: str,
    caller: str,
    file_path: str,
    name_table: dict[str, tuple[str, str]],
    file_symbols: dict[str, set[str]],
    class_methods: dict[str, dict[str, str]],
    module_to_file: dict[str, str],
) -> str:
    """Resolve a raw callee name to a qualified file::symbol string."""
    local_symbols = file_symbols.get(file_path, set())

    # 1. self.method() → resolve to same class
    if callee.startswith("self."):
        method_name = callee[5:]  # strip "self."
        # Determine which class the caller is in
        # caller is "ClassName.method_name" for methods
        if "." in caller:
            class_name = caller.split(".")[0]
            methods = class_methods.get(class_name, {})
            if method_name in methods:
                return f"{file_path}::{class_name}.{method_name}"
        return f"?::{callee}"

    # 2. Direct call: check same-file symbols first
    if callee in local_symbols:
        return f"{file_path}::{callee}"

    # 3. Check import name table
    if callee in name_table:
        target_file, target_sym = name_table[callee]
        return f"{target_file}::{target_sym}"

    # 4. Attribute call: module.func() — split on first dot
    if "." in callee:
        parts = callee.split(".", 1)
        module_name = parts[0]
        attr = parts[1]
        # Check if module_name is an imported module
        if module_name in name_table:
            target_file, _ = name_table[module_name]
            target_syms = file_symbols.get(target_file, set())
            if attr in target_syms:
                return f"{target_file}::{attr}"
        # Try resolving module_name directly
        target_file = module_to_file.get(module_name)
        if target_file:
            target_syms = file_symbols.get(target_file, set())
            if attr in target_syms:
                return f"{target_file}::{attr}"

    # 5. Unresolved
    return f"?::{callee}"
