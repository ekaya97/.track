"""Ticket, Agent, and Board I/O operations."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from agent_track.services import paths
from agent_track.services.frontmatter import parse_frontmatter, serialize_frontmatter
from agent_track.services.utils import atomic_write, file_lock, now_iso


# ── Ticket I/O ────────────────────────────────────────────────────────────────


def _resolve_ticket_path(ticket_id: str) -> Path | None:
    """Find a ticket file in either flat or directory format."""
    # Directory format: tickets/T-0001/ticket.md
    dir_path = paths.TICKETS_DIR / ticket_id / "ticket.md"
    if dir_path.exists():
        return dir_path
    # Flat format: tickets/T-0001.md
    flat_path = paths.TICKETS_DIR / f"{ticket_id}.md"
    if flat_path.exists():
        return flat_path
    # Check archive (both formats)
    dir_path = paths.ARCHIVE_DIR / ticket_id / "ticket.md"
    if dir_path.exists():
        return dir_path
    flat_path = paths.ARCHIVE_DIR / f"{ticket_id}.md"
    if flat_path.exists():
        return flat_path
    return None


def read_ticket(ticket_id: str) -> tuple[dict, str, Path]:
    """Read a ticket file. Returns (meta, body, path). Supports flat and directory formats."""
    path = _resolve_ticket_path(ticket_id)
    if path is None:
        print(f"Error: Ticket {ticket_id} not found.", file=sys.stderr)
        sys.exit(1)
    text = path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)
    return meta, body, path


def write_ticket(meta: dict, body: str, path: Path) -> None:
    """Write a ticket file atomically."""
    content = serialize_frontmatter(meta, body)
    atomic_write(path, content)


def all_tickets() -> list[tuple[dict, str, Path]]:
    """Load all tickets from tickets/ and archive/. Supports flat and directory formats."""
    results = []
    seen: set[str] = set()
    for d in [paths.TICKETS_DIR, paths.ARCHIVE_DIR]:
        if not d.exists():
            continue
        # Directory format: T-NNNN/ticket.md
        for ticket_dir in sorted(d.iterdir()):
            if ticket_dir.is_dir() and ticket_dir.name.startswith("T-"):
                ticket_file = ticket_dir / "ticket.md"
                if ticket_file.exists():
                    text = ticket_file.read_text(encoding="utf-8")
                    meta, body = parse_frontmatter(text)
                    results.append((meta, body, ticket_file))
                    seen.add(ticket_dir.name)
        # Flat format: T-NNNN.md
        for f in sorted(d.glob("T-*.md")):
            if f.stem not in seen:
                text = f.read_text(encoding="utf-8")
                meta, body = parse_frontmatter(text)
                results.append((meta, body, f))
    return results


def _collect_ticket_ids() -> set[int]:
    """Collect all ticket numbers from both flat and directory formats."""
    nums: set[int] = set()
    for d in [paths.TICKETS_DIR, paths.ARCHIVE_DIR]:
        if not d.exists():
            continue
        # Directory format
        for entry in d.iterdir():
            if entry.is_dir():
                m = re.match(r"T-(\d+)", entry.name)
                if m:
                    nums.add(int(m.group(1)))
        # Flat format
        for f in d.glob("T-*.md"):
            m = re.match(r"T-(\d+)", f.stem)
            if m:
                nums.add(int(m.group(1)))
    return nums


def next_ticket_id() -> str:
    """Find the next available ticket ID."""
    nums = _collect_ticket_ids()
    max_num = max(nums) if nums else 0
    return f"T-{max_num + 1:04d}"


def migrate_ticket_to_dir(ticket_id: str) -> Path:
    """Migrate a flat ticket file to directory format. Idempotent.

    Returns the ticket directory path.
    """
    ticket_dir = paths.TICKETS_DIR / ticket_id

    # Already directory format
    if ticket_dir.is_dir() and (ticket_dir / "ticket.md").exists():
        (ticket_dir / "tasks").mkdir(exist_ok=True)
        return ticket_dir

    # Flat format — migrate
    flat_path = paths.TICKETS_DIR / f"{ticket_id}.md"
    if not flat_path.exists():
        # Check archive
        flat_path = paths.ARCHIVE_DIR / f"{ticket_id}.md"
        if not flat_path.exists():
            raise FileNotFoundError(f"Ticket {ticket_id} not found")
        ticket_dir = paths.ARCHIVE_DIR / ticket_id

    ticket_dir.mkdir(parents=True, exist_ok=True)
    (ticket_dir / "tasks").mkdir(exist_ok=True)

    # Move flat file to ticket.md inside directory
    flat_path.rename(ticket_dir / "ticket.md")

    return ticket_dir


# ── Agent I/O ─────────────────────────────────────────────────────────────────


def read_agent(agent_id: str) -> dict:
    """Read an agent JSON file."""
    path = paths.AGENTS_DIR / f"{agent_id}.json"
    if not path.exists():
        print(f"Error: Agent '{agent_id}' not found.", file=sys.stderr)
        sys.exit(1)
    return json.loads(path.read_text(encoding="utf-8"))


def write_agent(data: dict) -> None:
    """Write an agent JSON file atomically."""
    path = paths.AGENTS_DIR / f"{data['id']}.json"
    atomic_write(path, json.dumps(data, indent=2) + "\n")


def all_agents() -> list[dict]:
    """List all agent JSON files."""
    results = []
    if paths.AGENTS_DIR.exists():
        for f in sorted(paths.AGENTS_DIR.glob("*.json")):
            data = json.loads(f.read_text(encoding="utf-8"))
            results.append(data)
    return results


# ── Board I/O ─────────────────────────────────────────────────────────────────

BOARD_HEADER = """# .track Board

<!-- New messages are prepended below this line -->
"""


def post_to_board(agent: str, ticket: str, tag: str, message: str) -> None:
    """Append an entry to the board file."""
    with file_lock("_board.lock"):
        if not paths.BOARD_FILE.exists():
            paths.BOARD_FILE.write_text(BOARD_HEADER, encoding="utf-8")

        content = paths.BOARD_FILE.read_text(encoding="utf-8")
        marker = "<!-- New messages are prepended below this line -->"
        entry = f"\n---\n**[{now_iso()}] {agent}** | {ticket} | {tag}\n{message}\n"

        if marker in content:
            content = content.replace(marker, marker + entry, 1)
        else:
            content += entry

        atomic_write(paths.BOARD_FILE, content)


def parse_board_entries(limit: int = 50) -> list[dict]:
    """Parse board entries from BOARD.md."""
    if not paths.BOARD_FILE.exists():
        return []
    content = paths.BOARD_FILE.read_text(encoding="utf-8")
    entries = []
    pattern = re.compile(
        r"---\n\*\*\[(.+?)\] (.+?)\*\* \| (.+?) \| (.+?)\n(.*?)(?=\n---\n|\Z)",
        re.DOTALL,
    )
    for m in pattern.finditer(content):
        entries.append(
            {
                "timestamp": m.group(1),
                "agent": m.group(2),
                "ticket": m.group(3).strip(),
                "tag": m.group(4).strip(),
                "message": m.group(5).strip(),
            }
        )
    return entries[:limit]
