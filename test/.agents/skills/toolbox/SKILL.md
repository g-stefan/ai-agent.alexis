---
name: toolbox
description: Use this skill when the user asks for the current date or time, wants some text rendered as a big ASCII-art banner, or wants to evaluate a math expression. Runs the bundled helper scripts via skill_run.
license: MIT
---

# Toolbox

Small utility scripts. Run them with the `skill_run` tool, passing
`skill="toolbox"`, the script `name`, and any `arguments`.

| Script      | What it does                       | Example call                                                          |
|-------------|------------------------------------|----------------------------------------------------------------------|
| `date`      | Print the current date/time        | `skill_run(skill="toolbox", name="date")`                            |
| `ascii_art` | Render text as an ASCII-art banner | `skill_run(skill="toolbox", name="ascii_art", arguments=["HELLO"])`  |
| `calc`      | Evaluate a math expression         | `skill_run(skill="toolbox", name="calc", arguments=["2 * (3 + 4)"])` |

## date
- Optional first argument: a `strftime` format string.
- Default output: `YYYY-MM-DD HH:MM:SS`.

## ascii_art
- First argument: the text to render (uppercased; A–Z, 0–9 and space supported).
- Returns a multi-line ASCII banner.

## calc
- First argument: the expression. Only numbers and `+ - * / // % ** ( )` are
  allowed (it is parsed safely, not `eval`'d).

When a request matches, call the right script and show its output verbatim.
