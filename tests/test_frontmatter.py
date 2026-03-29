"""Tests for the frontmatter parser and serializer."""

from agent_track.services.frontmatter import parse_frontmatter, serialize_frontmatter


def test_parse_basic():
    text = "---\nid: T-0001\ntitle: Fix bug\nstatus: backlog\n---\n\nBody text."
    meta, body = parse_frontmatter(text)
    assert meta["id"] == "T-0001"
    assert meta["title"] == "Fix bug"
    assert meta["status"] == "backlog"
    assert body == "Body text."


def test_parse_null_values():
    text = "---\nbranch: null\nclaimed_by:\n---\n\nBody."
    meta, body = parse_frontmatter(text)
    assert meta["branch"] is None
    assert meta["claimed_by"] is None


def test_parse_inline_list():
    text = "---\ndepends_on: [T-0001, T-0002]\n---\n\nBody."
    meta, body = parse_frontmatter(text)
    assert meta["depends_on"] == ["T-0001", "T-0002"]


def test_parse_empty_list():
    text = "---\nlabels: []\n---\n\nBody."
    meta, body = parse_frontmatter(text)
    assert meta["labels"] == []


def test_parse_multiline_list():
    text = "---\nlabels:\n  - python\n  - auth\n---\n\nBody."
    meta, body = parse_frontmatter(text)
    assert meta["labels"] == ["python", "auth"]


def test_parse_quoted_value():
    text = '---\ntitle: "Fix: auth bug"\n---\n\nBody.'
    meta, body = parse_frontmatter(text)
    assert meta["title"] == "Fix: auth bug"


def test_parse_no_frontmatter():
    text = "Just plain text."
    meta, body = parse_frontmatter(text)
    assert meta == {}
    assert body == "Just plain text."


def test_serialize_roundtrip():
    meta = {
        "id": "T-0001",
        "title": "Fix bug",
        "status": "backlog",
        "labels": ["python", "auth"],
        "branch": None,
        "depends_on": [],
    }
    body = "## Description\n\nSome text."
    text = serialize_frontmatter(meta, body)
    meta2, body2 = parse_frontmatter(text)
    assert meta2["id"] == "T-0001"
    assert meta2["labels"] == ["python", "auth"]
    assert meta2["branch"] is None
    assert meta2["depends_on"] == []
    assert body2 == body


def test_serialize_value_with_spaces():
    meta = {"title": "Fix the auth bug"}
    body = "Body."
    text = serialize_frontmatter(meta, body)
    assert '"Fix the auth bug"' in text
