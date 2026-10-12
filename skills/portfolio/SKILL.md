---
name: portfolio
description: "Coordinate work across several repositories or tasks with fresh workers and commit-first review."
---

# Portfolio

Use this when one request spans several repositories or several tasks. The
coordinator plans, routes, verifies, pushes, and deploys; repository workers do
the work. Route each task through `worker-first`.

## Control Plane

- Cut the request into small tasks. Each task is one fresh worker run; there
  are no persistent per-repository sessions.
- One write worker per repository folder at a time; the broker enforces it.
  Read-only review, inspection, and inventory may run alongside.
- Give tasks that run together different files. Keep one heavy build or test
  run per host and check headroom before broad work.
- The coordinator owns prioritization, owner questions, cross-repository
  conflicts, and every push and deploy.
- Prompt text never changes a worker's real permissions. Verify the effective
  access before its first protected write or network action, then surface one
  exact blocker instead of repeatedly retrying a denied operation.

## Inventory

Run a read-only inventory over the roots relevant to the request:

```bash
agent-repo-inventory --root ~/Desktop --root ~/Projects
```

Add other roots explicitly. The helper reports Git state and any
`docs/plan/*.md` files without fetching, switching branches, or changing files.
Read each repository's `issues.md` and `CHANGELOG.md` `## Unreleased` section
for open issues and unshipped changes.

## Queue

1. Reconcile inventory with the newest instructions, commits, CI, and
   `issues.md`. Adopt existing work instead of opening a duplicate.
2. Process each repository's tasks serially: worker commits, fresh reviewer
   reads the range, fresh fix worker on `CHANGES`, re-review until `APPROVE`,
   then the coordinator lands it.
3. Classify each repository only as actionable, externally waiting, or needing
   one exact owner decision after every safe reversible step is complete.
4. Refill an idle slot only with qualified in-scope work. Do not create work to
   satisfy a concurrency target.

## Records

The commit log, `CHANGELOG.md`, and `issues.md` are the only records. Keep no
ledger, plan, watch file, or hand-off file. Report repository, exact head,
review verdict, checks, next action, and blocker compactly.

For an owner decision, present the repository, current evidence, the smallest
decision being asked, at most two options with a pick, and what continues
while the answer is pending.

## Cross-Host Peers

`agent-lease` and `agent-forge-handoff` stay installed for cross-host peer work
through pull requests. Hermes's own repositories do not use leases or peer
handoffs. Read `references/forge-peer-handoff.md` only when configuring a peer
watcher; keep host polling in the owning host integration.
