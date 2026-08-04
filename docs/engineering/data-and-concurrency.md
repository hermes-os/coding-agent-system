---
summary: Query, transaction, pagination, and concurrency rules for any repository with a database.
read_when:
  - Writing or reviewing database queries, transactions, or pagination.
  - Adding concurrent data access.
---

# Data And Concurrency

Rules for any repository that uses a database.

- No query in a loop without an explicit reason why batching is impossible.
  Reduce query count before parallelizing queries.
- Never fan out unbounded concurrent database work.
- Every list query has deterministic ordering; every paginated query has a
  stable unique tie-breaker. Prefer cursor pagination for large or mutable sets.
- Database constraints enforce uniqueness and referential integrity. An
  application pre-check does not replace a constraint.
- Use idempotent writes where repeated requests are expected.
- Keep transactions short. Never hold one open across network calls, file
  generation, model calls, user interaction, or long computation.
- Set explicit command timeouts and propagate cancellation.
- No `SELECT *` outside disposable scripts. Review indexes alongside new
  high-volume query paths.
- Derived summaries are projections, never the source of truth. Measure before
  introducing replicas, sharding, or distributed caches.
