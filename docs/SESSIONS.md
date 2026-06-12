# Sessions

Alexis keeps an automatic, **per-directory session** so you can stop and resume work
in a project, and wipe a failed attempt to retry cleanly. Sessions live under the
per-user home, `~/.alexis/sessions/` (override the home with `$AI_AGENT_ALEXIS_HOME`).

## How it works

- A session is identified by a **SHA-256 of the current working directory** — running
  Alexis in the same folder always resumes that folder's session.
- Stored files (under `~/.alexis/sessions/`):
  - `index.sqlite` — registry of all sessions: `id`, `cwd`, `begin_ts`, `last_used_ts`
    (for fast listing and pruning).
  - `<id>.history.sqlite` — the conversation messages (owned by the CLI).
  - `<id>.todo.sqlite` — the todo plan (owned by the bundled todo MCP server, which is
    launched with `--session <id>`).

Subagents are ephemeral: they do **not** persist conversation history, and their todo MCP
server is launched with `--in-memory`, so a subagent's todo plan lives only in memory and
leaves **no files** behind. This keeps `~/.alexis/sessions/` to exactly three files per
session (`index.sqlite` is shared).
- On startup the CLI loads the history into the conversation and points the todo server
  at the session's database — so todo data no longer lands in the project folder.

## Defaults and flags

- Auto-session is **on by default** for interactive/textual and web (`api`) modes.
- `--no-session` — disable it; history is kept in memory for this run only.
- `--session PATH` — legacy mode: save/load the conversation as a JSON file and **disable**
  the automatic per-directory session.
- `--sessions-prune-days N` — remove stored sessions (history + todo) not used in the last
  N days, then continue. Removal is **manual only**; the current session is never pruned.
- Subagents never get a session (they're ephemeral).

## Clear vs. reset

- **Clear** (textual `/clear`, web `[CLEAR_LOG]` → `POST /clear`) is lightweight: it clears
  the on-screen/conversation transcript (keeping the system prompt). It does not touch the
  todo plan.
- **Reset** (textual `/reset` + menu, web `[RESET_SESSION]` → `POST /session/reset`) is a
  full wipe of the session: it clears the conversation history **and** the todo plan, for a
  clean retry of a failed run. The system prompt is preserved; the session id does not
  rotate (it's wiped in place).

> The live todo database is held open by the todo MCP server, so reset clears it
> **logically** via the `todo_clear` MCP tool rather than deleting the file. Subagents
> keep their todo in memory, so there's nothing to clean up for them. Pruning removes
> every `<id>.*` file for an inactive session.
