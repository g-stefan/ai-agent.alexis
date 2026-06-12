# Todo system

A persistent, project-bound todo list the agent uses to track multi-step work
and resume after a restart. It is implemented as a bundled MCP server
(`mcp/mcp-server-todo.py`), a skill (`skills/todo/`) that tells the model the
system exists, and a side panel in the textual UI that shows the live plan.

## Pieces

| Piece | Role |
|-------|------|
| **MCP server** (`mcp-server-todo.py`) | Owns the data. Exposes `todo_*` tools (for the model) and a `todo://current` resource (for the UI). Persists to SQLite. |
| **Skill** (`skills/todo/SKILL.md`) | Progressive-disclosure hint so the model knows to use the todo tools for multi-step work and to resume via `todo_get`. |
| **UI panel** (`TodoPanel`) | Compact, clickable summary in the right sidebar: shows progress (`done/total`), a bar, and the active item. Clicking it opens a read-only modal (`TodoScreen`) with the description and full checklist. Reads the plan **over MCP**, never from disk. |

Enable it with `--agent-use-mcp-todo` (on by default). It is forwarded to
subagents like the other bundled servers.

## Storage

State lives in a project-bound SQLite database, by default
`.agents/repository/todo.sqlite` in the current folder (override with the
`MCP_TODO_DB` environment variable, mapped to the server as `DB`). The database uses
WAL mode and a busy timeout so reads and writes can overlap. Persisting to disk
is what makes a plan survive the agent being closed; the resume path then reads
it back through the server (below).

## Data shape

A plan is one **description** (what the overall work is for) plus an ordered list
of **items**, each with a status of `pending`, `in_progress`, or `completed`.
Both the tools and the resource return the same JSON:

```json
{
  "description": "Ship the feature",
  "items": [
    { "id": 1, "position": 0, "content": "Design",  "status": "completed" },
    { "id": 2, "position": 1, "content": "Build",   "status": "in_progress" },
    { "id": 3, "position": 2, "content": "Test",    "status": "pending" }
  ],
  "summary": "1/3 completed"
}
```

## Tools (model-facing)

The model manages the plan with these MCP tools:

- `todo_get()` — read the plan (call this first to resume).
- `todo_write(description, items)` — create/replace the whole plan atomically.
- `todo_set_status(id, status)` — flip one item's status.
- `todo_add(content, status="pending")` — append one item.
- `todo_clear()` — wipe items and reset the description.

## Read procedure (host/UI-facing)

The UI must show the plan and keep it current **without knowing where the data is
stored**. It does this by asking the server over the existing MCP connection,
rather than opening the database file.

### Why a resource, and what "stream" means here

MCP over stdio is a **single bidirectional JSON-RPC stream**: one pipe that
multiplexes many request/response pairs, each matched by its `id`. It is not
several separate streams — but because requests are multiplexed, the host can
issue its own request (read the plan) **concurrently** with the model's tool
calls on the same connection, and the responses are routed back independently.

The MCP-native way to expose readable state to a client is a **resource**. The
todo server publishes:

```
uri:       todo://current
mimeType:  application/json
```

### The exchange

1. The host (`cli.py`) captures the todo server's `ClientSession` after connect
   (`tool_to_session["todo_get"]`) and hands the UI an async callback,
   `fetch_todo()`.
2. `fetch_todo()` issues a standard MCP **`resources/read`** for
   `todo://current`:

   ```python
   res = await todo_session.read_resource(AnyUrl("todo://current"))
   plan = json.loads(res.contents[0].text)
   ```

3. The server's `resource_current()` handler reads the current state from SQLite
   and returns it as the JSON above, on the same stdio stream.
4. `TodoPanel` calls `fetch_todo()` once on mount (initial load / resume) and
   again on a short timer, re-rendering the checkboxes whenever the plan changes.
   Overlapping asks are dropped (an exclusive worker group), so a slow round-trip
   never piles up requests on the channel.

This means:

- The UI holds **no database path** and never touches the file — the storage
  location can change freely without touching the UI.
- The same `resources/read` call restores a plan saved by a previous run, giving
  the resume behaviour.
- The read goes through the live server, so it always reflects the server's own
  writes (no cross-process file/cache/cwd mismatch).

## Extending

To expose more project-bound state to the UI the same way, add another
`@mcp.resource("<scheme>://...")` to the relevant server and a matching
`read_resource` call on the host — no new file paths or polling of disk needed.
The `.agents/repository/` folder is the shared home for such project-bound data.
