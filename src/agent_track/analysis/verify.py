"""Post-completion verification — compare pre/post analysis to verify ticket work."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from agent_track.services import paths
from agent_track.services.utils import now_iso


@dataclass
class VerificationResult:
    """Result of verifying ticket completion."""
    ticket_id: str
    verified_at: str
    result: str  # "pass", "fail", "partial"
    checks: list[dict] = field(default_factory=list)
    follow_up_needed: bool = False


# ── Ticket directory helpers ─────────────────────────────────────────────────


def _ticket_dir(ticket_id: str) -> Path | None:
    """Find or create ticket directory."""
    # Directory format
    d = paths.TICKETS_DIR / ticket_id
    if d.is_dir():
        return d
    # Flat format — migrate to directory
    flat = paths.TICKETS_DIR / f"{ticket_id}.md"
    if flat.exists():
        d.mkdir(parents=True, exist_ok=True)
        flat.rename(d / "ticket.md")
        return d
    # Check archive
    d = paths.ARCHIVE_DIR / ticket_id
    if d.is_dir():
        return d
    return None


def _read_ticket_meta(ticket_id: str) -> dict | None:
    """Read ticket metadata."""
    from agent_track.services.frontmatter import parse_frontmatter

    d = _ticket_dir(ticket_id)
    if not d:
        return None
    ticket_file = d / "ticket.md"
    if not ticket_file.exists():
        return None
    meta, _ = parse_frontmatter(ticket_file.read_text(encoding="utf-8"))
    return meta


# ── Analysis data readers ────────────────────────────────────────────────────


def _read_analysis(name: str) -> dict | None:
    """Read an analysis JSON file from .track/analysis/."""
    path = paths.ANALYSIS_DIR / f"{name}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _snapshot_for_labels(labels: list[str]) -> dict:
    """Build a snapshot dict with relevant analysis data for the given labels."""
    snapshot: dict = {}

    # Always capture all three, but label determines what we compare
    dup = _read_analysis("duplicates")
    if dup:
        snapshot["duplicates"] = dup

    cov = _read_analysis("test-coverage")
    if cov:
        snapshot["coverage"] = cov

    sec = _read_analysis("security")
    if sec:
        snapshot["security"] = sec

    snapshot["captured_at"] = now_iso()
    return snapshot


# ── Pre-analysis capture ─────────────────────────────────────────────────────


def capture_pre_analysis(ticket_id: str) -> None:
    """Capture analysis snapshot before work begins on a ticket.

    Called when a ticket is claimed. Writes to .track/tickets/{id}/pre-analysis.json.
    """
    meta = _read_ticket_meta(ticket_id)
    if not meta:
        return

    labels = meta.get("labels") or []
    snapshot = _snapshot_for_labels(labels)

    d = _ticket_dir(ticket_id)
    if d:
        (d / "pre-analysis.json").write_text(json.dumps(snapshot, indent=2))


# ── Verification ─────────────────────────────────────────────────────────────


def _compare_duplicates(pre: dict, post: dict) -> dict:
    """Compare pre/post duplicate analysis."""
    pre_clusters = pre.get("stats", {}).get("exact_clusters", 0)
    post_clusters = post.get("stats", {}).get("exact_clusters", 0)
    if post_clusters == 0:
        result = "pass"
    elif post_clusters < pre_clusters:
        result = "partial"
    else:
        result = "fail"
    return {
        "type": "duplicates",
        "pre": {"clusters": pre_clusters},
        "post": {"clusters": post_clusters},
        "result": result,
    }


def _compare_coverage(pre: dict, post: dict) -> dict:
    """Compare pre/post coverage analysis."""
    pre_untested = pre.get("coverage", {}).get("functions_without_tests", 0)
    post_untested = post.get("coverage", {}).get("functions_without_tests", 0)
    if post_untested == 0:
        result = "pass"
    elif post_untested < pre_untested:
        result = "partial"
    else:
        result = "fail"
    return {
        "type": "coverage",
        "pre": {"untested_functions": pre_untested},
        "post": {"untested_functions": post_untested},
        "result": result,
    }


def _compare_security(pre: dict, post: dict) -> dict:
    """Compare pre/post security analysis."""
    pre_findings = len(pre.get("findings", []))
    post_findings = len(post.get("findings", []))
    if post_findings == 0:
        result = "pass"
    elif post_findings < pre_findings:
        result = "partial"
    else:
        result = "fail"
    return {
        "type": "security",
        "pre": {"findings": pre_findings},
        "post": {"findings": post_findings},
        "result": result,
    }


def run_verification(ticket_id: str) -> VerificationResult | None:
    """Run post-completion verification for a ticket.

    Compares pre-analysis snapshot with current analysis results.
    Writes verification.json to the ticket directory.

    Returns:
        VerificationResult or None if no pre-analysis exists.
    """
    meta = _read_ticket_meta(ticket_id)
    if not meta:
        return None

    d = _ticket_dir(ticket_id)
    if not d:
        return None

    pre_file = d / "pre-analysis.json"
    if not pre_file.exists():
        return None

    pre_snapshot = json.loads(pre_file.read_text(encoding="utf-8"))
    labels = meta.get("labels") or []

    # Build current snapshot
    post_snapshot = _snapshot_for_labels(labels)

    checks: list[dict] = []

    # Compare based on ticket labels
    if "dedup" in labels and "duplicates" in pre_snapshot and "duplicates" in post_snapshot:
        checks.append(_compare_duplicates(pre_snapshot["duplicates"], post_snapshot["duplicates"]))

    if "testing" in labels and "coverage" in pre_snapshot and "coverage" in post_snapshot:
        checks.append(_compare_coverage(pre_snapshot["coverage"], post_snapshot["coverage"]))

    if "security" in labels and "security" in pre_snapshot and "security" in post_snapshot:
        checks.append(_compare_security(pre_snapshot["security"], post_snapshot["security"]))

    # If no label-specific checks, compare all available
    if not checks:
        if "duplicates" in pre_snapshot and "duplicates" in post_snapshot:
            checks.append(_compare_duplicates(pre_snapshot["duplicates"], post_snapshot["duplicates"]))
        if "coverage" in pre_snapshot and "coverage" in post_snapshot:
            checks.append(_compare_coverage(pre_snapshot["coverage"], post_snapshot["coverage"]))
        if "security" in pre_snapshot and "security" in post_snapshot:
            checks.append(_compare_security(pre_snapshot["security"], post_snapshot["security"]))

    # Determine overall result
    if not checks:
        overall = "pass"
    elif all(c["result"] == "pass" for c in checks):
        overall = "pass"
    elif all(c["result"] == "fail" for c in checks):
        overall = "fail"
    else:
        overall = "partial"

    follow_up = overall in ("fail", "partial")

    vr = VerificationResult(
        ticket_id=ticket_id,
        verified_at=now_iso(),
        result=overall,
        checks=checks,
        follow_up_needed=follow_up,
    )

    # Write verification result
    result_dict = {
        "ticket_id": vr.ticket_id,
        "verified_at": vr.verified_at,
        "result": vr.result,
        "checks": vr.checks,
        "follow_up_needed": vr.follow_up_needed,
    }
    (d / "verification.json").write_text(json.dumps(result_dict, indent=2))

    return vr
