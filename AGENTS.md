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
- Keep secrets out of output, commits, logs, prompts, and new files.

## Quality

- Define observable success criteria before substantial edits.
- Add or update focused tests for changed behavior when practical.
- Run narrow checks first, then the repository's required gate.
- Use an assigned `review` role for non-trivial or risky diffs. Reviews are
  advisory: verify each finding against the real code before acting.
- Use `behavior-validator` when user-visible behavior needs source-blind proof.
- Never claim success without fresh evidence. State skipped checks and residual
  risk plainly.
- Reviews lead with concrete defects ordered by severity and cited to files.

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
- Use `handoff` when pausing and `pickup` when resuming. Handoffs report current
  evidence; they are not an append-only memory store.
- On completion, move durable product facts into canonical docs and user-facing
  changes into the changelog when used. Keep a plan only when it retains unique
  architectural value; otherwise delete it.

## Git And Delivery

- Safe inspection commands are always allowed.
- Never discard, overwrite, or revert unrelated work.
- A request to implement authorizes local edits and tests. A request to land,
  ship, publish, or deploy authorizes the matching commit/push/deploy sequence.
- Destructive commands and irreversible production or data actions must remain
  inside the user's stated scope. Clarify only genuinely ambiguous boundaries.
- Report final changed-file scope and verification evidence concisely.

## Roles And Skills

- Roles describe jobs and output contracts, never model identities.
- The task prompt may assign any available model to any role. Do not pin models
  in policy, skills, hooks, launchers, or agent configuration.
- Record the actual model in generated artifacts as provenance, not acceptance.
- Shared workflows live globally in one canonical `SKILL.md`. Product-specific
  workflows live in their repository under `.agents/skills/<name>/SKILL.md`.
- Put deterministic scripts and detailed references beside their owning skill.
  Host-specific files may point to canonical sources but must not duplicate
  workflow policy.
- Skill hooks live with the skill. Global hook configuration only dispatches
  to active global and repository skill manifests.

## Repository Adapters

- A repository guide begins with: `READ ~/.agents/AGENTS.md BEFORE ANYTHING
  (skip if missing).`
- Keep repository guides factual and short: architecture, invariants, commands,
  delivery conventions, and pointers to repo-owned skills.
- Use one root `AGENTS.md`. Add nested guides only for genuinely distinct
  subtrees. Compatibility files such as `CLAUDE.md` should point to it.

## Context

- Do not create persistent personas, journals, auto-memory, or session diaries.
- Do not load historical context unless the task explicitly names it.
- Prefer current repository state, tests, and source-of-truth files over notes.
