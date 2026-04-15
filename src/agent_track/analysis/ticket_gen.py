"""Generate tickets from analysis findings (duplicates, coverage, security)."""

from __future__ import annotations

from agent_track.services import paths
from agent_track.services.frontmatter import parse_frontmatter
from agent_track.services.models import (
    all_tickets,
    next_ticket_id,
    post_to_board,
    write_ticket,
)
from agent_track.services.utils import file_lock, now_iso


# ── Per-finding-type ticket generators ───────────────────────────────────────


def tickets_from_duplicates(findings: dict) -> list[dict]:
    """Generate ticket dicts from duplicate-analysis findings."""
    tickets: list[dict] = []
    for cluster in findings.get("clusters", []):
        funcs = cluster.get("functions", [])
        if len(funcs) < 2:
            continue
        # Use first function name as representative
        rep_name = funcs[0]["name"]
        count = len(funcs)
        files = list(dict.fromkeys(f["file"] for f in funcs))  # dedupe, preserve order

        # Build body
        func_lines = []
        for f in funcs:
            func_lines.append(
                f"- `{f['file']}:{f['name']}` (lines {f['line_start']}-{f['line_end']})"
            )

        body = f"""## Description

{count} {cluster.get('type', 'exact')} duplicate functions detected across the codebase.

### Duplicate functions:
{chr(10).join(func_lines)}

### Suggested fix:
1. Create a shared utility function
2. Replace all {count} call sites with imports from the shared location
3. Ensure all existing tests pass after refactoring

## Acceptance Criteria

- [ ] Single implementation of the duplicated logic
- [ ] All {count} original call sites updated to use the shared function
- [ ] No duplicate hash matches remaining in `track analyze`
- [ ] All existing tests pass"""

        tickets.append({
            "title": f"Deduplicate: {rep_name} ({count} copies)",
            "priority": "medium",
            "labels": ["dedup", "auto-generated"],
            "files": files,
            "body": body,
            "_finding_key": f"dedup:{cluster.get('hash', '')}:{','.join(files)}",
        })
    return tickets


def tickets_from_coverage(findings: dict) -> list[dict]:
    """Generate ticket dicts from coverage-analysis findings."""
    tickets: list[dict] = []

    for func in findings.get("untested_functions", []):
        file_path = func["file"]
        func_name = func["name"]
        line_start = func.get("line_start", "?")
        line_end = func.get("line_end", "?")

        body = f"""## Description

`{file_path}:{func_name}` (lines {line_start}-{line_end}) has no test coverage.

### Suggested approach:
1. Create test file for `{func_name}`
2. Test happy path
3. Test error cases
4. Mock external dependencies if needed

## Acceptance Criteria

- [ ] Test file created for {func_name}
- [ ] Happy path test passes
- [ ] At least 2 error case tests
- [ ] `track analyze` no longer flags this function as untested"""

        tickets.append({
            "title": f"Add tests: {file_path}:{func_name}",
            "priority": "low",
            "labels": ["testing", "auto-generated"],
            "files": [file_path],
            "body": body,
            "_finding_key": f"coverage:{file_path}:{func_name}",
        })

    return tickets


def tickets_from_security(findings: dict) -> list[dict]:
    """Generate ticket dicts from security-analysis findings."""
    tickets: list[dict] = []

    for finding in findings.get("findings", []):
        severity = finding.get("severity", "medium")
        file_path = finding["file"]
        line = finding.get("line", "?")
        pattern = finding.get("pattern", "Unknown pattern")
        snippet = finding.get("snippet", "")
        finding_type = finding.get("type", "security_issue")

        # Map severity to priority
        priority_map = {"high": "critical", "medium": "high", "low": "medium"}
        priority = priority_map.get(severity, "medium")

        title = f"Security: {pattern} in {file_path}"
        if len(title) > 80:
            title = f"Security: {pattern[:40]}... in {file_path}"

        body = f"""## Description

{finding_type.replace('_', ' ').title()} detected at `{file_path}:{line}`.
Pattern: {pattern}.

```
{snippet}
```

### Suggested fix:
1. Remove or externalize the sensitive value
2. Use environment variables or a secrets manager
3. Verify the fix with `track analyze`

## Acceptance Criteria

- [ ] No {finding_type.replace('_', ' ')} in source code at this location
- [ ] Configuration reads from safe source (env var, secrets manager)
- [ ] `track analyze` security scan passes clean for this file"""

        tickets.append({
            "title": title,
            "priority": priority,
            "labels": ["security", "auto-generated"],
            "files": [file_path],
            "body": body,
            "_finding_key": f"security:{file_path}:{line}:{pattern}",
        })

    return tickets


# ── Deduplication check ──────────────────────────────────────────────────────


def _existing_ticket_keys() -> set[str]:
    """Collect finding keys from existing auto-generated tickets.

    We check labels and files to detect equivalent tickets.
    """
    keys: set[str] = set()
    for meta, body, _path in all_tickets():
        labels = meta.get("labels") or []
        if "auto-generated" not in labels:
            continue
        # Reconstruct a rough key from label + files + title
        files_str = ",".join(sorted(meta.get("files") or []))
        title = meta.get("title", "")
        for label in ("dedup", "testing", "security"):
            if label in labels:
                keys.add(f"{label}:{files_str}:{title}")
    return keys


def _ticket_matches_existing(ticket: dict, existing_keys: set[str]) -> bool:
    """Check if a generated ticket already has an equivalent in the system."""
    labels = ticket.get("labels", [])
    files_str = ",".join(sorted(ticket.get("files", [])))
    title = ticket.get("title", "")
    for label in ("dedup", "testing", "security"):
        if label in labels:
            key = f"{label}:{files_str}:{title}"
            if key in existing_keys:
                return True
    return False


# ── Main entry point ─────────────────────────────────────────────────────────


def generate_tickets_from_findings(
    *,
    duplicates: dict | None = None,
    coverage: dict | None = None,
    security: dict | None = None,
    dry_run: bool = False,
) -> list[dict]:
    """Generate and optionally create tickets from analysis findings.

    Args:
        duplicates: Output of find_duplicates().
        coverage: Output of analyze_coverage().
        security: Output of scan_security().
        dry_run: If True, return ticket dicts without writing files.

    Returns:
        List of ticket metadata dicts that were created (or would be in dry-run).
    """
    proposed: list[dict] = []
    if duplicates:
        proposed.extend(tickets_from_duplicates(duplicates))
    if coverage:
        proposed.extend(tickets_from_coverage(coverage))
    if security:
        proposed.extend(tickets_from_security(security))

    if not proposed:
        return []

    # Filter out tickets that already exist
    if not dry_run:
        existing_keys = _existing_ticket_keys()
        proposed = [t for t in proposed if not _ticket_matches_existing(t, existing_keys)]

    if dry_run:
        return proposed

    # Create actual ticket files
    created: list[dict] = []
    for ticket in proposed:
        with file_lock("_create.lock"):
            tid = next_ticket_id()
            meta = {
                "id": tid,
                "title": ticket["title"],
                "status": "backlog",
                "priority": ticket["priority"],
                "created": now_iso(),
                "created_by": "track-analyze",
                "claimed_by": None,
                "claimed_at": None,
                "labels": ticket["labels"],
                "branch": None,
                "files": ticket["files"],
                "depends_on": [],
            }
            body = ticket["body"]
            path = paths.TICKETS_DIR / f"{tid}.md"
            write_ticket(meta, body, path)

        post_to_board("track-analyze", tid, "created", f"Created: {ticket['title']}")
        created.append(meta)

    return created
