# agent-track

Lightweight ticketing & agent coordination for multi-agent coding workflows.

Built to orchestrate multiple Claude Code sessions (or any AI agents) working on the same codebase in parallel. All state lives in a `.track/` directory as markdown and JSON files. No database, no external services, **zero dependencies** -- Python stdlib only.

## Install

```bash
pipx install agent-track    # recommended
# or
pip install agent-track
```

## Quick Start

```bash
track init                                          # create .track/ directory
track create --title "Fix auth bug" --priority high # create a ticket
track register --agent agent-alpha                  # register an agent
track claim T-0001 --agent agent-alpha              # claim the ticket
track update T-0001 --status in-progress --agent agent-alpha
track log T-0001 --agent agent-alpha -m "Found root cause in token_refresh()"
track board --agent agent-alpha -m "Starting work on auth module"
track list                                          # see all active tickets
track serve -d                                      # start web dashboard
```

## Features

- **Zero dependencies** -- pure Python stdlib, single `pip install`
- **File-based storage** -- markdown tickets + JSON agents in `.track/`
- **Concurrent-safe** -- `fcntl.flock` advisory locks, atomic writes
- **Web dashboard** -- kanban board at `localhost:7777` with auto-refresh
- **Agent coordination** -- heartbeats, file ownership tracking, message board
- **Git-friendly** -- all state is plain text, easy to commit and review

## Commands

| Command | Description |
|---------|-------------|
| `track init` | Create `.track/` directory structure |
| `track create --title "..." [-p priority] [-l labels]` | Create a ticket |
| `track list [--status X] [--agent X] [--label X]` | List tickets (excludes done by default) |
| `track show T-0001` | Print full ticket markdown |
| `track claim T-0001 --agent X` | Claim a ticket (checks dependencies) |
| `track update T-0001 --status X [--agent X]` | Update ticket (enforces valid transitions) |
| `track log T-0001 --agent X -m "message"` | Append to ticket work log |
| `track board --agent X -m "message"` | Post to the message board |
| `track board --last 10` | Read recent board entries |
| `track register [--agent X] [--capabilities python,ui]` | Register an agent |
| `track deregister --agent X [--release-tickets]` | Deregister an agent |
| `track files --add path --agent X --ticket T-0001` | Track file ownership |
| `track files --check path` | Check who owns a file |
| `track heartbeat --agent X` | Update heartbeat timestamp |
| `track stale [--reclaim]` | Detect/reclaim stale agents |
| `track serve [--port 7777] [-d]` | Start web dashboard |
| `track stop` | Stop background dashboard |

## Ticket Lifecycle

```
backlog -> claimed -> in-progress -> review -> done
```

Valid transitions are enforced. Use `--force` to override.

## TRACK_DIR Discovery

By default, `track` walks up from the current directory to find a `.track/` folder (like `git` finds `.git/`). You can override this with the `TRACK_DIR` environment variable:

```bash
TRACK_DIR=/path/to/.track track list
```

## Dashboard

Start the web dashboard with `track serve` (default port 7777). Use `-d` to daemonize:

```bash
track serve -d        # background mode
track stop            # stop the background server
```

The dashboard shows a kanban board, active agents, file ownership conflicts, and the message board. Auto-refreshes every 5 seconds.

## Platform

macOS and Linux only. Uses `fcntl.flock` for file locking and `os.fork()` for daemon mode, which are not available on Windows.

## License

MIT
