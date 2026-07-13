---
name: handoff
description: "Package unfinished engineering work for a clean continuation session."
---

# Handoff

Inspect current evidence and return concise bullets in this order:

1. Scope and status: objective, completed work, pending work, and blockers.
2. Working tree: `git status -sb` summary and unpushed local commits.
3. Branch and review: branch, relevant PR or review, and CI status if known.
4. Running processes: relevant sessions, servers, tests, debuggers, or scripts;
   include copy-paste attach or capture commands.
5. Verification: commands run, results, and checks still due.
6. Next steps: the next actions in execution order.
7. Risks: flaky checks, credentials, feature flags, brittle areas, and
   irreversible boundaries.

Do not create a diary or append-only handoff file. Update an existing active
project plan only when its durable status, milestones, or open questions changed.
