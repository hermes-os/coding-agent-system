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
- Keep VM-specific bootstrap, credentials, and remote-control behavior in the VM
  repository while pinning the portable system to an exact revision. Keep the
  separately requested local launch behavior in an explicit local adapter.
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
- Keep launchers out of the shared catalog. The installer wires an explicit
  host integration: `host/local` for this machine, or the VM-owned adapter for
  cloud hosts.
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
- Hardened candidate proof: `./validate.sh` passed all 60 tests in 154.867
  seconds, including managed-path collision safety, unrelated hook preservation,
  exact-origin publication checks, TOML and shell-profile preservation, shared
  skill layout, aggregate hook budgets, and repository symlink containment.
- A second frozen independent review at fingerprint
  `7fc31ed41f98dc69c52e4bc3e914891950d7779c0c2e6dc6553caeb49ef09d9e`
  found ten additional boundary defects. Focused regressions now cover dotted
  and inline TOML, symlinked host files, unowned plugins, repository hook
  escapes, end-to-end hook timing, rewritten origins, dangling roots, deleted
  tracked secret paths, and host-specific launcher ownership. A fresh
  exact-candidate review is still required before publication.
- Repaired candidate proof: `./validate.sh` passes all 67 tests in 173.047
  seconds, plus the strict skill audit, repository check, syntax checks, and
  `git diff --check`.
- A third frozen independent review at fingerprint
  `e30b4f98c611df14c314c1c602544e0ddf0dd81fde23230688d497ea42c1593c`
  found three remaining host-boundary defects: timed-out hook descendants,
  unbounded hook output, and incomplete host-adapter doctor checks. Focused
  regressions now prove process-group cleanup, a combined 256 KiB output cap,
  and rejection of a missing host shell adapter. The validated review artifact
  is
  `/var/folders/kq/yv_n5c115r566nxsz5r1sh200000gp/T/agent-autoreview-e30b4f98c611-jhwl8n_c/result.json`.
- Final repaired candidate proof: `./validate.sh` passes all 69 tests in
  227.161 seconds, followed by the strict skill audit, repository check, syntax
  checks, and `git diff --check`.
- A fourth frozen review at fingerprint
  `41d0736317051fd8fe3c9cdf001fabd9717c9feea512da8f2999eb3a3586f55d`
  found one final host-adapter preflight gap. The installer now rejects an
  unreadable shell adapter before modifying host configuration; its focused
  install and doctor regression passes in 6.349 seconds. The validated review
  artifact is
  `/var/folders/kq/yv_n5c115r566nxsz5r1sh200000gp/T/agent-autoreview-41d073631705-56_gl7ws/result.json`.
- Post-review candidate proof: `./validate.sh` passes all 69 tests in 221.959
  seconds, followed by the strict skill audit, repository check, syntax checks,
  and `git diff --check`.
- The first published CI run, `29285718921`, exposed a timing assumption in the
  lease-renewal regression on both Linux and macOS: renewing with the original
  TTL inside the same second can correctly retain the same metadata commit.
  The test now uses a distinct renewal TTL, and the focused cross-host lease
  scenario passes three consecutive fresh runs.
- CI-repair candidate proof: `./validate.sh` passes all 69 tests in 239.761
  seconds, followed by the strict skill audit, repository check, syntax checks,
  and `git diff --check`.

## Open Questions

- None currently. Record only decisions that cannot be recovered from code or
  tests, then delete this plan when it no longer carries unique value.
