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
