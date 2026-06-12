---
name: subagent
description: Delegate work to autonomous subagents with the subagent_run tool, acting like a team manager. CRITICAL: first break the request into small, concrete steps and a todo list, then delegate ONE step at a time — never forward the user's whole task to a single subagent. Use it to offload each focused piece of work (research, building one component, analysing a large file) and to delegate verification/QC (checking a big file or output you don't need to read yourself), so fresh agents do the heavy lifting and return only short results, keeping your own context clean. Reach for this on any multi-step job, or when checking something directly would flood your context.
---

# Delegating work to a subagent

You have a **`subagent_run`** tool. Calling it spawns a fresh, fully autonomous
agent that runs its **own** agentic conversation — with its own copy of the
tools and skills you have — on a prompt you give it, and returns **only its final
answer text** (none of its thinking or tool traces). It is the way to hand off a
self-contained piece of work.

```
subagent_run(prompt="<a complete, standalone description of the task>")
```

**Think of yourself as a team manager.** Your context window is limited, so you
shouldn't personally do or read everything. You direct a team: one subagent does
the work, another independently verifies it, another researches — and each hands
you back a short result. Your job is to break the work down, delegate, and
integrate, not to pour every file and every check into your own context.

## Break the work down FIRST — don't hand off the whole task

The most common and most damaging mistake is to take the user's whole request and
forward it to a single subagent. **That solves nothing.** The subagent now faces
the exact same large, under-specified job you did — you've just moved the problem
and are now waiting on a copy of yourself. Delegation only helps when each
handed-off piece is **small and well-defined**.

So before you delegate anything:

1. **Decompose the request into concrete, small steps.** Think through the whole
   job first and list the individual pieces. For *"build a website with several
   pages"* that is: decide the site structure, build the Home page, build the
   About page, build the Contact page, add the shared stylesheet, link the pages
   together — **not** "build the website".
2. **Write a todo list** of those steps (use the [[todo]] skill) so the plan is
   explicit, tracked, and resumable, and the user can see progress.
3. **Delegate ONE step at a time.** Hand a single, fully-specified step to a
   subagent, wait for its result, integrate it, mark that todo item done, then
   move to the next step — passing along whatever context the finished steps
   produced (e.g. the structure you settled on, the stylesheet name).

A handed-off step should be something a subagent can finish in one focused pass
and return a concrete result for — *"build the About page with sections X, Y, Z
using styles.css"*, not *"build the site"*. If you find yourself writing a
subagent prompt that is basically the user's whole request reworded, **stop and
break it down further.**

You stay the manager who holds the plan and sequences the work; the subagents do
the legwork one piece at a time.

## Why delegate

- **Keep your context clean.** A subtask that would flood your context with tool
  output (reading many files, long searches, trial-and-error) runs in the
  subagent's context instead; you get back just the result.
- **Offload self-contained work.** Research a question, build a component, refactor
  a module, analyse a document — anything you can describe completely up front.
- **Stay focused.** Break a large job into pieces, delegate the well-defined ones,
  and integrate the results yourself.

## Delegate verification too, not just the work

Verifying is work — and often the *most* context-hungry kind, because it means
reading large files, diffs, logs, or test output. Don't pull all that into your
own context just to check it. Delegate the check to a **separate** subagent and
ask for a short report back.

- **Separate the doer from the checker.** Have one subagent produce the work, then
  a *different* subagent verify it — independent QC, like a team where one group
  builds and another tests. The verifier starts fresh, so it isn't biased by the
  builder's reasoning.
- **Only verify what needs it.** If you can already tell the result is fine, don't
  spend a subagent on it. Reach for a verification subagent when checking directly
  would cost a lot of context (a big file, a long output, a wide change) or when
  an independent second pair of eyes genuinely adds confidence.
- **Ask for a short report, not the raw material.** Tell the verifier exactly what
  to check and to return a concise verdict — e.g. *"pass/fail, then up to 5 bullets
  on any problems found, with file:line references."* You get the conclusion
  without the bulk.

Example: instead of reading a 2,000-line generated file yourself, run
`subagent_run(prompt="Review the file <path>. Check that <criteria>. Report
PASS/FAIL and list any issues as bullets with line numbers. Do not paste the file
back.")` and act on the short report.

## When NOT to delegate

- Trivial or single-step work you can just do — delegation has overhead.
- Work needing tight back-and-forth with the user, or your own judgement at each
  step (the subagent runs to completion on its own and only returns at the end).
- Anything where you need to see the intermediate steps, not just the result.

## Writing the prompt

The subagent **does not see your conversation** — it starts fresh. So the prompt
must stand alone:

1. **State the goal** plainly and completely.
2. **Include the context it needs** — file paths, names, constraints, prior
   decisions — since it can't read your history.
3. **Specify the output** you want back (e.g. "return the final function body",
   "answer in 3 bullet points", "return the file path you wrote").
4. **Scope it to one self-contained task.** Don't ask for something that needs to
   check back with you midway.

A good prompt reads like a task you could hand to a competent colleague who knows
nothing about this conversation.

## After it returns

Treat the returned text as the result of the subtask: verify it, integrate it,
and continue. If it's wrong or incomplete, refine the prompt and delegate again,
or finish the work yourself.

> Note: subagents may themselves delegate, but recursion depth is bounded — don't
> rely on deeply nested delegation. Prefer one clear level of hand-off.
