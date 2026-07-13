---
name: portfolio
description: "Coordinate multi-repository or multi-phase work with ownership, leases, and recovery."
---

# Portfolio

Use this as the lean root orchestrator for multi-repository, multi-phase, or
continuously monitored work. The root coordinates; one repository worker owns
implementation and delivery for that repository.

## Inventory

Run a read-only inventory over the roots relevant to the request:

```bash
agent-repo-inventory --root ~/Desktop --root ~/Projects
```

Add other roots explicitly. The helper reports Git state and active
`docs/plan/*.md` files without fetching, switching branches, or changing files.

## Ownership

1. Reconcile inventory with current tasks, plans, CI, provider state, and the
   newest instructions. Adopt existing work instead of opening a duplicate.
2. Use exactly one mutation owner per repository. Read-only analysis, review,
   and monitoring may run concurrently; workers never create worker trees.
3. Process each repository queue serially through small landable milestones.
   Keep one heavy process per host and check headroom before broad work.
4. Classify only as actionable, externally waiting, or needing one exact owner
   decision after every safe reversible step is complete.

## Leases And Public Gate

The shared coordination repository is the installed agent-system checkout. Its
temporary remote lock refs provide atomic cross-host ownership without a diary.

```bash
head=$(git rev-parse HEAD)
repo_lease_id="$(agent-lease acquire "repo:<owner>/<repo>:write" --head "$head" | python3 -c 'import json,sys; print(json.load(sys.stdin)["lease_id"])')"
agent-lease verify "$repo_lease_id" --repo "$PWD" --head "$head"
public_lease_id="$(agent-lease acquire "public:mutation" --head "$head" | python3 -c 'import json,sys; print(json.load(sys.stdin)["lease_id"])')"
agent-lease verify "$public_lease_id" --repo "$PWD" --head "$head"
# Perform exactly one synchronous provider write here.
agent-lease release "$public_lease_id"
# Keep the repository lease while observing CI or deployment.
agent-lease release "$repo_lease_id"
```

- Acquire the repository lease before mutation ownership and renew it during
  long work. After committing the candidate, renew with `--head <sha>`. Acquire
  the global public lease second, immediately before a push, PR mutation, merge,
  workflow approval, release, deployment, or provider write.
- Private implementation and proof continue in parallel. Admit one new public
  write at a time. Release the public lease immediately after that synchronous
  write; never hold it while waiting for review, CI, or deployment.
- Recheck the exact candidate SHA after acquiring the public lease and directly
  before every irreversible boundary. Drift invalidates review and admission.
- Reacquire and reverify before each later public write. Keep the repository
  lease through active waits, then release it when repository ownership ends.
- TTL is limited to 24 hours. An expired lease remains owned until `agent-lease
  reap <scope>` succeeds after checking worker, GitHub, CI, deployment, and
  provider state; acquisition never reaps implicitly.
- Use operation plus candidate SHA as the idempotency key. Repeated automation
  wakes reconcile current state and become no-ops when the outcome already
  exists.

## Monitoring

The responsible worker stays active through tests, review, CI, and deployment
waits. A scheduled heartbeat only wakes the root to inspect workers, renew or
reconcile leases, refill completed lanes, and surface prepared decisions. It is
not project memory and does not replace a worker's active wait.

Track only the current phase: `queued`, `implementing`, `validating`,
`reviewing`, `ready`, `publishing`, `waiting`, `verified`, or `blocked`. Use the
repository plan for durable multi-session decisions, `handoff` when pausing,
and `pickup` when resuming. Never create a global append-only ledger.

Read `references/cursor-orchestration.md` only when configuring Cursor
Automations. Re-run inventory after landings and report repository, exact head,
phase, proof, next action, and blocker compactly.
