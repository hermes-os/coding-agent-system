---
name: review
description: "Freeze, independently review, and validate a code change, plan, or implementation."
---

# Review

Use an independently assigned reviewer. Judge the frozen candidate and relevant
source, never a success summary. For non-trivial code, use the deterministic
bundle and result validator:

```bash
agent-autoreview prepare --base <target-ref> --intent "<requested outcome>"
agent-autoreview validate --bundle <bundle-dir> --result <result.json> --record
```

`prepare` requires a committed candidate, fails closed on sensitive paths or
secret-like patch text, snapshots changed source files, and prints the bundle
path. Give only that bundle plus the role assignment to a fresh reviewer. The
reviewer writes `result.json` from the generated template. Record provenance
for the reviewer actually used; never make an identity an acceptance rule.

## Contract

1. Freeze the request, target branch, intended behavior, owner boundary,
   changed files, candidate SHA, and available proof.
2. Inspect correctness, regressions, security and privacy, data behavior,
   broken contracts, unnecessary complexity, and missing tests.
3. Verify candidate findings against source, tests, types, and current primary
   documentation when external behavior matters.
4. Reject speculative edge cases and rewrites that do not fix a concrete risk
   introduced by the candidate.
5. Classify findings as `blocker`, `follow-up`, or `scope-break` and use
   severities `P0` through `P3`.
6. Verify accepted findings in the real checkout before editing. If code
   changes, rerun focused proof and review a newly frozen bundle.
7. Stop when the validator records a pass for the exact fingerprint. Do not run
   redundant reviews for a nicer verdict.

If a finding would double the original surface, alter a public contract, cross
an owner boundary, or fails to converge after two repair cycles, stop expanding
and report the scope break. Pair this source-aware review with
`behavior-validator` when user-visible behavior needs independent proof.

For an authorized GitHub workflow, `agent-autoreview publish` records an
idempotent fingerprint-specific commit status after validation. Acquire the
public mutation lease from `portfolio` only for that publish, then release it
immediately. Read `references/cursor-automation.md` only when configuring
Cursor Automations.

## Output

- Findings first, ordered by severity, with file and line references.
- State impact, evidence, classification, and the smallest correction.
- Then open questions, verification, and residual risk.
- Say clearly when no actionable findings remain.
