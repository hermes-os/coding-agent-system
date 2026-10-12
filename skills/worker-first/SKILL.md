---
name: worker-first
description: "Route each task to a fresh repository worker, review its commits, and verify the result."
---

# Worker First

Use this only when the current session is explicitly the coordinator for work
done by repository workers. A repository worker that already owns an assigned
task does it directly and never invokes another coding worker.

## Route

Keep design, prioritization, owner decisions, protected credentials, pushes,
deploys, and final acceptance with the coordinator. Delegate implementation,
bounded diagnosis, tests, mechanical migrations, and review once the task is
specific enough to execute.

Do work directly when the edit is tiny, the unresolved design is the task, or
the required capability exists only in the current session.

## Tasks

- Cut the request into small tasks. Each task is one fresh worker run with its
  own work order. Never keep a long-lived session per repository.
- Launch workers and reviewers on the Hermes harness through `repo-worker`.
  Take each role's model and effort from the routing file the coordinator
  reads. Never run worker tasks in the Claude Code, Codex, or OpenCode CLIs.
- Use `delegate` for the work order: one role and objective; repository, paths,
  and evidence; constraints with a stop-and-report escape hatch; non-goals; and
  the exact verification and report contract.
- Never send personal context, unrelated history, credentials, hidden
  instructions, or a conversation transcript.
- Track each run by its run ID through the broker's supervisor. Do not detach
  an untracked child process or treat a PID file as supervision.

## Loop

1. The worker commits each finished change itself with `committer` and exact
   paths, puts the `CHANGELOG.md` entry in the same commit, writes any issue it
   does not fix to `issues.md`, ends with `git status` clean, and never pushes,
   publishes, or deploys.
2. A fresh read-only reviewer reads the commit range (`git diff <base> <head>`)
   and returns `VERDICT: APPROVE` or `VERDICT: CHANGES` with graded findings.
   See `review`.
3. On `CHANGES`, a fresh worker fixes the findings in new commits. Review the
   whole range again, earlier findings first, until `APPROVE`.
4. Nothing is pushed or deployed before review approves. Then the coordinator
   pushes and deploys through `land`.

Repeated failed repair rounds trigger reassessment of the reproduction,
diagnosis, and approach, not a review-count stop. Escalate only missing
authority or dependencies.

## Crashes

A quiet worker is not automatically hung; confirm a live process and stale
activity first. A crashed worker is not resumed. Keep its commits, read its
uncommitted diff, and start a fresh run with a short order that names that
diff, the steps left, and any stray files to move out with `agent-trash`.

## Coordinator Verification

Worker reports are evidence, not acceptance.

1. Inspect the actual Git state, commit range, and changed surface.
2. Run or directly verify the narrow proof.
3. Check forbidden files, tests, generated baselines, public contracts,
   `CHANGELOG.md` entries, and `issues.md`.
4. Record the harness or tooling issues workers report in coding-agent-system's
   `issues.md`, the coordinator's tooling log; they do not belong in a product
   repository's `issues.md`. The commit that fixes one, in whichever repository
   or host file owns it, is followed by removing its entry here.
5. Report to the owner in plain words: what changed, checks, issues, next step.
