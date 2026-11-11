---
name: fix-issue
description: "Resolve a tracked issue through reproduction, root-cause repair, and a regression test."
---

# Fix Issue

Use this workflow for an issue reference, an `issues.md` entry, a bug report, or
a request to fix a known defect.

## Workflow

1. Resolve the repository and issue. Read the full report, comments, linked
   work, current code path, nearby tests, and current branch state.
2. Reproduce the behavior or establish another observable failure signal.
   Distinguish confirmed facts from assumptions and stale reports.
3. Trace the path that owns the behavior and fix the root cause. If the
   structure caused the defect, fix the structure.
4. Add a regression test that failed before the fix. Run the narrow checks and
   the repository's gate, then read the final diff once more.
5. Commit with `committer` and exact paths. The same commit adds the
   `CHANGELOG.md` line for a user-visible fix and removes the issue's
   `issues.md` entry. Other problems found on the way are fixed in their own
   commits, or go in `issues.md` when they need Hermes's decision.
6. Push to `origin` when the task came to you directly (`land`). When another
   agent dispatched you, leave the commits for it. Closing a tracker issue or
   deploying the fix follows the repository's own rules.

## Output

Report the cause, changed behavior, files, verification, delivery state, and
remaining risk. If blocked, preserve the work and name the exact missing fact
or external condition.
