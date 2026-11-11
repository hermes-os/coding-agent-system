---
name: delegate
description: "Write a task for another agent and hand it to a worker as a kanban card."
---

# Delegate

The agent that takes the task has not seen this conversation. It owns the
codebase while it works: it reads the code, picks the design, and proves the
result. Give it what it cannot find out alone, and leave the how to it.

## The task

Write it for a capable engineer on a first day:

- **Outcome.** What should be true when the work is finished, in plain words.
- **Why it matters.** Who needs it and what it is for. This is what lets the
  agent make good calls you did not foresee.
- **Done.** How anyone can tell it is finished: the behavior to show, and the
  gate if it is not the one in the repository's `AGENTS.md`.
- **What you already know.** Exact symptoms, issue references, and evidence
  you gathered. Mark a guess as a guess.
- **Boundaries.** Only real ones: a branch someone else is changing, a decision
  that is Hermes's, a thing that cannot be undone.

Leave out step lists, file-by-file instructions, and the name of a model. If
the task needs steps to be safe, it is not understood well enough to hand over.
One task per card. Never include secrets, raw environment values, or a
conversation transcript.

## Handing it to a worker

A worker is the Hermes profile `worker`. It runs one kanban card in its own
container and sees only the clean clones under `~/workbench`, as they are on
the Git server. Push what the task depends on first.

```bash
./setup.sh repo <name>     # in the coding-agent-system checkout
hermes kanban create "<title>" --body-file task.md \
  --assignee worker --workspace worktree:$HOME/workbench/<name>
```

Inside the Hermes harness, `kanban_create` with assignee `worker`, workspace
kind `worktree` and workspace path `/home/hermes/workbench/<name>` does the
same. The board starts the worker. The worker commits on branch
`wt/<task-id>`, in the worktree `~/workbench/<name>/.worktrees/<task-id>`, and
hands the card to the `reviewer` profile. It cannot push.

When the card is done, the work is yours again: read the diff, merge the
branch, run the gate, and push to `origin`. A worker's report is evidence, not
acceptance. A blocked card holds a question for Hermes.
