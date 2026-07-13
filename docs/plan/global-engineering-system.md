---
summary: Extract and harden the portable global engineering system as an independently versioned repository.
read_when:
  - Changing global policy, skills, hooks, commands, installation, validation, or VM integration.
---

# Global Engineering System

## Status

Active. The portable source has been history-preservingly extracted from the VM
repository. Hardening and independent publication are in progress.

## Problem

The portable engineering system and VM bootstrap currently share one repository,
which couples global policy to VM-specific authentication and remote-control
behavior. Validation also contains hand-maintained catalogs that can drift.

## Goals

- Version the portable policy, skills, hooks, commands, installer, and tests in
  one independent public repository.
- Make installed state, repository wiring, and skill catalogs deterministically
  auditable without loading historical context.
- Keep VM-only bootstrap, credentials, and remote-control behavior in the VM
  repository while pinning the portable system to an exact revision.
- Prevent stale managed files, ambiguous hook manifests, model pins, secret
  filenames, generated artifacts, and duplicate instruction systems.

## Non-Goals

- Encoding product-specific architecture or test commands globally.
- Pinning models or assigning roles through host configuration.
- Creating a global project diary, issue mirror, or append-only work ledger.
- Replacing project-specific CI, tests, or repository-owned skills.

## Decisions

- Use `hermes-os/coding-agent-system` as the canonical portable repository.
- Keep `hermes-os/coding-agent-vm-setup` independent and consume the portable
  repository at an exact Git revision.
- Treat CI and deterministic doctor/check commands as enforcement; hooks remain
  skill-owned and host adapters only dispatch them.
- Preserve unrelated user configuration and extensions while tracking and
  pruning only paths managed by this system.

## Milestones

- [x] Extract portable history into an independent local repository.
- [x] Centralize and validate the managed catalog and installed-state manifest.
- [x] Add repository hygiene checks and strict hook validation.
- [ ] Split portable and VM integration tests and documentation.
- [ ] Validate fresh local and VM installs on the pinned revision.
- [ ] Publish both repositories and verify CI from exact heads.

## Verification

- Strict skill and model-neutrality audit.
- Full portable unit and integration test suite on macOS and Linux CI.
- Fresh-home install followed by `agent-system-doctor`.
- Repository checks against this repository, VM setup, and Ashwren.
- VM bootstrap test with the pinned portable revision initialized.
- macOS local proof: all 51 unit and integration tests pass in bounded groups;
  strict skill audit, repository check, syntax checks, and `git diff --check`
  pass. The desktop command runner truncates the aggregate suite at roughly 30
  seconds, so the unchanged aggregate command remains CI proof.

## Open Questions

- None currently. Record only decisions that cannot be recovered from code or
  tests, then delete this plan when it no longer carries unique value.
