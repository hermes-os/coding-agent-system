---
name: fix-issue
description: "Resolve a tracked issue through reproduction, root-cause repair, tests, and commit-first review."
---

# Fix Issue

Use this workflow for an issue reference, an `issues.md` entry, a bug report, or
a request to fix a known defect. Read global and repository instructions before
acting.

## Workflow

1. Resolve the repository and issue. Read the full report, comments, linked
   work, current code path, nearby tests, and current branch state.
2. Reproduce the behavior or establish another observable failure signal.
   Distinguish confirmed facts from assumptions and stale reports.
3. Trace the owning path and fix the root cause with the smallest coherent
   change. Preserve unrelated work and established architecture.
4. Add a regression test that failed before the fix. Run the narrow checks and
   the repository's required gate, then recheck the final diff.
5. Commit with `committer` and exact paths. The same commit adds the
   `CHANGELOG.md` entry for a user-visible fix and removes the issue's
   `issues.md` entry. Other issues found on the way go in `issues.md`, in their own commit.
6. A fresh reviewer reads the commit range (`review`). Push, merge, deploy, or
   close the issue only after review approves, and only as the coordinator
   through `land`; a repository worker never does these.

A request to fix authorizes implementation, verification, and commits.

## Output

Report the cause, changed behavior, files, verification, delivery state, and
remaining risk. If blocked, preserve the work and name the exact missing fact
or external condition.
