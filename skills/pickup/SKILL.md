---
name: pickup
description: "Reconstruct unfinished work in a fresh session from repository evidence or a dead session."
---

# Pickup

A fresh session finishes the work; a crashed session is not resumed.
Rehydrate only the context needed to act:

1. Read global and repository instructions plus relevant scoped rules.
2. Read a supplied handoff.
3. Run `git status -sb`, inspect local commits, `issues.md`, and the
   `CHANGELOG.md` `## Unreleased` section, and identify branch/review state.
4. Inspect relevant CI, review feedback, sessions, and owned background work.
5. Confirm the latest verification evidence and choose the first check needed.
6. Summarize the next two or three actions, then execute them.

Treat current code, git, tests, and provider state as authoritative when a
handoff has drifted. Do not load unrelated historical plans or chats.

## Dead Session Recovery

Use local transcripts only when no adequate handoff exists or the prior session
died before writing one:

```bash
agent-session-recover find --cwd "$PWD" --query "<task terms>"
agent-session-recover render <session-path> --query "<task terms>"
```

The helper reads local Codex and Claude logs, emits only sanitized visible
turns, and omits reasoning, tool payloads, system policy, and secrets. Read the
smallest matching stdout extract and reconcile it against current evidence.
When a file is genuinely needed, use a private `mktemp` path and remove it as
soon as pickup is complete. Never auto-load transcript history.
