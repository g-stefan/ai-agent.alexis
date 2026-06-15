# AI-Agent.Alexis
# SPDX-FileCopyrightText: 2026 Grigore Stefan <g_stefan@yahoo.com>
# SPDX-License-Identifier: Apache-2.0

"""Per-directory session storage under ``<alexis_home>/sessions/``.

Each working directory maps to one stable session, identified by a SHA-256 of
the absolute (case-normalised) directory path. A session owns:

  - ``index.sqlite``           — a registry of all sessions (id, cwd, timestamps)
  - ``<id>.history.sqlite``    — the conversation messages (owned by the CLI)
  - ``<id>.todo.sqlite``       — the todo plan (owned by the todo MCP server)
  - ``<id>.provider.json``     — the LLM provider chosen for this folder (UI)

Re-running Alexis in a directory resumes that directory's session; a reset wipes
its history and todo for a clean retry. This module is pure stdlib and never
imports from ``cli`` — the caller passes ``alexis_home()`` in — so it can be
unit-tested and reused (e.g. by the todo server) without import cycles.
"""

import os
import glob
import json
import time
import hashlib
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Iterator


# ── Paths ────────────────────────────────────────────────────────────────

def sessions_dir(alexis_home: str) -> str:
    """Return ``<alexis_home>/sessions``, creating it on demand."""
    path = os.path.join(alexis_home, "sessions")
    os.makedirs(path, exist_ok=True)
    return path


def session_id_for_cwd(cwd: Optional[str] = None) -> str:
    """Stable session id for a directory: SHA-256 of its absolute, case- and
    separator-normalised path. ``C:\\X`` and ``c:/x`` therefore map to one id."""
    raw = os.path.abspath(cwd if cwd is not None else os.getcwd())
    norm = os.path.normcase(os.path.normpath(raw))
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def history_db_path(alexis_home: str, sid: str) -> str:
    return os.path.join(sessions_dir(alexis_home), f"{sid}.history.sqlite")


def todo_db_path(alexis_home: str, sid: str) -> str:
    """Path the todo MCP server mirrors when launched with ``--session <id>``.
    (Subagents don't use this — they run their todo in-memory.)"""
    return os.path.join(sessions_dir(alexis_home), f"{sid}.todo.sqlite")


def index_db_path(alexis_home: str) -> str:
    return os.path.join(sessions_dir(alexis_home), "index.sqlite")


def provider_path(alexis_home: str, sid: str) -> str:
    """Path of the per-session LLM provider file (``<id>.provider.json``).
    Holds the provider name the user selected for this folder in the UI, so the
    choice is remembered across runs. Pruned alongside the session's other files
    by :func:`prune_sessions` (it matches ``<id>.*``)."""
    return os.path.join(sessions_dir(alexis_home), f"{sid}.provider.json")


# ── Per-session provider choice (<id>.provider.json) ─────────────────────

def provider_load(alexis_home: str, sid: str) -> Optional[str]:
    """Return the provider name remembered for this session, or None when none
    is stored / the file is unreadable."""
    path = provider_path(alexis_home, sid)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        name = data.get("provider") if isinstance(data, dict) else None
        return str(name) if name else None
    except Exception:
        return None


def provider_save(alexis_home: str, sid: str, name: str) -> None:
    """Remember ``name`` as this session's provider. Best-effort: errors are
    swallowed like the rest of the session persistence."""
    try:
        path = provider_path(alexis_home, sid)
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"provider": name}, f)
    except Exception:
        pass


# ── Shared sqlite helper ─────────────────────────────────────────────────

def _connect(path: str) -> sqlite3.Connection:
    """Open a sqlite DB (creating the folder) with WAL + a busy timeout, so
    concurrent readers/writers across processes don't error out."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def _db(path: str) -> Iterator[sqlite3.Connection]:
    """Open a connection and ALWAYS close it on exit. ``with conn:`` (the sqlite
    context manager) only commits — it leaves the handle open, which leaks
    descriptors and keeps the file locked so prune can't remove it."""
    conn = _connect(path)
    try:
        yield conn
    finally:
        conn.close()


# ── Registry (index.sqlite) ──────────────────────────────────────────────

