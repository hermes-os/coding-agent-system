# Issues

The coordinator's tooling log: known problems with the agent tools and the worker harness, wherever their code lives. Issue only; fixes are proposed in reports. When the fix lands in the owning repository or host file, a commit here removes the entry.

## No working CI runner
- Where: Forgejo Actions for every hermes repo; GitHub Actions on the mirror.
- What happens: the only Forgejo runner (`school-mini-macos`, scoped to hearth) is offline, and GitHub Actions only sees the stale mirror. No repo gets CI on a push.
- Found: portfolio delivery check, 2026-10-12.

## Usage watch resumes runs the coordinator ended on purpose
- Where: `~/.hermes/profiles/cal/scripts/model-usage-watch-v20260930.py` (every 5 minutes); its ledger is `~/.hermes/profiles/cal/workspace/state/model-usage-watch/ledger.json`.
- What happens: it calls `repo-worker --resume-run` on any run it reads as limit-killed unless the runId is in the ledger's `not_limit` list. A run whose task a fresh worker already finished was restarted on a moved main.
- Found: ashwren run 6b3f57c9 resumed itself after its task was done, 2026-10-11.

## Launcher origin check accepts only one form of the Forgejo URL
- Where: origin check in the cal copy `~/.hermes/profiles/cal/workspace/scripts/repo-worker` (the libexec copy accepts all forms).
- What happens: `git.ashwren.com` is accepted only as `git@host:owner/repo`, not as an https or ssh:// URL, and the refusal message still says "GitHub URL".
- Found: skill audit against the launcher code, 2026-10-12.

## Write runs leave worker-owned paths in .git
- Where: canonical checkouts and lane clones after a write run (`.git/objects/xx`, refs).
- What happens: host git fails with "insufficient permission for adding an object" on fetch, merge or push until the ACLs are reset by hand.
- Found: ashwren merge 2026-10-11; `find .git ! -user hermes ! -writable` found 130 paths in hermes-mobile-lane-toolcore-r2 and 9 in hermes-mobile.

## Two copies of the runner differ
- Where: `~/.hermes/profiles/cal/workspace/scripts/repo-worker` and `/usr/local/libexec/agent-worker-runner`.
- What happens: at least the run-cap constant differs; it is not clear which copy is live for which setting.
- Found: skill audit, 2026-10-12.

## Runner still offers project mode
- Where: `repo-worker --mode project`.
- What happens: it adds a "single execution owner for this project queue" note to the packet, a long-lived-session model the workflow no longer uses.
- Found: skill audit, 2026-10-12.

## Repo check still validates plan files
- Where: `agent-repo-check`, `agent-repo-inventory`.
- What happens: they check the shape of `docs/plan/*.md` and list them as active work, while plans are no longer an allowed record.
- Found: skill audit, 2026-10-12.

## Stale policy copies outside the repo
- Where: `~/.agents/kimi/agent.yaml` (both homes), the installed Cursor commands and global rule, `tirith-install` helpers, Claude and Codex model pins, `.bashrc` invocation blocks, and the skill catalog hash.
- What happens: they drift from the repository; `agent-system-doctor` reports each one.
- Found: skill audit, 2026-10-12.

## Parity doc drops a script that still exists
- Where: `docs/steipete-agent-scripts-parity.md` line 21 (control-plane proof sentence).
- What happens: it no longer names `scripts/orchestrator-watch`, but the cal workspace still ships it: `ORCHESTRATION.md` refers to it, `validate-workspace` requires it, and its cron job is paused, not removed.
- Found: round 2 review of b7990cd.

## CHANGELOG misses two skill changes
- Where: `CHANGELOG.md` `### Changed`.
- What happens: it does not say that `review` now grades findings BLOCKER/FIX/NIT or that `fix-issue` puts found issues in their own commit.
- Found: round 2 review of b7990cd.

## Autoreview script still ships with the old severity scale
- Where: `skills/review/scripts/agent-autoreview.py` (lines 502, 725).
- What happens: it still requires P0-P3 severities, while the review skill grades BLOCKER/FIX/NIT and the CHANGELOG says review no longer uses autoreview bundles.
- Found: round 2 review of b7990cd.

## Host gate cannot install packages in a checkout a worker built in
- Where: shared checkouts after a write run, e.g. `rpo-wellness/wellness/node_modules` (owned by agent-worker).
- What happens: a repo's pre-commit gate run as hermes fails on `pnpm install` with EACCES (exit 243), so lint, typecheck, test and build cannot run in the shared folder.
- Found: rpo-wellness precommit gate for commit 6a133b2, 2026-10-12.

## Staged-diff fingerprint depends on the user's git diff config
- Where: rpo-wellness `.agents/skills/rpo-quality-gates/scripts/lib/review-common.sh` (`staged_candidate_fingerprint` and other fingerprint call sites).
- What happens: the fingerprint hashes `git diff --cached` output, which changes with global `diff.mnemonicPrefix` and `diff.algorithm`, so the same staged change can fingerprint differently for a worker and for the host user.
- Found: rpo-wellness fix worker fe6843cb, 2026-10-12.

## Workers cannot be talked to from herdr
- Where: `/usr/local/libexec/agent-worker-hermes/host/bin/agent-hermes-worker` (`build_command`) and `repo-worker` (`--foreground` is unavailable with the worker broker).
- What happens: each worker runs `hermes chat --oneshot` with no terminal attached. A herdr pane can only show the run through `watch-worker.py`, so herdr does not list the worker as an agent and Hermes cannot type to it.
- Found: Hermes asked for interactive workers in herdr, 2026-10-12.

## Forgejo push mirrors stalled silently for two weeks
- Where: Forgejo on `vps` (`/etc/forgejo/app.ini`, mirror cron).
- What happens: from 2026-10-01 the mirror cron logged `PushMirrorsIterate: context canceled` every 10 minutes and pushed nothing; GitHub stayed at 2026-09-28 for every repo while each mirror showed no `last_error`. A Forgejo restart cleared it. Nothing alerts when GitHub falls behind Forgejo.
- Found: imessage-sidecar remote setup, 2026-10-12.

## Worker system and Foreman tools are not in git
- Where: `~/.hermes/profiles/cal/workspace/scripts/` (repo-worker, agent-worker-broker, agent-hermes-worker and configs, wait-for-workers; 153 files, many one-off dated launch scripts and `.bak-*` copies), the installed copy at `/usr/local/libexec/agent-worker-hermes/`, and `~/.hermes/profiles/foreman/{SOUL.md,skills,scripts}`.
- What happens: the software every worker run depends on has no history, no review and no backup; changes to it cannot be traced or rolled back.
- Found: git coverage check, 2026-10-12.
