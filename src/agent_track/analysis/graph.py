"""Graph assembly and analyze command implementation."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from agent_track.analysis import detect_language, walk_project
from agent_track.analysis.parsers.python_parser import ParseResult, parse_python_file
from agent_track.analysis.symbol_graph import resolve_symbol_graph


# ── Graph assembly ────────────────────────────────────────────────────────────


def assemble_file_graph(
    results: list[ParseResult], project_root: str
) -> dict:
    """Assemble file-level graph from parse results.

    Returns a dict with nodes (files), edges (imports), and stats.
    """
    nodes = []
    edges = []
    lang_counts: dict[str, int] = {}
    total_symbols = 0

    for pr in results:
        lang_counts[pr.language] = lang_counts.get(pr.language, 0) + 1
        total_symbols += len(pr.symbols)

        # Build node
        node = {
            "id": pr.file_path,
            "type": "file",
            "language": pr.language,
            "directory": str(Path(pr.file_path).parent),
            "symbols": [
                {
                    "name": s.name,
                    "type": s.type,
                    "line_start": s.line_start,
                    "line_end": s.line_end,
                    "hash": s.hash,
                }
                for s in pr.symbols
            ],
            "lines": pr.lines,
        }
        nodes.append(node)

        # Build import edges (file-level)
        seen_imports: set[tuple[str, str]] = set()
        for imp in pr.imports:
            key = (pr.file_path, imp.target_module)
            if key not in seen_imports:
                seen_imports.add(key)
                edges.append(
                    {
                        "source": pr.file_path,
                        "target_module": imp.target_module,
                        "type": "import",
                    }
                )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "project_root": project_root,
        "stats": {
            "files": len(results),
            "symbols": total_symbols,
            "edges": len(edges),
            "languages": lang_counts,
        },
        "nodes": nodes,
        "edges": edges,
    }


def assemble_symbol_graph(
    results: list[ParseResult], project_root: str
) -> dict:
    """Assemble full symbol-level graph from parse results.

    Includes file nodes, import edges, AND resolved call edges.
    """
    file_graph = assemble_file_graph(results, project_root)

    # Resolve call edges
    resolved = resolve_symbol_graph(results)
    call_edges = []
    seen: set[tuple[str, str]] = set()
    for edge in resolved:
        key = (edge.caller, edge.callee)
        if key not in seen:
            seen.add(key)
            call_edges.append(
                {
                    "source": edge.caller,
                    "target": edge.callee,
                    "type": "call",
                }
            )

    file_graph["edges"].extend(call_edges)
    file_graph["stats"]["edges"] = len(file_graph["edges"])
    return file_graph


# ── Analysis runner ───────────────────────────────────────────────────────────


def run_analysis(
    results: list[ParseResult],
    project_root: str,
    graph_dir: Path | None = None,
) -> None:
    """Run full analysis and write JSON output files."""
    from agent_track.services import paths

    gd = graph_dir or paths.GRAPH_DIR
    gd.mkdir(parents=True, exist_ok=True)

    file_graph = assemble_file_graph(results, project_root)
    symbol_graph = assemble_symbol_graph(results, project_root)

    (gd / "file-graph.json").write_text(json.dumps(file_graph, indent=2))
    (gd / "symbol-graph.json").write_text(json.dumps(symbol_graph, indent=2))


# ── CLI command ───────────────────────────────────────────────────────────────


def cmd_analyze(args: argparse.Namespace) -> None:
    """Run codebase analysis."""
    from agent_track.services import paths

    project_root = paths.TRACK_DIR.parent

    paths.GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    paths.ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

    # Walk and parse
    files = walk_project(project_root)
    results: list[ParseResult] = []
    for f in files:
        lang = detect_language(f)
        if lang == "python":
            rel = str(f.relative_to(project_root))
            source = f.read_text(errors="replace")
            results.append(parse_python_file(source, rel))

    # Write graph files
    run_analysis(results, str(project_root), graph_dir=paths.GRAPH_DIR)

    # Build summary for non-python files too
    all_files = files
    lang_counts: dict[str, int] = {}
    for f in all_files:
        lang = detect_language(f) or "unknown"
        lang_counts[lang] = lang_counts.get(lang, 0) + 1

    output_format = getattr(args, "format", "text") or "text"

    if output_format == "json":
        file_entries = []
        for f in all_files:
            rel = str(f.relative_to(project_root))
            lang = detect_language(f) or "unknown"
            file_entries.append({"path": rel, "language": lang})
        result = {
            "project_root": str(project_root),
            "files": file_entries,
            "stats": {
                "total_files": len(file_entries),
                "languages": lang_counts,
                "python_parsed": len(results),
            },
        }
        print(json.dumps(result, indent=2))
    else:
        print(f"Analyzed {len(all_files)} files in {project_root}")
        print(f"Parsed {len(results)} Python files into graph")
        if lang_counts:
            print("Languages:")
            for lang, count in sorted(lang_counts.items()):
                print(f"  {lang}: {count}")
        print(f"\nGraph: {paths.GRAPH_DIR}")
        print(f"Analysis: {paths.ANALYSIS_DIR}")