def registry_init(alexis_home: str) -> None:
    """Create the session registry table if absent."""
    with _db(index_db_path(alexis_home)) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS sessions (
                id           TEXT PRIMARY KEY,
                cwd          TEXT NOT NULL,
                begin_ts     REAL NOT NULL,
                last_used_ts REAL NOT NULL
            )"""
        )
        conn.commit()


def registry_touch(alexis_home: str, sid: str, cwd: str) -> None:
    """Record a session as used now: insert it (begin = last = now) on first
    sight, otherwise just bump ``last_used_ts``."""
    now = time.time()
    with _db(index_db_path(alexis_home)) as conn:
        cur = conn.execute(
            "UPDATE sessions SET last_used_ts = ?, cwd = ? WHERE id = ?",
            (now, cwd, sid),
        )
        if cur.rowcount == 0:
            conn.execute(
                "INSERT INTO sessions (id, cwd, begin_ts, last_used_ts)"
                " VALUES (?, ?, ?, ?)",
                (sid, cwd, now, now),
            )
        conn.commit()


def registry_reset_begin(alexis_home: str, sid: str) -> None:
    """Mark a session as freshly started (begin = last = now) — used on reset."""
    now = time.time()
    with _db(index_db_path(alexis_home)) as conn:
        conn.execute(
            "UPDATE sessions SET begin_ts = ?, last_used_ts = ? WHERE id = ?",
            (now, now, sid),
        )
        conn.commit()


def registry_list(alexis_home: str) -> List[Dict[str, Any]]:
    """Return all registered sessions, most-recently-used first."""
    path = index_db_path(alexis_home)
    if not os.path.isfile(path):
        return []
    with _db(path) as conn:
        rows = conn.execute(
            "SELECT id, cwd, begin_ts, last_used_ts FROM sessions"
            " ORDER BY last_used_ts DESC"
        ).fetchall()
    return [
        {"id": r[0], "cwd": r[1], "begin_ts": r[2], "last_used_ts": r[3]}
        for r in rows
    ]


# ── History store (<id>.history.sqlite) ──────────────────────────────────

def history_init(path: str) -> None:
    """Create the messages table if absent."""
    with _db(path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS messages (
                seq     INTEGER PRIMARY KEY AUTOINCREMENT,
                role    TEXT,
                content TEXT NOT NULL
            )"""
        )
        conn.commit()


def history_load(path: str) -> List[Dict[str, Any]]:
    """Return the stored message list (in order). Empty when absent/unreadable.
    Each message dict is stored whole as JSON, so tool_calls / images /
    attachments survive a round-trip losslessly."""
    if not os.path.isfile(path):
        return []
    try:
        with _db(path) as conn:
            rows = conn.execute(
                "SELECT content FROM messages ORDER BY seq"
            ).fetchall()
        out: List[Dict[str, Any]] = []
        for (content,) in rows:
            try:
                out.append(json.loads(content))
            except Exception:
                continue
        return out
    except Exception:
        return []


def history_save(path: str, messages: List[Dict[str, Any]]) -> None:
    """Persist the whole message list (replace-all in one transaction), matching
    the JSON session's full-dump-every-save semantics. Best-effort: swallows
    errors like the legacy ``save_state`` does."""
    try:
        history_init(path)
        with _db(path) as conn:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM messages")
            conn.executemany(
                "INSERT INTO messages (role, content) VALUES (?, ?)",
                [
                    (
                        (m.get("role") if isinstance(m, dict) else None),
                        json.dumps(m, ensure_ascii=False),
                    )
                    for m in messages
                ],
            )
            conn.commit()
    except Exception:
        pass


def history_wipe(path: str) -> None:
    """Empty the messages table (keep the file/schema). Safe while the CLI owns
    the file; used by reset together with a re-save of the system-only list."""
    try:
        history_init(path)
        with _db(path) as conn:
            conn.execute("DELETE FROM messages")
            conn.commit()
    except Exception:
        pass


# ── Prune (manual only) ──────────────────────────────────────────────────

def prune_sessions(alexis_home: str, days: int,
                   keep_id: Optional[str] = None) -> List[str]:
    """Remove sessions whose ``last_used_ts`` is older than ``days`` days:
    delete their history + todo sqlite files (and WAL sidecars) and their
    registry row. The current session (``keep_id``) is never pruned, and any
    session whose files are still locked is skipped (left for next time).
    Returns the list of pruned ids."""
    path = index_db_path(alexis_home)
    if not os.path.isfile(path):
        return []
    cutoff = time.time() - max(0, days) * 86400
    sdir = sessions_dir(alexis_home)
    pruned: List[str] = []
    for entry in registry_list(alexis_home):
        sid = entry["id"]
        if sid == keep_id or entry["last_used_ts"] > cutoff:
            continue
        # Remove every file belonging to this session: history, todo, any
        # suffixed (subagent) todo, plus their -wal/-shm sidecars.
        ok = True
        for f in glob.glob(os.path.join(glob.escape(sdir), glob.escape(sid) + ".*")):
            try:
                os.remove(f)
            except OSError:
                ok = False
        if not ok:
            # Something is still locked — keep the row so we retry later.
            continue
        try:
            with _db(path) as conn:
                conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
                conn.commit()
            pruned.append(sid)
        except Exception:
            pass
    return pruned
