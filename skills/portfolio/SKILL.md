---
name: portfolio
description: "Inventory and coordinate active work across repositories without a persistent diary."
---

# Portfolio

Use this workflow for multi-repository status, maintenance, prioritization, or
continued autonomous work across projects.

## Inventory

Run a read-only inventory over the roots relevant to the request:

```bash
agent-repo-inventory --root ~/Desktop --root ~/Projects
```

Add other roots explicitly. The helper reports Git state and active
`docs/plan/*.md` files without fetching, switching branches, or changing files.

## Coordination

1. Reconcile inventory with current tasks, reviews, CI, provider state, and the
   newest user instructions. Current repository evidence outranks old handoffs.
2. Reserve repositories already owned by another active task. Use one execution
   owner per repository and serialize shared landing, release, and production
   boundaries.
3. Classify work as actionable, waiting on an external condition, or requiring
   one owner decision. Prefer independently verifiable milestones.
4. Assign roles by job and output contract through `delegate`; never pin a
   model. Keep one heavy process per host at a time.
5. Resume through each repository's active plan and `pickup`. Use `handoff` when
   pausing. Do not create a global diary or append-only portfolio memory.
6. Re-run the inventory after landings and report repository, branch, status,
   proof, next action, and blocker in a compact table or list.

Mutation, landing, release, and deployment remain governed by each task's
stated scope and repository convention.
