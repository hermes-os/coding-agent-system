# Issues

Real problems with the agent machine that are found and not yet fixed, wherever their code lives. The commit that fixes one removes its entry.

## The workbench image has no committer
- Where: `workbench/Containerfile`; the working agreement tells every agent to commit with `committer`.
- What happens: a worker's container sees none of `bin/`, so workers always fall back to plain `git commit`, and a gate line that names a command from `bin/` cannot run there.
- Found: removing the old machine from this repository, 2026-11-11.

## The books skill's hooks in ashwren-legacy no longer run
- Where: `ashwren-legacy/.agents/skills/books/hooks.json` (two Stop checks and a PreToolUse review).
- What happens: only the removed hook dispatcher read that file, and only in Claude Code, Cursor and Kimi sessions; agents in the Hermes harness never ran these hooks. To keep them for Claude Code sessions, the repository needs them in its own `.claude/settings.json`.
- Found: removing the hook dispatcher, 2026-11-11.

## No working CI runner
- Where: Forgejo Actions for every hermes repo; GitHub Actions on the mirror.
- What happens: the only Forgejo runner (`school-mini-macos`, scoped to hearth) is offline, and GitHub Actions only sees the mirror. No repo gets CI on a push to the Git server.
- Found: portfolio delivery check, 2026-10-12.

## Nothing alerts when GitHub falls behind the Git server
- Where: Forgejo on `vps` (`/etc/forgejo/app.ini`, mirror cron).
- What happens: from 2026-10-01 the mirror cron logged `PushMirrorsIterate: context canceled` every 10 minutes and pushed nothing; GitHub stayed at 2026-09-28 for every repo while each mirror showed no `last_error`. A Forgejo restart cleared it, and it can happen again unseen.
- Found: imessage-sidecar remote setup, 2026-10-12.

## A worker cannot build a crate that depends on a sibling folder
- Where: `imessage-sidecar` depends on `../../rustpush-upstream`, which is not part of its repository.
- What happens: a worker sees only the clones under `~/workbench`, and its worktree sits two folders below the clone, so the relative path leads nowhere. Workers on the old machine cloned RustPush themselves and tested against a different revision than the host. Not yet tried in the workbench.
- Found: imessage-sidecar workers 3e244c95 and cf94a341, 2026-10-13.

## Workers cannot reach the GPU
- Where: the workbench container; `profiles/worker/profile.json` passes no device into it.
- What happens: headless Chromium falls back to software rendering, so every frame-time number a worker records is CPU only, and GPU numbers must be taken on the host. Seen on the old machine; the workbench has the same limit.
- Found: Red Acre engine test run 758c362c, 2026-10-24.

## Staged-diff fingerprint depends on the user's git diff config
- Where: rpo-wellness `.agents/skills/rpo-quality-gates/scripts/lib/review-common.sh` (`staged_candidate_fingerprint` and other fingerprint call sites).
- What happens: the fingerprint hashes `git diff --cached` output, which changes with global `diff.mnemonicPrefix` and `diff.algorithm`, so the same staged change can fingerprint differently in a worker's container and for the host user.
- Found: rpo-wellness fix worker fe6843cb, 2026-10-12.

## A broken stream chunk ends a Hermes run as a non-retryable error
- Where: the Hermes harness on an Anthropic model (`agent/chat_completion_helpers.py` `_call_anthropic`; the run ends at `agent/turn_recovery.py:1106`). Seen on Hermes 9caa2133 and e3d78e60.
- What happens: a streamed tool-call input that is not valid JSON raises `ValueError: expected value at line 1 column 11`. The loop retries once, calls it a "Non-retryable client error", and the run ends with no report. It often follows a 429 retry.
- Found: marquee review runs ffb6fab1, 08ddb7b8 and a47ff056, 2026-10-22; Red Acre runs 781e7eb0 and 93e00846, 2026-10-25.

## File-mutation verifier warns about a file that a later edit changed
- Where: Hermes harness file-mutation verifier, at the end of an agent's report.
- What happens: one failed `patch` call on a wrong path makes the report end with "issues.md was NOT modified this turn", even though a later edit changed and committed that file.
- Found: ashwren worker 77c8c020 (commit 77916f5 changed issues.md), 2026-10-13.

