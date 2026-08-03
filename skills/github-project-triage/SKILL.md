---
name: github-project-triage
description: "Triage GitHub issues and pull requests by fit, risk, proof, blockers, and next action."
---

# GitHub Project Triage

Use for a request to triage a GitHub repository or queue. From a repository,
default to its current GitHub remote. Broaden to multiple repositories or
owners only when the request does.

## Sources

Use the connected GitHub provider when available; otherwise use an authenticated
GitHub CLI or API. Inspect live issue, pull request, comment, review, check, and
merge state. Read local source and tests before judging a claimed fix. Treat
current owner comments and repository product documentation as stronger routing
evidence than labels or stale summaries.

Do not pull, switch branches, stash, or mutate a dirty checkout merely to
triage it. Report the state and continue read-only where possible.

## Evaluate

For every surfaced item, provide its canonical URL first and classify:

- `Fit`: alignment with current product behavior and documented direction.
- `Risk`: blast radius, security/privacy exposure, migration, or compatibility.
- `Proof`: reproduction, source path, tests, live behavior, and current CI.
- `Trust`: factual contributor and repository activity when it changes review
  depth; trust is never correctness proof.
- `Blocker`: exact missing evidence, access, decision, or failed check.
- `Next`: one concrete maintainer action.

Read the whole owner path for plausible candidates, not only the touched file.
For bugs, identify the root cause or state what evidence is missing. For
features, require an end-to-end validation path. For dependency and security
changes, inspect upstream primary sources and current affected behavior.

## Output

Use three URL-first groups:

- `Autonomous candidates`: bounded work with a credible verification path.
- `Needs owner`: a prepared decision brief with options, tradeoff,
  recommendation, and exact unblock.
- `Defer, close, or supersede`: duplicate, stale, poor-fit, or lower-quality
  work with supporting evidence.

Say what portion of a large queue was not expanded. A triage request selects
and explains work; it does not authorize comments, closes, merges, or other
GitHub writes unless the user also asks to act.

When autonomous execution is authorized, process one item at a time through
implementation, focused proof, independent review, exact-head CI/delivery, and
a clean checkout before choosing the next item. Use `portfolio` for a sustained
or multi-repository queue.
