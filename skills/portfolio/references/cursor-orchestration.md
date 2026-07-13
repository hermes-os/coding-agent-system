# Cursor Orchestration Automation

Create this only for an explicitly monitored project or portfolio. Attach the
owning repositories. The schedule is a wake-up signal; repository state, plans,
GitHub, provider state, and remote leases remain authoritative.

Recommended schedule: every five minutes while active, disabled when all work
is terminal. Event-triggered review remains separate.

```text
Enter the global portfolio job. Read global policy, portfolio, and only the
repository skills and active plans needed for current work. Do not use or write
Cursor Memories and do not maintain an append-only global log.

Reconstruct current phases from repositories, GitHub, CI, deployments, and
agent-lease status. Adopt existing work and never create a second mutation
owner for one repository. Read-only monitoring may run concurrently. Keep one
heavy operation per host.

For an actionable repository, acquire its write lease before mutation. Before
any push, PR mutation, merge, workflow approval, release, deployment, or
provider write, acquire public:mutation second and verify the exact candidate
head. Use operation plus candidate SHA as the idempotency key. Let an admitted
public sequence reach a safe boundary, then release public and repository
leases in reverse order.

Reap an expired lease only after verifying its worker and external operation
are no longer active. Continue active waits through terminal CI or deployment
state. Surface only one exact access, irreversible choice, or genuine product
decision after every safe reversible action is complete.
```

Keep implementation workers and the heartbeat distinct. The heartbeat
reconciles, renews, and refills; the repository owner implements and waits.
