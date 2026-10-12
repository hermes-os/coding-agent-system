# Changelog

This file records user-visible changes to the portable coding-agent system.

## Unreleased

- Add constrained GitHub peer handoffs with local host identity, bounded queue
  discovery without stale-label starvation, recipient-wide signals,
  immutable transition binding, canonical host authorization, post-lease PR
  revalidation, exact-head lifecycle events, and Darwin-only macOS validation
  statuses.
- Harden canonical GitHub peer authorization reads with a 256 KiB limit,
  no-follow descriptor pinning, and fail-closed inode and metadata checks.
- Report Xcode, `xcrun`, and simulator capabilities when available.

### Changed

- The working agreement now tells every agent to add a CHANGELOG.md entry
  for each user-visible change in the same commit, to log unfixed bugs and
  gaps in a repo-root issues.md (issue only, fix ideas go in the report), to
  end each task with `git status` clean, and to report issues with a
  suggested fix. The commit log, CHANGELOG.md and issues.md are the only
  allowed records.
- `land` commits the release heading before the push so it is part of the
  reviewed range; `worker-first` names coding-agent-system's `issues.md` as
  the coordinator's tooling log; README and the parity doc say workers run on
  the Hermes harness.
- Align the coordinator skills with the commit-first workflow: each task is a
  fresh worker run on the Hermes harness (no persistent project sessions, no
  resume of a crashed worker), workers commit their own changes with
  `CHANGELOG.md` entries and record unfixed issues in `issues.md`, a fresh
  read-only reviewer returns `VERDICT: APPROVE|CHANGES` on the commit range,
  and only the coordinator pushes and deploys after approval. `review` no
  longer uses `agent-autoreview` bundles, `land` and `portfolio` no longer use
  leases for Hermes's repositories, and the Cursor Automation references and
  the completed parity plan are gone.
- Replace the long global `AGENTS.md` with a short working agreement: the code is
  the context, workers commit after every change, agents write no specs, plans,
  or notes, and the 55 percent context handoff rule is gone.
- Skip unmanaged symlinks in the global skill root instead of blocking every
  hook event; their hooks never register.
- Recognize public SQLite FTS5 tokenizer options during review secret scanning,
  without exempting credential assignments or token patterns elsewhere.

- Allow hooks to ignore empty, read-only mounted `.git` placeholders while
  keeping ordinary malformed repository markers fail-closed.
- Require fresh verification, prompt repair of verified review findings, and
  removal of obsolete planning documents before delivery.
- Require every governed repository to maintain an up-to-date changelog.
- Require a handoff once an agent's context exceeds 55 percent.

## 2026-07-29

### Added

- Support for adopting and validating governed assistant workspaces.

## 2026-07-13

### Added

- Initial independently versioned portable engineering system.
- Deterministic installation, repository validation, review, continuity, and
  cross-host coordination tools.

### Completed

- Split portable policy and tests from VM-specific integration and
  documentation.
- Validated fresh local and VM installations against an exact shared-system
  revision.
- Published both repositories and verified their exact-head GitHub Actions
  validation, completing the standalone-extraction plan. Durable ownership and
  integration boundaries now live in `README.md`.
