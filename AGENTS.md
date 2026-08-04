# Global Engineering System

Canonical, tool-, agent-, and model-agnostic policy. Host files only adapt this
policy to their runtime. Repository `AGENTS.md` files add project facts; active
skills add job workflows.

## Start

- Read the repository `AGENTS.md`, then load only relevant skills and documents.
- If `docs/` exists and `docs-list` is available, run it and read only matching
  documents.
- Inspect the real code, git state, nearby patterns, and live provider state
  before deciding.
- Read the entire target file before editing it. Read its direct callers,
  callees, and tests when behavior crosses the file boundary.
- Inspect neighboring files to learn local conventions, and follow the
  repository's current framework, language, and module conventions. Do not
  import idioms from another version of the stack.
- Read file history before changing a workaround, a security boundary,
  compatibility logic, code whose purpose is unclear, or behavior with a
  surprising constraint.
- Search the repository and standard library before introducing a new symbol,
  helper, configuration key, or pattern. Reuse an existing utility that fits.
- Treat a user's requested outcome and commands as authorization for the work
  they plainly require. Do not ask for the same approval at every step.
- Ask once only when required information cannot be discovered and guessing
  could cause an unintended irreversible or external effect.

## Work

- Own an assigned task through implementation, verification, and handoff.
- Make the smallest coherent change that fixes the root cause.
- Follow existing architecture and dependencies. Avoid speculative features,
  broad refactors, and unrelated cleanup.
- Preserve changes you did not make. Work with concurrent edits when possible.
- Use one heavy process at a time. Check host headroom before builds or broad
  tests, close only processes you own, and treat exit 137 as host starvation.
- Agent work defaults to write access with provider approval prompts bypassed.
  Host launchers must make that mode explicit instead of relying on mutable
  provider defaults.
- Read-only analysis and review are the exception: declare read access, disable
  provider bypass, and enforce a read-only filesystem boundary where the host
  supports one. Role names alone never change access.
- Keep secrets out of output, commits, logs, prompts, and new files.

## Scope

- Touch only the lines the task requires. A one-line fix stays a one-line diff.
- No drive-by reformatting, renaming, cleanup, or style normalization outside
  scope. Format only the files you touched.
- Leave unrelated TODOs, commented-out code, and local idiom inconsistencies
  alone unless asked.
- Do not rewrite working code to express a personal preference, and preserve
  existing public behavior unless the task explicitly changes it.
- Do not combine feature work with dependency upgrades, formatting migrations,
  or broad refactors.
- More files, comments, interfaces, tests, and abstractions do not improve a
  change. Every addition must earn its maintenance cost.

## Structure

- Do not abstract before the second real caller. Keep single-use values inline
  unless extraction materially improves clarity.
- Interfaces are justified at external or nondeterministic boundaries:
  databases, identity providers, clocks, filesystems, email, network services,
  model providers, object storage, and process execution. Do not create one to
  mirror a single internal class, or to make a pure helper mockable.
- Do not pad for symmetry. Two cases get two branches, not three examples.
- Prefer explicit data flow over hidden global state, and ordinary functions
  over classes when state and identity are unnecessary.
- No new dependency without explicit approval. Do not introduce a framework,
  queue, service, or abstraction for hypothetical future use.

## Errors

- Catch only at a boundary where you can recover, retry, translate, or add
  durable context. Never catch and continue, and never catch only to rethrow
  unchanged.
- Invalid internal state is a failure, not a fallback. No silent fallbacks that
  mask missing or invalid data, and no default values concealing absent
  required configuration.
- User input and external-service failures are expected boundary errors and
  must be translated deliberately.
- No redundant null or existence checks on values the type system guarantees.
- Error messages are terse, actionable, and greppable.

## Comments And Naming

- Comment why, never what. Delete comments that restate the line below them.
- No hedge comments. Either implement the behavior or write `TODO(<ticket>):`.
  Banned: `in a real application`, `in production you would`, `handles most
  cases`, `for simplicity`, `for brevity`, `simplified version`, `left as an
  exercise`.
- No banner or divider comments, and no `Step 1:` narration in source.
- No emoji in source, logs, error messages, or test output.
- Never mention the model, prompt, session, or generation process in source.
- Documentation scales with audience: public and exported APIs need useful
  documentation, internal helpers usually need only a clear signature and name,
  private one-liners need none.
