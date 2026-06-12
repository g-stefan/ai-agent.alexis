# MCP Todo
# SPDX-FileCopyrightText: 2026 Grigore Stefan <g_stefan@yahoo.com>
# SPDX-License-Identifier: Apache-2.0

"""Persistent project todo list, backed by SQLite.

The list has a single *plan description* (what the work is for) and an ordered
set of *items*, each with a status (pending / in_progress / completed). State
lives in a project-bound SQLite database — by default
``.agents/repository/todo.sqlite`` in the current folder — so a plan survives the
agent being closed and can be resumed later. The bundled textual UI reads the
same database read-only and renders the list with checkboxes in its side panel.
"""

import os
import sys
import json
import sqlite3
import argparse
import datetime
import uvicorn
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from mcp.server.fastmcp import FastMCP
from typing import Any, List, Optional
from pathlib import Path

# --- Pre-parse --env-base ---
# A separate parser that ignores unknown args grabs the env-base prefix early,
# because we need it to resolve module-level configuration below — same pattern
# as the other bundled servers (mcp-server-workspace.py).
pre_parser = argparse.ArgumentParser(add_help=False)
pre_parser.add_argument("--env-base", type=str, default="")
pre_parser.add_argument("--tool-prefix", type=str, default="todo_")
pre_parser.add_argument("--mcp-name", type=str, default="Todo")
pre_parser.add_argument("--session", type=str, default="")
pre_parser.add_argument("--in-memory", dest="in_memory", action="store_true")
pre_args, _ = pre_parser.parse_known_args()

ENV_PREFIX = pre_args.env_base
TOOL_PREFIX = pre_args.tool_prefix
MCP_NAME = pre_args.mcp_name
SESSION_ID = pre_args.session
IN_MEMORY = pre_args.in_memory


def get_env_var(name: str, default: Any = None) -> Any:
    """Get an environment variable, optionally applying the env-base prefix."""
    if ENV_PREFIX:
        prefix = ENV_PREFIX if ENV_PREFIX.endswith("_") else f"{ENV_PREFIX}_"
        env_key = f"{prefix}{name}"
    else:
        env_key = name
    return os.environ.get(env_key, default)


def _alexis_home() -> str:
    """Per-user home dir: ``$AI_AGENT_ALEXIS_HOME`` or ``~/.alexis`` — mirrors
    ``cli.alexis_home()`` so this standalone server resolves session paths to the
    same place the agent does."""
    env = os.environ.get("AI_AGENT_ALEXIS_HOME")
    if env and env.strip():
        return os.path.abspath(os.path.expanduser(env.strip()))
    return os.path.join(os.path.expanduser("~"), ".alexis")


def _resolve_db_path() -> str:
    """Resolve the database path. Precedence:
      1. an explicit <PREFIX>_DB env var (power-user override, e.g. MCP_TODO_DB)
      2. ``--session <id>`` -> <alexis_home>/sessions/<id>.todo.sqlite (the
         per-directory session store, keeping todo data out of the project folder)
      3. legacy project-bound default ``.agents/repository/todo.sqlite``
    """
    explicit = get_env_var("DB")
    if explicit:
        return explicit
    if SESSION_ID:
        return os.path.join(_alexis_home(), "sessions", f"{SESSION_ID}.todo.sqlite")
    return os.path.join(".agents", "repository", "todo.sqlite")


# With --in-memory nothing is written to disk: the plan lives only for the life
# of this process. Used by subagents, whose todo lists are throwaway scratch and
# should never leave files behind.
DB_PATH = ":memory:" if IN_MEMORY else _resolve_db_path()
# Port for HTTP mode, defaulting to 48103 (workspace=48101, skills=48102).
PORT = int(get_env_var("PORT", "48103"))

# The three states an item can be in. Anything else is normalised to "pending".
VALID_STATUS = ("pending", "in_progress", "completed")


def _now() -> str:
    """Current local timestamp, second precision, ISO-8601."""
    return datetime.datetime.now().isoformat(timespec="seconds")


def _normalise_status(status: Any) -> str:
    """Map a variety of spellings onto the three canonical statuses."""
    s = str(status or "").strip().lower().replace("-", "_").replace(" ", "_")
    if s in ("completed", "complete", "done", "finished"):
        return "completed"
    if s in ("in_progress", "inprogress", "doing", "active", "started", "wip"):
        return "in_progress"
    return "pending"


# In --in-memory mode every call must reuse ONE connection: a fresh
# ``:memory:`` connection gets its own empty database, so the plan would vanish
# between tool calls. We keep a single shared connection alive for the process.
_mem_conn: Optional[sqlite3.Connection] = None


