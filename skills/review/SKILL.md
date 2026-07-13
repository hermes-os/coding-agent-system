---
name: review
description: "Independent findings-first review of a code change, plan, or implementation."
---

# Review

Act as the independently assigned reviewer. Review the real diff and relevant
surrounding code; do not infer quality from a summary alone.

## Contract

1. Freeze the requested scope, intended behavior, ownership boundary, changed
   files, and available proof.
2. Inspect for correctness defects, regressions, security or privacy risk,
   unsafe data behavior, broken contracts, unnecessary complexity, and missing
   tests.
3. Verify each candidate finding against source, tests, types, and current
   primary documentation when external behavior matters.
4. Reject speculative edge cases and broad rewrites that do not fix a concrete
   problem introduced by the change.
5. Classify accepted findings as in-scope blocker, follow-up, or scope-breaking
   design decision.
6. If fixes are made, rerun focused proof and review the resulting diff once
   more. Stop when no accepted actionable finding remains.

## Output

- Findings first, ordered by severity, with file and line references.
- State impact, evidence, and the smallest appropriate correction.
- Then list open questions or assumptions.
- End with a short verification and residual-risk summary.
- Say clearly when no findings remain.
