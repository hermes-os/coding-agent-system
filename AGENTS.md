# Global Engineering System

Canonical, tool-, agent-, and model-agnostic policy. Host files only adapt this
policy to their runtime. Repository `AGENTS.md` files add project facts; active
skills add job workflows.

## Start

- Read the repository `AGENTS.md`, then load only relevant skills and documents.
- If `docs/` exists and `docs-list` is available, run it and read only matching
  documents. Database and model-boundary rules live in `docs/engineering/` of
  this repository; load them when the task touches either.
- Inspect real code, git state, and live provider state before deciding.
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
- Make the smallest coherent change that fixes the root cause, following
  existing architecture and dependencies.
- Preserve changes you did not make. Work with concurrent edits when possible.
- Use one heavy process at a time. Check host headroom before builds or broad
  tests, close only processes you own, and treat exit 137 as host starvation.
- Agent work defaults to write access with provider prompts bypassed; host
  launchers must set that mode explicitly rather than trust provider defaults.
  Read-only analysis is the exception: declare read access, disable bypass, and
  enforce a read-only filesystem boundary. Role names never change access.
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

## Structure

- Do not abstract before the second real caller; keep single-use values inline
  unless extraction materially improves clarity.
- Interfaces are justified only at external or nondeterministic boundaries:
  databases, identity providers, clocks, filesystems, email, network services,
  model providers, object storage, process execution. Never to mirror one
  internal class or to make a pure helper mockable.
- Do not pad for symmetry: two cases get two branches, not three examples.
- Prefer explicit data flow over hidden global state, and plain functions over
  classes when state and identity are unnecessary.
- No new dependency without explicit approval, and no framework, queue,
  service, or abstraction for hypothetical future use.

## Errors

- Catch only where you can recover, retry, translate, or add durable context.
  Never catch and continue; never catch only to rethrow unchanged.
- Invalid internal state is a failure, not a fallback: no silent fallback that
  masks missing data, no default that conceals absent required configuration.
- User input and external-service failures are expected boundary errors and
  must be translated deliberately.
- No redundant checks on values the type system guarantees.
- Error messages are terse, actionable, and greppable.

## Comments And Naming

- Comment why, never what; delete comments that restate the line below them.
- No hedge comments — implement the behavior or write `TODO(<ticket>):`.
  Banned: `in a real application`, `in production you would`, `handles most
  cases`, `for simplicity`, `for brevity`, `simplified version`, `left as an
  exercise`.
- No banner comments, no `Step 1:` narration, no emoji in source, logs, error
  messages, or test output, and never name the model, prompt, session, or
  generation process in source.
- Documentation scales with audience: public and exported APIs need it,
  internal helpers usually need only a clear signature and name, private
  one-liners need none.
- Name length scales with scope; annotate boundaries, not inferred values.

## Quality

- Define observable success criteria before substantial edits.
- Run narrow checks first, then the repository's required gate.
- Before delivery, run `agent-repo-check --repo "$PWD"` when available. It
  checks repository hygiene, not the project's own gate.
- Use `review` for non-trivial or risky diffs: freeze the exact candidate,
  validate its structured result, and verify each finding against real code.
  Reviews lead with concrete defects ordered by severity and cited to files;
  fix every verified defect promptly.
- Use `behavior-validator` when user-visible behavior needs source-blind proof.
- Never claim success without fresh evidence. Complete skipped checks before
  delivery and state residual risk plainly.
- Report final changed-file scope and verification evidence concisely.
- Prefer a deterministic gate over prose for anything a machine can check: the
  strictest practical type checker, a strict configuration schema rejecting
  unknown and missing keys, and residue blocked in CI. A hallucinated API or
  config key must fail at build or startup, not silently no-op.

## Tests

- Test observable behavior at the boundary, not the mock implementation.
- Every meaningful invalid or boundary condition gets a test; do not invent
  degenerate cases to satisfy a quota. A bugfix ships with a test that failed
  before the fix.
- Mock only nondeterministic or external boundaries, never pure code.
- No assertion-free tests, and none that only verify a mock was called unless
  the call is the contract.
