---
name: git-helper
description: Use this skill when the user mentions "git", "commit", "branch", "merge", "rebase", or "pull request". Returns exact, copy-pasteable git commands.
license: MIT
---

# Git Helper

When a git question matches:

1. Give the answer as one or more fenced `bash` code blocks with the exact
   commands, in order.
2. Add a one-line comment above each command explaining what it does.
3. Below the block, add a short **Heads up:** note for anything destructive
   (e.g. `reset --hard`, `push --force`).
4. Prefer safe defaults (e.g. `git switch -c` over `git checkout -b`).

Example shape:

```bash
# create and switch to a new branch
git switch -c feature/login
```
