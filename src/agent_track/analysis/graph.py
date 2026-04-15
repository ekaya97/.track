"""Graph assembly and analyze command implementation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_track.analysis import detect_language, walk_project
from agent_track.services import paths


def cmd_analyze(args: argparse.Namespace) -> None:
    """Run codebase analysis."""
    # Determine project root (parent of .track/)
    project_root = paths.TRACK_DIR.parent

    # Ensure output directories exist
    paths.GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    paths.ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

    # Walk the project
    files = walk_project(project_root)

    # Build file list with language info
    file_entries = []
    lang_counts: dict[str, int] = {}
    for f in files:
        rel = str(f.relative_to(project_root))
        lang = detect_language(f) or "unknown"
        lang_counts[lang] = lang_counts.get(lang, 0) + 1
        file_entries.append({"path": rel, "language": lang})

    output_format = getattr(args, "format", "text") or "text"

    if output_format == "json":
        result = {
            "project_root": str(project_root),
            "files": file_entries,
            "stats": {
                "total_files": len(file_entries),
                "languages": lang_counts,
            },
        }
        print(json.dumps(result, indent=2))
    else:
        # Text summary
        print(f"Analyzed {len(file_entries)} files in {project_root}")
        if lang_counts:
            parts = [f"  {lang}: {count}" for lang, count in sorted(lang_counts.items())]
            print("Languages:")
            for p in parts:
                print(p)
        else:
            print("No code files found.")
        print(f"\nGraph directory: {paths.GRAPH_DIR}")
        print(f"Analysis directory: {paths.ANALYSIS_DIR}")
