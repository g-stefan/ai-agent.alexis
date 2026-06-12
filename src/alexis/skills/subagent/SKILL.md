---
name: subagent
requires: internal-mcp-subagent
description: Delegate work to autonomous subagents with the subagent_run tool, acting like a team manager. Break a job into small steps (a todo list helps), then delegate steps one at a time rather than forwarding the whole request to one subagent. Also good for delegating verification/QC and any work that would otherwise flood your own limited context. Reach for it on multi-step jobs or when checking something directly would cost a lot of context.
---

# Delegating work to a subagent

`subagent_run(prompt="...")` spawns a fresh, autonomous agent with its own copy
of your tools and skills, runs your prompt to completion, and returns **only its
final answer** (no thinking or tool traces). Use it to keep your own limited
context clean: the subagent absorbs the heavy lifting, you get back a short result.

**Work like a team manager:** hold the plan, delegate the legwork, integrate the
results.

## How to delegate well

- **Break the job down first.** Split a big request into small, concrete steps —
  a todo list (see the [[todo]] skill) is a good way to track them. Delegate the
  steps; don't just forward the user's whole request to one subagent (that only
  moves the problem).
- **One step at a time.** Hand off a single well-defined piece, integrate the
  result, then do the next — passing along the context the finished steps produced.
- **Delegate verification too.** Reviewing a big file, diff, or log is itself
  context-hungry; let a separate subagent check it and report back a short verdict
  (e.g. "PASS/FAIL + any issues as bullets with line numbers").
- **Make each prompt stand alone.** The subagent can't see this conversation, so
  include the goal, the context it needs (paths, names, decisions), and the output
  you want back. It runs to completion without asking questions.

## When to just do it yourself

Trivial or single-step work, anything needing tight back-and-forth or your own
judgement at each step, or cases where you need to see the intermediate steps —
not just the result.

When a result comes back, integrate it (or delegate a fix) and move on.
