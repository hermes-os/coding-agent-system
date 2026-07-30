# Changelog

This file records user-visible changes to the portable coding-agent system.

## Unreleased

### Changed

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
