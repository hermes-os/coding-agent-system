---
name: review
description: "Review a committed change range and give one verdict: approve, or the defects that remain."
---

# Review

Judge the result, not the route. A review reads the commits and the code they
touch, never a summary of them. The reviewer changes nothing.

## What to judge

1. Does it do what was asked? Read the request, then `git log -p <base>..<head>`.
2. Is it the simplest design that works? Would you be glad to keep building on
   this code?
3. Is it proven? Run the tests that matter and the repository's gate. Check
   that a bug fix has a test that would have failed before it.
4. Is it safe? Look for regressions, broken contracts, data loss, and secrets
   in code, logs, tests or commits.
5. Are the records true? A user-visible change has its `CHANGELOG.md` line in
   the same commit; a problem left open is in `issues.md`; a fix removed its
   entry.

Check each finding against the source before you raise it. Leave out taste,
speculative edge cases, and rewrites that fix no concrete risk in this range.
Pair the review with `behavior-validator` when the behavior a user sees needs
its own proof.

## Verdict

Give one, first:

- **Approve** when the work meets the request. Say what you checked.
- **Changes** when a real defect remains. Name each one, where it is, why it
  matters, and the smallest fix, most serious first, so the author can fix it
  without asking.
- **Hermes decides** when the open question is his: the question, at most two
  options, and your pick.

Then the checks you ran and any risk that remains. Stop at approve; a second
review for a nicer verdict adds nothing.
