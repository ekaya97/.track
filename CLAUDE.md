# CLAUDE.md

## Project

agent-track (`.track`) — lightweight ticketing & agent coordination for multi-agent coding workflows. Zero external dependencies, Python stdlib only.

## Dev

- `uv run pytest tests/ -q` — run tests
- `uv run track <command>` — run CLI
- `uv run track serve` — dashboard at http://localhost:7777

## Agent Protocol

Your session is **automatically tracked** via hooks. No registration, heartbeats, or deregistration needed.

Before starting work:
```bash
track board --last 10
track list
```

Create a ticket (auto-claimed to you):
```bash
track create --title "Fix auth bug" --desc "See docs/phase2-plan.md:45-72"
```

Create for another agent: `track create --title "..." --no-claim`

While working:
- Reference ticket IDs in git commits: `T-0001: fix token refresh`
- Check the board: `track board --last 10`
- Post to the board: `track board -m "message" --ticket T-NNNN`

When done:
```bash
track update T-NNNN --status review
```

## Rules

- One ticket at a time
- Check the board before starting work
- Reference ticket IDs in commits
- TDD: write tests first, then implement
- Never modify `.track/` files directly