- Test names state the behavior and its condition, not `works as expected`.
- Coverage is a regression guard, not evidence of test quality.

## Residue

- Ship the change, not a demo: no `__main__` blocks, sample invocations,
  playground code, or printed summaries in library code. Examples belong in
  tests, docs, examples directories, or dedicated CLI commands.
- Leave no temporary diagnostics, debug logs, commented experiments, or
  generated notes; keep investigation notes outside tracked source.
- Never commit prompt transcripts, model self-reviews, chain-of-thought,
  session links, model signatures, or placeholders such as `your-api-key`,
  `changeme`, and `lorem ipsum`.

## Anti-Rules

- The standard is not code that looks human, and thoroughness is not quality.
  More files, comments, interfaces, tests, and abstractions do not improve a
  change; every addition must earn its maintenance cost.
- Never fake scar tissue. Do not add inconsistent naming, arbitrary shortcuts,
  fake TODOs, unexplained exceptions, uneven formatting, or pointless
  duplication. History accumulates on its own once agents stop bulldozing
  existing code.
- Reject linters that manufacture the tell: docstrings on every private helper,
  minimum identifier lengths, mandatory comments for obvious code, abstraction
  quotas, or a ban on short names. Scope documentation rules to public APIs.
- Good code does not need to explain that it is good.

## Projects And Continuity

- Current code, git history, tests, and provider state are operational truth.
- Ordinary tasks need no plan file. Cross-cutting work spanning sessions gets
  one mutable `docs/plan/<project>.md` in the owning repository, holding only
  `summary` and `read_when` frontmatter, status, problem, goals, non-goals,
  decisions, milestones, verification, and open questions. Update it in place;
  never create parallel trackers.
- Milestones must be small and independently landable. Delivery follows the
  repository's branch and review convention.
- Use `portfolio` for cross-repository coordination. Keep one execution owner
  per repository; parallelize private analysis, then serialize shared public
  mutations with exact-head leases. Scheduled automation is a wake-up
  mechanism, never the coordination state: reconstruct status from repositories
  and active plans.
- Use `handoff` when pausing and `pickup` when resuming; handoffs report current
  evidence, not an append-only memory store.
- On completion, move durable product facts into canonical docs and user-facing
  changes into the changelog, which every repository keeps current. Keep a plan
  only while it retains unfinished work, and remove stale planning documents
  and obsolete tracking notes found in the active repository.

## Git And Delivery

- Safe inspection commands are always allowed.
- Never discard, overwrite, or revert unrelated work.
- Use `agent-trash` for routine deletion so recovery remains possible; delete
  permanently only when clearly warranted and within the task's scope.
- Prefer `committer` with explicit paths when creating a commit in a dirty or
  concurrently edited repository. Commit messages describe the product change,
  constraint, and migration impact.
- A request to implement authorizes local edits and tests. A request to land,
  ship, publish, or deploy authorizes the matching commit/push/deploy sequence.
- Destructive commands and irreversible production or data actions must remain
  inside the user's stated scope. Clarify only genuinely ambiguous boundaries.

## Roles And Skills

- Roles describe jobs and output contracts, never model identities.
- The task prompt may assign any model to any role. Never pin models in shared
  policy, skills, hooks, launchers, or generated configuration; a provider
  default may live in local host state but assigns no role or acceptance.
  Record the actual model in artifacts as provenance, not acceptance.
- Shared workflows live globally in one canonical `SKILL.md`; product-specific
  ones live under `.agents/skills/<name>/SKILL.md` in their repository. Keep
  deterministic scripts, detailed references, and hooks beside their owning
  skill. Host-specific files may point to canonical sources but must never
  duplicate workflow policy, and global hook configuration only dispatches to
  active skill manifests.
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
- Never use a persistent persona, journal, auto-memory, or session diary as
  project memory, and do not load historical context unless the task names it.

## Have Fun And Make Cool Stuff

- Always aim to make cool stuff that works, is good, and is fast.
- Don't be a Goofus
