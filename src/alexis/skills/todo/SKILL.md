---
name: todo
requires: mcp-todo
description: Track multi-step work with a persistent project todo list — a plan description plus checkable items (pending / in_progress / completed) stored in .agents/repository/todo.sqlite. Use it whenever a task has several steps, when you want progress shown live in the UI side panel, or to resume work after the agent was closed. Backed by the bundled todo MCP server (todo_* tools).
---

# Todo system

You have a **persistent todo list** for the current project, provided by the
bundled todo MCP server. It survives the agent being closed: the state lives in
`.agents/repository/todo.sqlite` in the project folder, and the UI renders it
live in the right-hand panel with checkboxes, so the user can watch progress and
you can pick the work back up after a restart.

A plan has two parts:

1. A **description** — one short line saying what the overall work is for.
2. An ordered list of **items**, each with a status: `pending`,
   `in_progress`, or `completed`.

## When to use it

- Any task that takes **more than ~3 steps**, or spans multiple tool calls.
- Long-running or multi-session work where you may be interrupted and need to
  **resume** later — always `todo_get` first to recover the plan.
- When the user explicitly asks for a plan, checklist, or progress tracking.

For a single trivial action, skip it — don't track one-step work.

## Tools

- `todo_get()` — read the current plan (description, items, completion summary).
  **Call this at the start of a session** to resume an existing plan before
  creating a new one.
- `todo_write(description, items)` — create or replace the whole plan atomically.
  `items` is an ordered list of objects like
  `{"content": "Write the parser", "status": "pending"}` (status optional,
  defaults to `pending`). Use it to lay out the plan and to rewrite it when the
  steps change.
- `todo_set_status(id, status)` — flip one item by its `id` (from `todo_get` /
  `todo_write`) to `pending`, `in_progress`, or `completed`. Prefer this for
  ticking items off rather than rewriting the list.
- `todo_add(content, status="pending")` — append one new item without touching
  the others.
- `todo_clear()` — wipe all items and reset the description when the work is done
  or you are starting unrelated work.

## How to work with it

1. **Resume or start.** Call `todo_get`. If a relevant plan already exists,
   continue it; otherwise `todo_write` a fresh one with a clear description.
2. **Mark one item `in_progress`** before you begin it, so the UI shows what is
   active. Keep only one item in progress at a time.
3. **Mark it `completed`** as soon as it is genuinely done (via
   `todo_set_status`), then move to the next.
4. **Keep the plan honest** — if scope changes, update items with `todo_write`
   or `todo_add` instead of leaving the list stale.
5. When everything is complete, either leave the finished list for the user to
   see, or `todo_clear` if starting something new.
