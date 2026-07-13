---
name: fix-issue
description: "Resolve a tracked issue through reproduction, root-cause repair, tests, and authorized delivery."
---

# Fix Issue

Use this workflow for an issue reference, bug report, or request to fix a known
defect. Read global and repository instructions before acting.

## Workflow

1. Resolve the repository and issue. Read the full report, comments, linked
   work, current code path, nearby tests, and current branch state.
2. Reproduce the behavior or establish another observable failure signal.
   Distinguish confirmed facts from assumptions and stale reports.
3. Trace the owning path and fix the root cause with the smallest coherent
   change. Preserve unrelated work and established architecture.
4. Add focused regression coverage when practical. Update canonical docs or a
   changelog only when the repository uses them and behavior changed.
5. Run narrow checks, an independent `review` for non-trivial risk, and the
   repository's required gate. Recheck the final diff.
6. If the request includes land, ship, push, merge, close, or equivalent
   delivery intent, activate `land` and complete that authorized sequence.
   Comment on or close the issue only after remote state and proof agree.

A request to fix authorizes implementation and verification. Delivery language
authorizes the matching external sequence once; do not insert repeated gates.

## Output

Report the cause, changed behavior, files, verification, delivery state, and
remaining risk. If blocked, preserve the work and name the exact missing fact
or external condition.
