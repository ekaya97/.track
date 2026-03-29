# .track/ Agent Conventions

## Quick Start

1. **Register:**
   ```bash
   track register --agent {your-id} --capabilities python,ui
   ```

2. **Check available work:**
   ```bash
   track list --status backlog
   ```

3. **Read the board for context:**
   ```bash
   track board --last 10
   ```

4. **Claim a ticket:**
   ```bash
   track claim T-NNNN --agent {your-id}
   ```

5. **Start work:**
   ```bash
   track update T-NNNN --status in-progress --agent {your-id}
   ```

6. **Log progress:**
   ```bash
   track log T-NNNN --agent {your-id} -m "Description of progress"
   ```

7. **Track files you modify:**
   ```bash
   track files --add path/to/file.py --agent {your-id} --ticket T-NNNN
   ```

8. **Post to the board:**
   ```bash
   track board --agent {your-id} --ticket T-NNNN -m "Message"
   ```

9. **When done:**
   ```bash
   track update T-NNNN --status review --agent {your-id}
   ```

10. **Deregister on exit:**
    ```bash
    track deregister --agent {your-id} --release-tickets
    ```

## Rules

1. **One ticket per agent.** Do not claim multiple tickets simultaneously.
2. **Check the board before claiming.** Another agent may be about to claim the same ticket.
3. **Check file ownership.** Run `track files --check path/to/file.py` before modifying a file another agent is working on.
4. **Heartbeat.** Call `track heartbeat --agent {your-id}` periodically. Agents without heartbeat for 30 minutes are marked stale.
5. **Deregister on exit.** Always deregister, releasing tickets if work is incomplete.
6. **Communicate via board.** Do not modify another agent's ticket work log. Post on the board with the ticket ID instead.
7. **Small commits.** Reference the ticket ID in commit messages: `T-0001: move schema validation`

## Dashboard

```bash
track serve              # Start dashboard at http://localhost:7777
track serve -d           # Start in background (daemonize)
track stop               # Stop background dashboard
```

## Ticket Lifecycle

```
backlog -> claimed -> in-progress -> review -> done -> archive
```

## Board Tags

| Tag | Usage |
|-----|-------|
| `created` | Ticket was created |
| `claimed` | Agent claimed a ticket |
| `status:{s}` | Status changed |
| `registered` | Agent joined |
| `deregistered` | Agent left |
| `note` | General comment |
| `blocked` | Agent is blocked |
| `question` | Agent asks a question |
| `answer` | Response to a question |
| `conflict` | File ownership conflict |