- Name length scales with scope. Short-lived locals and loop indices stay
  short; exported symbols get descriptive names.
- Annotate boundaries, not values the checker infers.

## Quality

- Define observable success criteria before substantial edits.
- Add or update focused tests for changed behavior when practical.
- Run narrow checks first, then the repository's required gate.
- Before delivery, run `agent-repo-check --repo "$PWD"` when available. It
  validates instruction, skill, hook, plan, and clutter hygiene; it does not
  replace the repository's project-specific gate.
- Use `review` for non-trivial or risky diffs. Freeze the exact candidate,
  validate its structured result, and verify each finding against real code.
- Use `behavior-validator` when user-visible behavior needs source-blind proof.
- Never claim success without fresh evidence. Complete skipped checks before
  delivery and state residual risk plainly.
- Reviews lead with concrete defects ordered by severity and cited to files.
  Promptly fix every verified defect.
- Prefer a deterministic gate over prose for anything a machine can check.
  Repositories should run the strictest practical type checker, parse
  configuration through a strict schema that rejects unknown and missing keys,
  and block residue in CI. A hallucinated API or configuration key must fail at
  build or startup, not silently no-op.

## Tests

- Test behavior at the boundary, not the mock implementation. Prefer observable
  outcomes over implementation-detail assertions.
- Every meaningful invalid or boundary condition gets a test. Do not invent
  degenerate edge cases to satisfy a quota.
- A bugfix ships with a test that failed before the fix.
- Mock only nondeterministic or external boundaries. Do not mock pure code.
- No assertion-free tests, and no test that only verifies a mock was called
  unless the call is the contract.
- Test names state the behavior and its condition. Avoid `should work
  correctly`, `handles valid input`, and `works as expected`.
- Coverage is a regression guard, not evidence of test quality.

## Residue

- Ship the change, not a demo. No `__main__` demo blocks, sample invocations,
  playground code, or printed summaries in library code. Examples belong in
  tests, documentation, examples directories, or dedicated CLI commands.
- Leave no temporary diagnostics, debug logs, commented experiments, or
  generated notes. Keep investigation notes outside tracked source.
- Never commit prompt transcripts, model self-reviews, chain-of-thought,
  session links, or model signatures.
- No placeholder residue: `your-api-key`, `changeme`, `lorem ipsum`, and
  similar.
- Commit messages describe the product change, constraint, and migration
  impact.

## Data And Concurrency

- No query in a loop without an explicit reason why batching is impossible.
  Reduce query count before parallelizing queries.
- Do not fan out unbounded concurrency over a collection of queries.
- Every list query has deterministic ordering; every paginated query has a
  stable unique tie-breaker. Prefer cursor pagination for large or mutable
  result sets.
- Database constraints enforce uniqueness and referential integrity.
  Application pre-checks do not replace them.
- Use idempotent writes where repeated requests are expected.
- Keep transactions short. Never hold one open across network calls, file
  generation, model calls, user interaction, or long computation.
- Set explicit command timeouts and propagate cancellation.
- No `SELECT *` outside disposable scripts. Review indexes alongside new
  high-volume query paths.
- Derived summaries are projections, not the source of truth. Measure before
  introducing replicas, sharding, or distributed caches.

## Generated Content

- Model output is untrusted input. Parse and validate it before use, and never
  let a model waive validation, authorization, or publication rules.
- Keep prompts, provider SDKs, retries, token accounting, and raw responses
  behind a dedicated boundary. Core domain code must not depend on a model
  provider.
- Store accepted outputs and concise provenance, not chain-of-thought or
  self-review prose. Model commentary is not documentation, and automated
  critique is advisory until converted into a deterministic check.
- Human approval remains explicit where output is published, safety-sensitive,
  legally meaningful, or hard to reverse.
- Parallel model calls are an execution strategy, not a licence for autonomous
  orchestration. Do not introduce an agent framework where a deterministic
  workflow with explicit stages suffices.
- Every generated artifact carries an input identity, generator or rule
  version, creation timestamp, validation status, and a stable content hash
  where reproducibility matters.

## Anti-Rules

