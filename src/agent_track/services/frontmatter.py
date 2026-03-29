"""Stdlib-only YAML frontmatter parser and serializer for ticket markdown files."""

from __future__ import annotations

import re


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown. Stdlib-only, flat schema."""
    if not text.startswith("---"):
        return {}, text
    end_match = re.search(r"\n---\s*\n", text[3:])
    if not end_match:
        return {}, text
    end = end_match.start() + 3
    fm_str = text[3:end].strip()
    body = text[end + end_match.end() - end_match.start() :].strip()

    meta: dict = {}
    current_key: str | None = None
    current_list: list | None = None

    for line in fm_str.splitlines():
        if line.startswith("  - ") and current_key is not None:
            if current_list is None:
                current_list = []
            current_list.append(
                line.strip().removeprefix("- ").strip().strip('"').strip("'")
            )
            continue

        if current_key is not None and current_list is not None:
            meta[current_key] = current_list
            current_list = None
            current_key = None

        if ":" not in line:
            continue

        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()

        if value == "" or value == "null":
            current_key = key
            current_list = None
            meta[key] = None
        elif value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            if inner:
                meta[key] = [
                    v.strip().strip('"').strip("'")
                    for v in inner.split(",")
                    if v.strip()
                ]
            else:
                meta[key] = []
            current_key = None
        elif value.startswith('"') and value.endswith('"'):
            meta[key] = value[1:-1]
            current_key = None
        elif value.startswith("'") and value.endswith("'"):
            meta[key] = value[1:-1]
            current_key = None
        else:
            meta[key] = value
            current_key = None

    if current_key is not None and current_list is not None:
        meta[current_key] = current_list

    return meta, body


def serialize_frontmatter(meta: dict, body: str) -> str:
    """Serialize metadata dict + body back to frontmatter markdown."""
    lines = ["---"]
    for key, value in meta.items():
        if value is None:
            lines.append(f"{key}: null")
        elif isinstance(value, list):
            if not value:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                for item in value:
                    lines.append(f"  - {item}")
        elif isinstance(value, str) and (" " in value or ":" in value or '"' in value):
            lines.append(f'{key}: "{value}"')
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    lines.append("")
    lines.append(body)
    return "\n".join(lines)
