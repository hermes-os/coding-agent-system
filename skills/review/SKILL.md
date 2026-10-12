---
name: review
description: "Independently review a committed change range and return VERDICT: APPROVE or CHANGES."
---

# Review

Review happens after the worker commits. A fresh, read-only reviewer judges the
commit range and the relevant source, never a success summary. The reviewer
does not edit, commit, push, or deploy.

## Input

The review order names:

- the base and head commits (`git log <base>..<head>`, `git diff <base> <head>`);
- what the change does, in two lines, and the owner boundary;
- the defect classes to hunt;
- gates that already fail on the base, as known and not to be raised;
- on a re-review, the findings from earlier rounds, to check first.

## Contract

1. Inspect correctness, regressions, security and privacy, data behavior,
   broken contracts, unnecessary complexity, and missing tests.
2. Check that each user-visible change has its `CHANGELOG.md` entry in the same
   commit, that unfixed issues the workers found are in `issues.md`, and that a
   fixing commit removed its issue entry.
3. Verify each finding against source, tests, types, and current primary
   documentation when external behavior matters.
4. Reject speculative edge cases and rewrites that do not fix a concrete risk
   introduced by the range.
5. Grade findings `P0` through `P3` and mark a finding that would double the
   surface, alter a public contract, or cross an owner boundary as a scope break.
6. Stop at `APPROVE`. Do not run redundant reviews for a nicer verdict.

On `CHANGES`, a fresh worker fixes the findings in new commits and a fresh
reviewer reads the whole range again. Repeated repair failures call for better
diagnosis or a different bounded approach, not parking based on a review count.
Do not waive material findings. Pair this review with `behavior-validator` when
user-visible behavior needs independent proof.

## Output

- First line: `VERDICT: APPROVE` or `VERDICT: CHANGES`.
- Findings ordered by severity, with file and line references, impact,
  evidence, and the smallest correction.
- Then open questions, checks run, and residual risk.
- Say clearly when no actionable findings remain.
