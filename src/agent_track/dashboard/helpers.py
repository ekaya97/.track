"""Shared helpers for dashboard modules."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

# Thresholds in seconds
IDLE_THRESHOLD = 120  # 2 minutes without a tool call → idle
STALE_THRESHOLD = 1800  # 30 minutes → stale


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


def effective_status(agent_data: dict) -> str:
    """Compute the effective agent status based on heartbeat age.

    Stored status 'active' is refined to:
    - 'active'  if last heartbeat < 2 min ago
    - 'idle'    if last heartbeat 2-30 min ago
    - 'stale'   if last heartbeat > 30 min ago

    Other stored statuses (deregistered, stale) pass through unchanged.
    """
    stored = agent_data.get("status", "unknown")
    if stored != "active":
        return stored

    hb = agent_data.get("last_heartbeat")
    if not hb:
        return stored

    try:
        hb_dt = datetime.fromisoformat(hb.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - hb_dt).total_seconds()
    except (ValueError, TypeError):
        return stored

    if age > STALE_THRESHOLD:
        return "stale"
    if age > IDLE_THRESHOLD:
        return "idle"
    return "active"