- The standard is not code that looks human. Optimize for code that is correct,
  context-aware, consistent with local conventions, minimally scoped, explicit
  about real boundaries, and tested at meaningful failure points.
- Never fake scar tissue. Do not add inconsistent naming, arbitrary shortcuts,
  fake TODOs, unexplained exceptions, uneven formatting, or pointless
  duplication. History accumulates on its own once agents stop bulldozing
  existing code.
- Reject linters that manufacture the tell: docstrings on every private helper,
  minimum identifier lengths, mandatory comments for obvious code, uniform
  naming across differing scopes, abstraction quotas, or a blanket ban on short
  names. Scope documentation rules to public APIs and durable boundaries.
- Good code does not need to explain that it is good.

## Projects And Continuity

- Current code, git history, tests, and provider state are operational truth.
  Do not use a persistent persona or session diary as project memory.
- Ordinary tasks need no plan file. Cross-cutting work spanning sessions gets
  one mutable `docs/plan/<project>.md` in the owning repository.
- An active plan contains only `summary` and `read_when` frontmatter, status,
  problem, goals, non-goals, decisions, milestones, verification, and open
  questions. Update it in place; never create parallel trackers.
- Milestones must be small and independently landable. Delivery follows the
  repository's branch and review convention.
- Use `portfolio` for continuous or cross-repository coordination. Keep one
  execution owner per repository; parallelize private analysis, then serialize
  shared public mutations with exact-head leases.
- Scheduled automation is a wake-up mechanism, never the coordination state.
  Reconstruct status from repositories and active plans, not a global diary.
- Use `handoff` when pausing and `pickup` when resuming. Handoffs report current
  evidence; they are not an append-only memory store.
- On completion, move durable product facts into canonical docs and user-facing
  changes into the changelog. Every repository maintains an up-to-date
  changelog. Keep a plan only while it retains unfinished work; otherwise
  remove it.
- Remove stale planning documents discovered in the active repository. Keep
  repositories free of obsolete tracking files and notes.

## Git And Delivery

- Safe inspection commands are always allowed.
- Never discard, overwrite, or revert unrelated work.
- Use `agent-trash` for routine deletion so recovery remains possible. Use
  permanent deletion only when clearly warranted and within the task's scope.
- Prefer `committer` with explicit paths when creating a commit in a dirty or
  concurrently edited repository.
- A request to implement authorizes local edits and tests. A request to land,
  ship, publish, or deploy authorizes the matching commit/push/deploy sequence.
- Destructive commands and irreversible production or data actions must remain
  inside the user's stated scope. Clarify only genuinely ambiguous boundaries.
- Report final changed-file scope and verification evidence concisely.

## Roles And Skills

- Roles describe jobs and output contracts, never model identities.
- The task prompt may assign any available model to any role. Do not pin models
  in shared policy, skills, hooks, launchers, or generated agent configuration.
  A provider-required operator default may remain in local host state; it does
  not assign a model to a role or acceptance decision.
- Record the actual model in generated artifacts as provenance, not acceptance.
- Shared workflows live globally in one canonical `SKILL.md`. Product-specific
  workflows live in their repository under `.agents/skills/<name>/SKILL.md`.
- Put deterministic scripts and detailed references beside their owning skill.
  Host-specific files may point to canonical sources but must not duplicate
  workflow policy.
- Skill hooks live with the skill. Global hook configuration only dispatches
  to active global and repository skill manifests.
- Use `maintain-skills` for catalog hygiene and `capabilities` when the current
  host's available tooling is unclear.

## Repository Adapters

- A repository guide begins with: `READ ~/.agents/AGENTS.md BEFORE ANYTHING
  (skip if missing).`
- Keep repository guides factual and short: architecture, invariants, commands,
  delivery conventions, and pointers to repo-owned skills.
- Use one root `AGENTS.md`. Add nested guides only for genuinely distinct
  subtrees. Compatibility files such as `CLAUDE.md` should point to it.

## Context

- When context exceeds 55%, use `handoff` and ask the user to clear context.
- Do not create persistent personas, journals, auto-memory, or session diaries.
- Do not load historical context unless the task explicitly names it.
- Prefer current repository state, tests, and source-of-truth files over notes.

## Have Fun And Make Cool Stuff

- Always aim to make cool stuff that works, is good, and is fast.
- Don't be a Goofus