def _connect() -> sqlite3.Connection:
    """Return a database connection. For a file database this is a fresh
    connection (WAL, so the UI can read while we write); for ``--in-memory`` it is
    a single shared, process-lifetime connection holding the throwaway plan."""
    global _mem_conn
    if IN_MEMORY:
        if _mem_conn is None:
            _mem_conn = sqlite3.connect(":memory:", timeout=5, check_same_thread=False)
            _mem_conn.execute("PRAGMA busy_timeout=5000")
        return _mem_conn
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _init_db() -> None:
    """Create the schema if absent and ensure the single plan row exists."""
    with _connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS plan (
                id          INTEGER PRIMARY KEY CHECK (id = 1),
                description TEXT NOT NULL DEFAULT '',
                updated_at  TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS todo (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                position   INTEGER NOT NULL,
                content    TEXT NOT NULL,
                status     TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT,
                updated_at TEXT
            )"""
        )
        conn.execute(
            "INSERT OR IGNORE INTO plan (id, description, updated_at) VALUES (1, '', ?)",
            (_now(),),
        )
        conn.commit()


def _read_state() -> dict:
    """Return the current plan description and items as a plain dict."""
    with _connect() as conn:
        row = conn.execute("SELECT description FROM plan WHERE id = 1").fetchone()
        description = row[0] if row else ""
        items = [
            {"id": r[0], "position": r[1], "content": r[2], "status": r[3]}
            for r in conn.execute(
                "SELECT id, position, content, status FROM todo ORDER BY position, id"
            )
        ]
    done = sum(1 for it in items if it["status"] == "completed")
    return {
        "description": description,
        "items": items,
        "summary": f"{done}/{len(items)} completed",
    }


# ---
# Initialize the MCP Server and database.
mcp = FastMCP(MCP_NAME, stateless_http=True, json_response=False)
_init_db()


@mcp.tool(name=f"{TOOL_PREFIX}write")
async def tool_write(description: str, items: Optional[List[dict]] = None) -> dict:
    """Create or replace the whole todo plan in one atomic call.

    Use this to start a plan or to rewrite it after the steps change. Pass the
    plan `description` (a short statement of what the overall work is for) and the
    full ordered list of `items`. Each item is an object with a `content` string
    and an optional `status` of "pending", "in_progress", or "completed"
    (defaults to "pending"). The list is stored in order; existing items are
    replaced. Returns the resulting plan.
    """
    items = items or []
    now = _now()
    try:
        with _connect() as conn:
            conn.execute(
                "UPDATE plan SET description = ?, updated_at = ? WHERE id = 1",
                (str(description or ""), now),
            )
            conn.execute("DELETE FROM todo")
            for pos, it in enumerate(items):
                if isinstance(it, dict):
                    content = str(it.get("content", "")).strip()
                    status = _normalise_status(it.get("status"))
                else:
                    content = str(it).strip()
                    status = "pending"
                if not content:
                    continue
                conn.execute(
                    "INSERT INTO todo (position, content, status, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (pos, content, status, now, now),
                )
            conn.commit()
    except Exception as e:
        return {"error": f"Could not write plan: {e}"}
    return _read_state()


@mcp.tool(name=f"{TOOL_PREFIX}get")
async def tool_get() -> dict:
    """Return the current plan: its description, the ordered items with their
    statuses, and a short completion summary. Call this to resume after a
    restart or to check progress before deciding what to do next."""
    try:
        return _read_state()
    except Exception as e:
        return {"error": f"Could not read plan: {e}"}


@mcp.tool(name=f"{TOOL_PREFIX}set_status")
async def tool_set_status(id: int, status: str) -> dict:
    """Update a single item's status by its `id` (as returned by todo_get /
    todo_write). `status` is "pending", "in_progress", or "completed". Use this
    to tick an item off without rewriting the whole list. Returns the plan."""
    try:
        with _connect() as conn:
            cur = conn.execute(
                "UPDATE todo SET status = ?, updated_at = ? WHERE id = ?",
                (_normalise_status(status), _now(), int(id)),
            )
            conn.commit()
            if cur.rowcount == 0:
                return {"error": f"No item with id {id}."}
    except Exception as e:
        return {"error": f"Could not update item: {e}"}
    return _read_state()


@mcp.tool(name=f"{TOOL_PREFIX}add")
async def tool_add(content: str, status: str = "pending") -> dict:
    """Append a single new item to the end of the list, without disturbing the
    existing items. `status` defaults to "pending". Returns the plan."""
    content = str(content or "").strip()
    if not content:
        return {"error": "content is empty."}
    now = _now()
    try:
        with _connect() as conn:
            row = conn.execute("SELECT COALESCE(MAX(position), -1) FROM todo").fetchone()
            pos = (row[0] if row else -1) + 1
            conn.execute(
                "INSERT INTO todo (position, content, status, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (pos, content, _normalise_status(status), now, now),
            )
            conn.commit()
    except Exception as e:
        return {"error": f"Could not add item: {e}"}
    return _read_state()


@mcp.tool(name=f"{TOOL_PREFIX}clear")
async def tool_clear() -> dict:
    """Remove every item and reset the plan description to empty. Use this when
    the work is finished or you are starting an unrelated plan. Returns the
    (now empty) plan."""
    try:
        with _connect() as conn:
            conn.execute("DELETE FROM todo")
            conn.execute(
                "UPDATE plan SET description = '', updated_at = ? WHERE id = 1",
                (_now(),),
            )
            conn.commit()
    except Exception as e:
        return {"error": f"Could not clear plan: {e}"}
    return _read_state()


@mcp.resource("todo://current", name="Current todo plan", mime_type="application/json")
async def resource_current() -> str:
    """The current todo plan as JSON — the read side of the host/UI procedure.

    A client (the agent's UI) asks for the live plan by issuing an MCP
    `resources/read` for the URI ``todo://current``; the server answers with this
    JSON over the same stdio JSON-RPC stream. Because the UI reads through the
    server it never needs to know where the database lives, and the same call
    restores a plan saved by a previous run (resume). The payload mirrors
    todo_get:

        {
          "description": "<what the work is for>",
          "items": [{"id": 1, "position": 0, "content": "...", "status": "pending"}, ...],
          "summary": "<done>/<total> completed"
        }
    """
    try:
        return json.dumps(_read_state())
    except Exception as e:
        return json.dumps({"error": f"Could not read plan: {e}",
                           "description": "", "items": [], "summary": ""})


# --- Authentication Middleware ---


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    """Middleware to enforce API key authentication for incoming HTTP requests."""

    def __init__(self, app, api_key: str):
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        x_api_key = request.headers.get("X-API-Key")

        provided_key = None
        if auth_header and auth_header.startswith("Bearer "):
            provided_key = auth_header.split(" ", 1)[1]
        elif x_api_key:
            provided_key = x_api_key

        if not provided_key or provided_key != self.api_key:
            return JSONResponse(
                {"detail": "Unauthorized: Invalid or missing API Key"}, status_code=401
            )

        return await call_next(request)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Todo MCP Server")
    parser.add_argument("--stdio", action="store_true", help="Run in standard stdio mode")
    parser.add_argument("--mcp", action="store_true", help="Run in HTTP mode (default mode)")
    parser.add_argument("--api-key", type=str, help="Require API key for HTTP requests")
    parser.add_argument(
        "--env-base",
        type=str,
        help="Prefix for environment variables to isolate different servers (e.g., PREFIX)",
    )
    parser.add_argument("--tool-prefix", type=str, default="todo_", help="Prefix for MCP tools")
    parser.add_argument("--mcp-name", type=str, default="Todo", help="MCP name, default: Todo")
    parser.add_argument("--session", type=str, default="", help="Session id: store the database at <alexis-home>/sessions/<id>.todo.sqlite (where alexis-home is $AI_AGENT_ALEXIS_HOME or ~/.alexis), instead of the project-local .agents/repository/todo.sqlite. An explicit DB env var still overrides this.")
    parser.add_argument("--in-memory", dest="in_memory", action="store_true", help="Keep the plan in memory only — nothing is written to disk and it is discarded when the process exits. Used by subagents so they leave no todo files behind.")

    args = parser.parse_args()

    # In stdio mode standard out must stay clean for JSON-RPC, so logs go to stderr.
    _db_label = "(in-memory)" if IN_MEMORY else os.path.abspath(DB_PATH)
    print(f"[*] Todo MCP server — database: {_db_label}", file=sys.stderr)
    if ENV_PREFIX:
        actual_prefix = ENV_PREFIX if ENV_PREFIX.endswith("_") else f"{ENV_PREFIX}_"
        print(
            f"Using environment variable prefix: '{actual_prefix}' (e.g., expecting {actual_prefix}DB)",
            file=sys.stderr,
        )

    if args.stdio:
        mcp.run()
    else:
        starlette_app = mcp.streamable_http_app()
        if args.api_key:
            starlette_app.add_middleware(APIKeyAuthMiddleware, api_key=args.api_key)
        starlette_app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        uvicorn.run(starlette_app, host="127.0.0.1", port=PORT)
