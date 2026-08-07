---
name: portfolio
description: "Coordinate multi-repository or multi-phase work with ownership, leases, and recovery."
---

# Portfolio

Use this as the lean root orchestrator for multi-repository, multi-phase, or
continuously monitored work. The root coordinates; one repository worker owns
implementation and delivery for that repository.

## Control Plane

- For a sustained queue, use exactly one root-owned persistent project session
  per repository. Reuse it until the repository queue is complete.
- A project session processes its queue serially and never creates another
  mutation-owning worker, task session, or worktree.
- Classify support work before delegation. Parallel support may inspect,
  monitor, or independently analyze, but remains read-only and owns no
  deliverable or public action.
- The root owns prioritization, project-session lifecycle, owner questions,
  cross-repository conflicts, and final admission to public actions.
- Prompt text never changes a worker's real permissions. Verify the effective
  profile before its first protected write or network action, then surface one
  exact blocker instead of repeatedly retrying a denied operation.

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
5. Refill an idle lane only with qualified in-scope work. Do not create work to
   satisfy a concurrency target or duplicate an existing session.

## Leases And Public Gate

The installer records one shared coordination repository in
`~/.agents/config.json`. A standalone install defaults to this system checkout;
an integration layer such as the VM setup may select its own Git repository.
Temporary remote lock refs provide atomic cross-host ownership without a diary.

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

When continuous orchestration is active, use one five-minute root watch. On
every wake, reconcile the latest worker status and instruction before acting;
never create duplicate watches. Keep it active while workers, external waits,
owner decisions, or qualified refill work remain, and disable it when the
portfolio is complete or the owner stops orchestration.

Track only the current phase: `queued`, `implementing`, `validating`,
`reviewing`, `ready`, `publishing`, `waiting`, `verified`, or `blocked`. Use the
repository plan for durable multi-session decisions, `handoff` when pausing,
and `pickup` when resuming. Never create a global append-only ledger.

For an owner decision, present the exact repository and URL, current evidence,
the smallest decision being asked, realistic options and tradeoffs, a
recommendation, and what continues privately while the answer is pending.
Other qualified private lanes stay active.

Read `references/cursor-orchestration.md` only when configuring Cursor
Automations. Re-run inventory after landings and report repository, exact head,
phase, proof, next action, and blocker compactly.

## GitHub Peer Handoff

Use `agent-forge-handoff` when enrolled hosts exchange implementation, review,
or Mac-only validation through a pull request. Its comments are constrained,
machine-addressed events tied to the current PR SHA; they never grant mutation,
arbitrary-command, merge, or deployment authority. Mutating commands are
dry-run by default and require an exact-head `public:mutation` lease with
`--apply`.

Use the bounded `discover` operation with the recipient's constant queue label
for portfolio wake-ups. Lifecycle comments and queue-label signals are separate
idempotent writes, each admitted under its own public lease. Local
`githubPeer.localPeer` configuration binds a host to `mac-cal` or `vm-cal` even
when both share one trusted GitHub login. PR comment scans and whole operations
are capped, discovery overscans a bounded recent candidate set without
exceeding its output limit, and every write rechecks the live PR head after
lease admission. Enrollment is read only from the canonical host config or a
root-controlled pointer; the public CLI cannot replace it.

Read `references/forge-peer-handoff.md` before configuring a peer watcher or
publishing a handoff. Keep host polling and launch behavior in the owning host
integration, not this portable skill.
