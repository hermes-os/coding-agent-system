---
name: pickup
description: "Reconstruct and resume unfinished repository work from current evidence."
---

# Pickup

Rehydrate only the context needed to act:

1. Read global and repository instructions plus relevant scoped rules.
2. Run `docs-list` when available and read only documents matching the task.
3. Read a supplied handoff and the one active project plan relevant to the task.
4. Run `git status -sb`, inspect local commits, and identify branch/review state.
5. Inspect relevant CI, review feedback, sessions, and owned background work.
6. Confirm the latest verification evidence and choose the first check needed.
7. Summarize the next two or three actions, then execute them.

Treat current code, git, tests, and provider state as authoritative when a
handoff or plan has drifted. Do not load unrelated historical plans or chats.
