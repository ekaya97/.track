"""Dashboard API helpers — ticket-from-finding, verification, injections."""

from __future__ import annotations

import json

from agent_track.services import paths
from agent_track.services.models import all_agents


# ── Create ticket from finding ───────────────────────────────────────────────


def create_ticket_from_finding(finding: dict) -> dict:
    """Create a ticket from a single analysis finding.

    Args:
        finding: Dict with "type" (duplicates|coverage|security) and "data" keys.

    Returns:
        Dict with ticket_id on success, or error on failure.
    """
    from agent_track.analysis.ticket_gen import (
        tickets_from_duplicates,
        tickets_from_coverage,
        tickets_from_security,
        generate_tickets_from_findings,
    )

    finding_type = finding.get("type")
    data = finding.get("data", {})

    if finding_type == "duplicates":
        # Wrap single cluster into full findings format
        findings = {
            "clusters": [data],
            "stats": {"functions_analyzed": 0, "exact_clusters": 1, "near_clusters": 0, "total_duplicate_lines": 0},
        }
        results = generate_tickets_from_findings(duplicates=findings, dry_run=False)
    elif finding_type == "coverage":
        # Wrap single untested function into full findings format
        findings = {
            "coverage": {},
            "untested_functions": [data],
            "untested_files": [],
            "suspicious_tests": [],
        }
        results = generate_tickets_from_findings(coverage=findings, dry_run=False)
    elif finding_type == "security":
        findings = {
            "findings": [data],
            "stats": {"files_scanned": 0, "findings_high": 0, "findings_medium": 0, "findings_low": 0},
        }
        results = generate_tickets_from_findings(security=findings, dry_run=False)
    else:
        return {"error": f"Unknown finding type: {finding_type}"}

    if not results:
        return {"error": "No ticket created (may already exist)"}

    return {"ticket_id": results[0]["id"], "title": results[0]["title"]}


# ── Verification status ──────────────────────────────────────────────────────


def get_ticket_verification(ticket_id: str) -> dict | None:
    """Read verification.json for a ticket.

    Returns the verification dict, or None/error dict if not found.
    """
    # Check directory format
    for base in [paths.TICKETS_DIR, paths.ARCHIVE_DIR]:
        ticket_dir = base / ticket_id
        vfile = ticket_dir / "verification.json"
        if vfile.exists():
            try:
                return json.loads(vfile.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {"error": "Corrupt verification.json"}

    return None


# ── Injection history ────────────────────────────────────────────────────────


def get_ticket_injections(ticket_id: str) -> list[dict]:
    """Read injection history for a ticket across all sessions.

    Scans all agent sessions to find ones working on this ticket,
    then reads their injections.jsonl.
    """
    results: list[dict] = []

    # Find sessions associated with this ticket
    for agent_data in all_agents():
        if agent_data.get("current_ticket") != ticket_id:
            continue

        session_id = agent_data.get("session_id", agent_data.get("id", ""))
        inj_file = paths.SESSIONS_DIR / session_id / "injections.jsonl"
        if not inj_file.exists():
            continue

        try:
            for line in inj_file.read_text(encoding="utf-8").strip().split("\n"):
                if line.strip():
                    results.append(json.loads(line))
        except (json.JSONDecodeError, OSError):
            pass

    return results
