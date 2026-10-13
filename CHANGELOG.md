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

### Added

- `worker-host/` holds the live worker-host system as installed on
  2026-10-12: the runner, broker, Hermes adapter and its read/write configs,
  the Codex auth sync, the coordination probe and its sudoers rule, the model
  policy (`/etc/agent-worker/defaults.json`), the systemd units, the client
  tools (wait, watchdog, usage watch, pane, viewer, chain) and their tests.
- The repository runner (`worker-host/libexec/agent-worker-runner`) now
  carries the client launcher's two-run cap (`REPO_WORKER_MAX_ACTIVE`,
  default 2), so one file serves both the installed runner and
  `repo-worker`. The runner and broker no longer accept `git.ashwren.com`
  origins: the name no longer resolves and no checkout uses it; the forge is
  `git.imhermes.dev`.
- The runner finds its Cal workspace (model policy, Cal-profile guard) from
  the path it was started by, not the symlink-resolved file, so
  `~/.hermes/profiles/cal/workspace/scripts/repo-worker` can become a symlink
  into `worker-host/`. `worker-pane.sh` and `chain-workers.sh` find their
  sibling tools next to their resolved location in `worker-host/bin/`.
- `validate.sh` runs the worker-host tests (`worker-host/tests/run-tests`)
  against the repository copies. Tests that need root run through `sudo -n`
  when available and are skipped otherwise. The default-model and fallback
  tests now follow the policy's `workerDefault` and order instead of pinning
  Opus 5.5, and the explicit-routing test expects an explicit `--model` to
  return at once (no model swap), matching the code since 2026-10-07.
  `test-agent-runtime-policy` moved too but is not run (it probes the retired
  OpenClaw runtime).
- `worker-host/install.sh` compares the repository with the live host
  (`--check`, read-only, the default) and installs from it (`--apply`):
  backups under `/var/backups/agent-worker/<timestamp>/`, the target's current
  owner and mode, client paths replaced by symlinks into `worker-host/`,
  `daemon-reload` only when a unit changed, and a refusal while a run is
  active or the reboot hold is set.
- `worker-host/install.sh` with `WORKER_HOST_PREFIX` set (a scratch test
  tree) never calls sudo or systemctl: files keep the caller as owner and
  each systemctl command is printed as `would run: ...` instead.
- `worker-host/install.sh --apply` no longer resets the mode of an existing
  parent directory to 0755 when it installs a new file; it only creates a
  missing parent (root, 0755).
- `worker-host/install.sh --apply` installs committed content only: it
  refuses, before writing anything, while `git status --porcelain` lists any
  change or untracked file under `worker-host/`.
- `worker-host/install.sh --apply` records the daemon-reload and broker
  restart it owes in `/var/backups/agent-worker/pending` before installing.
  When a run starts during the apply it leaves the broker unrestarted, prints
  the `sudo systemctl try-restart agent-worker-broker.service` command and
  exits 3; an apply stopped before `daemon-reload` prints that command.
  `--check` reports recorded steps as `PENDING`, and the next `--apply` runs
  them instead of reporting nothing to apply.
- `worker-host/install.sh` resolves its repository with `pwd -P`, so
  starting it through a symlinked path no longer reports every client link as
  drift.
- `worker-host/install.sh --apply` refuses when an installed target cannot be
  read, instead of skipping it; `--check` now reports such a target as
  `DRIFT unreadable` instead of stopping silently at it.
- `worker-host/tests/run-tests` runs the two root-only tests only when
  `WORKER_HOST_ROOT_TESTS=1` is set (as root or through `sudo -n`).
  `validate.sh` does not set it, so it no longer runs anything through sudo.
- `worker-host/install.sh --apply` replaces the Cal workspace copies of
  `agent-hermes-worker` and `agent-worker-coordination-probe`, which are older
  than the installed ones, with symlinks to the `worker-host/` copies, which
  match the installed versions.
- The runner refuses an origin outside the accepted forges with "repository
  origin must be a forge URL" instead of naming only GitHub; Forgejo
  (`git.imhermes.dev`) origins were already accepted.

### Changed

- The working agreement now tells every agent to add a CHANGELOG.md entry
  for each user-visible change in the same commit, to log unfixed bugs and
  gaps in a repo-root issues.md (issue only, fix ideas go in the report), to
  end each task with `git status` clean, and to report issues with a
  suggested fix. The commit log, CHANGELOG.md and issues.md are the only
  allowed records.
- Workers do not add a release heading (the coordinator does when landing),
  and tooling issues go to coding-agent-system's `issues.md`.
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
