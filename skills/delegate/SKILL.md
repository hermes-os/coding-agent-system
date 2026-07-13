---
name: delegate
description: "Write a standalone role assignment for another engineering agent."
---

# Delegate

Produce a compact prompt that a fresh agent can execute without hidden context.

Include:

- assigned role and concrete objective
- repository or product identity and current state
- relevant symbols, modules, issue or PR references, and exact symptoms
- constraints, ownership boundaries, and explicit non-goals
- evidence already gathered without presenting assumptions as facts
- expected verification and output contract
- external actions that are or are not in scope

Assign the job, never a model identity. Ask the receiving agent to inspect the
real repository and challenge stale assumptions before editing. Do not include
secrets, raw environment values, giant conversation dumps, or unrelated history.
