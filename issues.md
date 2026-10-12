# Issues

Known problems with the agent tools and the worker harness. Issue only; fixes are proposed in reports. The commit that fixes an issue removes its entry.

## No working CI runner
- Where: Forgejo Actions for every hermes repo; GitHub Actions on the mirror.
- What happens: the only Forgejo runner (`school-mini-macos`, scoped to hearth) is offline, and GitHub Actions only sees the stale mirror. No repo gets CI on a push.
- Found: portfolio delivery check, 2026-10-12.

## Usage watch resumes runs the coordinator ended on purpose
- Where: `~/.hermes/profiles/cal/workspace/state/model-usage-watch` (`model-usage-watch-v20260930.py`, every 5 minutes).
- What happens: it calls `repo-worker --resume-run` on any run it reads as limit-killed unless the runId is in the ledger's `not_limit` list. A run whose task a fresh worker already finished was restarted on a moved main.
- Found: ashwren run 6b3f57c9 resumed itself after its task was done, 2026-10-11.

## Launcher origin check accepts only one form of the Forgejo URL
- Where: `repo-worker` launcher origin check.
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
- Where: `~/.agents/kimi/agent.yaml` (both homes) and the installed Cursor commands and global rule.
- What happens: they carry the August policy; `agent-system-doctor` flags them.
- Found: skill audit, 2026-10-12.
