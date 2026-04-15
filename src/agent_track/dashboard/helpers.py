"""Shared helpers for dashboard modules."""

from __future__ import annotations

import json
from pathlib import Path


def read_jsonl(file_path: Path) -> list[dict]:
    """Read a JSONL file, returning a list of parsed entries."""
    if not file_path.exists():
        return []
    entries = []
    for line in file_path.read_text(encoding="utf-8").strip().split("\n"):
        if line.strip():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return entries
