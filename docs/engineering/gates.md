---
summary: Deterministic gates every repository wires up - type checking, config schemas, lint rules, residue greps, diff and dependency guards, mutation testing.
read_when:
  - Wiring or changing CI checks, lint rules, or type-checker settings.
  - Adding residue, diff-scope, or dependency guards.
---

# Deterministic Gates

Machine-checkable rules. Prose does not enforce what a gate can. Each repository
wires these up; the requirement is global.

- Use the strictest practical type checker settings, and treat compiler warnings
  as errors where practical. Prefer exhaustive matching over wildcard branches
  that hide newly added cases.
- Parse configuration through a strict schema at startup: unknown keys fail,
  missing required keys fail, invalid values fail. A hallucinated configuration
  key must fail in CI or at startup, never silently no-op.
- Enable lint rules for unnecessary conditions, useless catches, swallowed
  errors, deprecated APIs, dead exports, unchecked results, restricted imports,
  and assertion-free tests. Analyzer suppressions are reviewed exceptions and
  carry a reason.
- Block on residue greps: emoji in source, hedge phrasings, banner comments and
  step narration, demo entry points outside approved locations, placeholder
  strings, and AI provenance strings. Run secret scanning separately; grep is
  not a credential check.
- Narration-comment greps are advisory. They produce review annotations rather
  than failing a build unless the repository's false-positive rate is very low.
- Check formatting repository-wide, but format only touched files in a task.
- Flag whitespace-only hunks, generated-file changes without a source change,
  unrelated directory changes, and dependency changes mixed into feature work.
- Dependency and lockfile changes require an explicit label, a stated reason,
  human review, and vulnerability checks.
- Verify that a clean checkout builds, lockfiles are honored, generated code is
  current, migrations are valid, and release artifacts carry no debug files.
- Apply mutation testing to high-risk changed modules: domain invariants,
  authorization, validation, billing, state transitions, security boundaries,
  concurrency rules, parsers and serializers. Do not spend that budget on
  generated bindings or view markup.