## A delegate_task child with an output_schema can lose its whole report
- Where: `delegate_task` in the Hermes harness, background children with `output_schema`.
- What happens: two host-setup children on 2026-10-27 ended `failed`. One stopped with "session storage was busy (another Hermes process was writing to the state database)". The other had its report rejected as not JSON; the retry turn no longer held the report, so it returned "nothing verified". In both cases the work on the host was done or half done, but no record of it came back.
- Found: deleg_db83d360 and deleg_4b317e4b (MacBook Pro worker-host setup).

## A slow disk makes the harness remove a worker's container
- Where: Hermes harness `tools/environments/docker.py:497` (`<podman> version` gets 5 seconds); the iMac, which has 4 cores and one spinning disk (`sda`, ST31000528AS).
- What happens: when the disk is saturated, `podman version` answers late. The harness reports "Docker daemon is not responding", fails the tool call, and then removes and recreates the container. The worker loses all that lived only inside it (a seeded Postgres, a gate in the background) and does the work again. On 2026-11-12 the disk was 97 to 99% busy at under 1 MB/s (`/proc/pressure/io` `some avg60` 61); two workers lost containers at 12:06, 12:09, 12:20, 12:27, 12:29 and 13:00, and a guide prep run on the `author` profile ended with nothing written. The largest reader seen was the desktop file indexer (`localsearch-3`, set to index all of `$HOME`). Suggested: a longer wait and a retry before the harness calls the daemon dead; keep the indexer out of `~/workbench` and `~/Projects`; an SSD ends the class.
- Found: ashwren cards t_f58034f1 and t_13f29629, 2026-11-12.

## A rebuilt container starts in a folder that no longer exists
- Where: Hermes harness `tools/terminal_tool.py` (`_session_cwd`) and `tools/environments/docker.py:1140` (`_run_command(new_name, self.cwd)` passes it to `podman run -w`).
- What happens: the session remembers its last working directory. When the container is lost (out of memory, or the entry above) the new one is started with `-w <that directory>`. A directory that the agent made inside the old container is not in the new one, so `podman run` exits 126 on every try; an explicit `workdir` on the tool call does not override it. No terminal or file tool works again in that run, and the card blocks. Unblocking starts a new run, which works. Suggested: fall back to the profile's default working directory when the saved one is missing.
- Found: ashwren card t_13f29629 (saved directory `/var/lib/postgres/dl`, after an exit 137 with its test database on the `/workspace` tmpfs), 2026-11-12.

## The workbench image has a different Chromium on each host, and no Deno or Poppler
- Where: `workbench/Containerfile` (`pacman -Syu ... chromium`: the image gets the version of the day it is built).
- What happens: the iMac's image (built 2026-11-11) has Chromium 156.0.8078.79 and sim's (built 2026-11-12) has 157.0.8103.38. Ashwren's gates refuse any browser but the pinned one (`.agents/gates/gate_pins.py`: Chromium 156.0.8078.79, Deno 2.9.8), so the same card runs its browser checks in one host's image and skips them in the other's. The hosts have drifted too (iMac and sim 155, the Air 157 since 2026-11-12), so on 2026-11-12 no host could run Ashwren's full gate with the pinned browser; the iMac's image was the only place. A rebuild of that image moves it to 157 and breaks the pins for every Ashwren card. The image also has no `deno` and no `poppler`: each Ashwren worker installs them with `pacman -Sy` in every container, and again after each rebuilt container. Suggested: install Chromium from the Arch Linux Archive at one fixed version, add `deno` and `poppler`, run every gate in the image and not on a host, and move Ashwren's pins in the same change.
- Found: release of ashwren 0f7d94a, 2026-11-12 (`pacman -Q chromium` on each host; `chromium --version` in each image; the worker's `gate1.sh`).

## A child card starts before its parent's branch is merged
- Where: the kanban dispatcher (`hermes kanban create --parent`), with worktree cards.
- What happens: a child card leaves `todo` within a minute of its parent reaching `done`. Its worktree is cut from the clone's `main`, and the parent's work is not on `main` until Foreman has read it, merged it and pushed. So a card made to run after another on the same files starts without that work, and its branch must take a merge later. On 2026-11-12 ashwren card t_81abe2eb started from `e152a14` one minute after t_f58034f1 was approved. Work-around in the `worker-dispatch` skill: park the second card with `hermes kanban schedule` and `unblock` it after the merge. Suggested: a way to cut the child's worktree from the parent's branch, or a card state that waits for the assigner's merge.
- Found: ashwren cards t_f58034f1 and t_81abe2eb, 2026-11-12.
