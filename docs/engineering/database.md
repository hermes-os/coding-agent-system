---
summary: Query, transaction, and concurrency rules for any repository backed by a database.
read_when:
  - Adding or changing a query, migration, index, transaction, or background job.
  - Reviewing a change that fans out concurrent work over a collection.
---

# Database And Concurrency

These rules apply to any codebase that uses a database. Repositories without
one can ignore this document.

## Query Shape

- No query in a loop without an explicit reason explaining why batching is
  impossible.
- Reduce query count before parallelizing queries. Fewer round trips beats
  faster round trips.
- Never fan out unbounded concurrency over a collection of queries. `Promise.all`,
  `Task.WhenAll`, and goroutine fan-out over an unbounded collection are all the
  same defect.
- Separate latency-sensitive and batch workloads through bounded pools or
  explicit concurrency limits.
- No `SELECT *` outside disposable scripts.
- Review indexes alongside any new high-volume query path.

## Ordering And Pagination

- Every list query has deterministic ordering.
- Every paginated query has a stable unique tie-breaker.
- Prefer cursor pagination for large or mutable result sets.

## Integrity

- Database constraints enforce uniqueness and referential integrity.
  Application pre-checks do not replace them.
- Use idempotent writes wherever repeated requests are expected.

## Transactions

- Keep transactions short.
- Never hold a transaction open across network calls, file generation, model
  calls, user interaction, or long-running computation.
- Set explicit command timeouts and propagate cancellation.

## Derived Data

- Read models and summaries are allowed when they reduce repeated aggregation.
- Derived summaries are projections, never the source of truth.
- Measure before introducing replicas, sharding, or distributed caches.
