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
- It also reads a provider 429 stream fault as limit-killed and resumes the run as a new run with no herdr pane, while the coordinator relaunches fresh (chain-workers or by hand). The duplicate takes a broker slot, so the next launch fails with "2 runs already active". Found: marquee reviewers 85a7fa69 and 22073d1c resumed as 05c6d415 and e53fea56 after their task was already approved and pushed, 2026-10-13.

## Write runs leave worker-owned paths in .git
- Where: canonical checkouts and lane clones after a write run (`.git/objects/xx`, refs).
- What happens: host git fails with "insufficient permission for adding an object" on fetch, merge or push until the ACLs are reset by hand.
- Found: ashwren merge 2026-10-11; `find .git ! -user hermes ! -writable` found 130 paths in hermes-mobile-lane-toolcore-r2 and 9 in hermes-mobile.

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

## Runtime-policy test probes the retired OpenClaw runtime
- Where: `worker-host/tests/test-agent-runtime-policy` (moved from the cal workspace).
- What happens: it reads `~/.hermes/profiles/cal/openclaw.json`, root's Claude and Codex sign-ins and the Codex Remote Control supervisor; the OpenClaw config is gone, so it fails with FileNotFoundError. `worker-host/tests/run-tests` does not run it.
- Found: running the ten live worker tests, 2026-10-12.

## install.sh can lose the pending record on a hard kill
- Where: `worker-host/install.sh` line 293 (pending marker write).
- What happens: `tee` empties `/var/backups/agent-worker/pending` before it writes it, so a hard kill at that instant leaves no record of an owed daemon-reload or broker restart.
- Found: round 2 review of ff5da1e.

## install.sh git status can take the shared index lock
- Where: `worker-host/install.sh` line 260 (committed-content check).
- What happens: plain `git status` may briefly take `index.lock` in the shared checkout, so a commit by another agent at that moment can fail.
- Found: round 2 review of ff5da1e.

## install.sh does not re-check a file between the commit check and its install
- Where: `worker-host/install.sh`, `--apply` path after the `git status` check.
- What happens: an edit made to `worker-host/` during an apply could still be installed as root.
- Found: round 2 review of ff5da1e.

## agent-trash fails inside the worker sandbox
- Where: worker sandbox (`repo-worker --access write`), `~/.local/share/Trash` of the worker user.
- What happens: the trash directory sits on a read-only mount, so `agent-trash` fails; a worker had to set `XDG_DATA_HOME=/var/lib/agent-worker/.cache/xdg-data` to remove files.
- Found: tape-machine worker f579fb5c, 2026-10-12; also tape-machine worker cf27cd80, 2026-10-14 (workers leave scratch copies in /tmp); red-acre run 50bd92ce, 2026-10-20 (fell back to `mv` into scratch); imhermes-dev run 3b3d4106, 2026-10-21.

## File-mutation verifier warns about a file that a later edit changed
- Where: Hermes harness file-mutation verifier, at the end of a worker's report.
- What happens: one failed `patch` call on a wrong path makes the report end with "issues.md was NOT modified this turn", even though a later edit changed and committed that file.
- Found: ashwren worker 77c8c020 (commit 77916f5 changed issues.md), 2026-10-13.

## Run status says blocked when the report does not start with OUTCOME
- Where: worker run status in `repo-worker --output` / `wait-for-workers.sh`.
- What happens: a reviewer that put `VERDICT: APPROVE` before `OUTCOME: COMPLETED` finished with status `blocked`; a worker whose only problem was a refused chmod also reported `blocked`. The status does not tell a finished run from a stuck one.
- Also: the run's final text is the last assistant message. When background-process completion notices arrive after the report, the worker answers them, and that short answer replaces the `OUTCOME: COMPLETED` report in `final.txt` and the stream's `final` event; the status becomes `blocked` and the real report is only in the run's `state.db`.
- Also: a model name with a dot (`claude-opus-5.5`) makes the runtime print `⚠️  Normalized model 'claude-opus-5.5' to 'claude-opus-5-5' for anthropic.` as the first line of `final.txt`, above `OUTCOME: COMPLETED`, so an approving review ends as `blocked`.
- Found: kestrel runs c36f5db8 and 13223cfb, 2026-10-13; marquee runs 026f8a9b and 8f2a31e4, 2026-10-16.

## repo-worker launch sometimes prints no runId
- Where: `repo-worker --agent hermes ... --task-file`.
- What happens: one launch for ashwren-legacy returned no runId and started no run; the same command a minute later worked.
- Found: Foreman launch of the ashwren-legacy align task, 2026-10-13.

## agent-repo-check validates docs/plan against plan sections
- Where: `agent-repo-check` (`PLAN_SECTIONS` check on `docs/plan/*.md`).
- What happens: the check still requires plan-file sections, while the working agreement retires plan files; it keeps nudging agents toward writing plans.
- Found: marvin-legal-management worker ade14070, 2026-10-13.

## agent-repo-check skill audit fails with No module named 'lib'
- Where: `agent-repo-check` skill audit, run by a worker in ashwren-legacy.
- What happens: the skill audit step stops with `No module named 'lib'`, so the repo check fails for a reason unrelated to the repo.
- Found: ashwren-legacy worker defbf092, 2026-10-13.

## Workers cannot build crates with sibling path dependencies
- Where: worker sandbox; `imessage-sidecar` depends on `../../rustpush-upstream`, which lives under `/home/hermes/Projects` and is not in the worker workspace.
- What happens: workers clone RustPush master into /tmp and patch it to build, so their gate runs against a different RustPush revision (70ec162) than the host checkout (a7fab47).
- Found: imessage-sidecar workers 3e244c95 and cf94a341, 2026-10-13; Foreman re-ran the gate against the host checkout.

## Worker sandbox cannot run the rpo-wellness gate with its defaults
- Where: the worker environment (repo-worker Hermes adapter) running `precommit-gate.sh` in rpo-wellness.
- What happens: the default pnpm store path is read-only and Playwright's Chromium is not installed, so the gate fails until the worker passes a /tmp pnpm store, `pnpm_config_verify_deps_before_run=false` and `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium` by hand.
- Found: worker d7606759 on rpo-wellness, 2026-10-14.

## install.sh --check ignores file mode on profile-script copies
- Where: `worker-host/install.sh`, `check_copies`.
- What happens: a copy that lost its exec bit reports no drift, but Foreman runs `worker-pane.sh` and `wait-for-workers.sh` directly, so they would fail with "Permission denied".
- Found: review of dc9626f, 2026-10-14.

## install.sh does not bring up a second host
- Where: `worker-host/install.sh --apply`.
- What happens: on a host with an older worker install, `--apply` reports no drift afterwards, but runs still fail: it does not install the trusted Hermes runtime release that `agent-hermes-worker` pins (`TRUSTED_HERMES_SOURCE`, runs end `runtime_unavailable`), and it does not enable `agent-worker-broker.socket` (repo-worker says "worker broker unavailable"). `--check` reports neither.
- Found: bringing up the MacBook Air worker host, 2026-10-14.

## chain-workers.sh starts a job in a folder another chain is about to use
- Where: `worker-host/bin/chain-workers.sh`.
- What happens: two chains waiting on the same run both launch when it ends. When that run fails, the first chain's retry is refused ("repository already has an active run") and the second chain's job starts on top of the failed run's uncommitted work. Seen in red-acre-integrate: K2 fix1 failed on a provider fault, the J3 fix2 chain started in its tree and committed the failed run's work for it.
- Found: Red Acre work, 2026-10-15 (runs 6a3d8332, eeb5b8ec).

## install.sh --apply refuses on a fresh host
- Where: `worker-host/install.sh` (active-run idle check).
- What happens: with no `repo-worker` launcher yet, it cannot list active runs, counts them as unknown and refuses, so it cannot do a first install. `worker-host/bootstrap.sh` works around it by linking the launcher first.
- Found: read-only mapping of the iMac and Air worker hosts for sim, 2026-10-15.

## Workers can override their root-owned git config
- Where: `/var/lib/agent-worker/.config/git/config` on every worker host (`.config` is agent-worker 0700, in the broker's `ReadWritePaths`, and the broker sets `XDG_CONFIG_HOME` to it).
- What happens: git reads that file after the root-owned `/var/lib/agent-worker/.gitconfig`, so a worker can change its commit identity and `safe.directory` entries.
- Found: review of `worker-host/bootstrap.sh`, 2026-10-15.

## committer cannot make a merge commit
- Where: the `committer` helper workers use for every commit.
- What happens: during a merge it fails with "cannot do a partial commit during a merge", so a worker merging branches must fall back to plain `git commit`, against the commit rule in AGENTS.md.
- Found: Red Acre N2 merge, 2026-10-16 (run 349d149a, merge fe54e5e).

## A worker turn that stops partway now fails with no result
- Where: `worker-host/libexec/agent-worker-hermes/host/bin/agent-hermes-worker` `run_child` (`if returncode != 0: return returncode, None, ...`) with Hermes e3d78e60 `hermes_cli/cli_single_query.py` `_single_query_exit_code`.
- What happens: Hermes 9caa2133 exited 0 with the reply when a one-shot turn stopped partway (iteration cap, `completed: False`). e3d78e60 exits 1 for `partial` or `completed: False`, so the adapter reports `provider_failed` and drops the partial reply.
- Found: read-only review of a4d86ab, 2026-10-16.

## The worker adapter admits Bedrock but the release cannot run it
- Where: `worker-host/libexec/agent-worker-hermes/host/bin/agent-hermes-worker` `TRUSTED_DIRECT_PROVIDERS` (`bedrock`, `aws`, `amazon-bedrock`) and `worker-host/build-hermes-release.sh` `EXTRAS`.
- What happens: neither the 9caa2133 nor the e3d78e60 release has boto3 (the `bedrock` extra). With lazy installs off for workers, a Bedrock run fails at provider setup.
- Found: read-only review of a3c5766, 2026-10-16.

## Run home checks are a denylist
- Where: `worker-host/libexec/agent-worker-hermes/host/bin/agent-hermes-worker` `prepare_runtime_home` (refuses `plugins`, `installs`, `.env`, `.op.env`, `.container-mode` by name).
- What happens: Hermes reads many names from `HERMES_HOME` (the worker-owned run home). Three review rounds of a4d86ab each found one more name that reaches code or a guard (`installs`, `.env`, `.container-mode`). Any name a later Hermes adds is accepted. Not yet checked: the pm store `<run home>/tools` (`tools/facts.json`, read by `pm.installed_package` and `env_for`) and `lsp/bin` (LSP servers; skipped today because worker repos are not trusted workspaces).
- Found: reviews of a4d86ab, a3c5766 and 09ad092, 2026-10-16.

## A worker's full report is lost when a late process notice arrives after it

Where: repo-worker runs on the hermes agent (final.txt and stream.log keep only the last assistant message).
What happens: the worker writes its report, then a late background-process notice makes it answer once more; that short answer replaces the report, so the findings with file:line and fixes are gone (red-acre review run 7dbcac7d, 2026-10-21; earlier runs show the same "late completions" reply).
How found: Foreman read `repo-worker --output`, final.txt and stream.log; only the summary was left.

## A broken stream chunk ends a worker run as a non-retryable error

Where: worker Hermes runtime 9caa2133 on sim (`agent/chat_completion_helpers.py` `_call_anthropic`, anthropic SDK `accumulate_event` partial JSON of a tool input).
What happens: a streamed tool-call input that is not valid JSON raises `ValueError: expected value at line 1 column 11`. The loop retries once, then calls it a "Non-retryable client error" and the run ends `failed` with no report ("Hermes provider exited with a failure status").
How found: marquee review run ffb6fab1 (claude-opus-5-5, 2026-10-22), `logs/agent.log` in its run home; a fresh run of the same packet was started.
Still happens on runtime e3d78e60: marquee review run 08ddb7b8 (claude-opus-5-5, 2026-10-22 18:17), same error after 55 API calls, "Streaming failed before delivery" then "Non-retryable client error". Again in run a47ff056 (18:33, after a 429). In e3d78e60 the text "expected value at line" is a listed stream-parse marker (`agent/api_error_summary.py:19`, used by `turn_api_error.py:_is_local_validation_error`), yet the run still ends at `agent/turn_recovery.py:1106`, so the error reaches that path through a classification that does not check the marker.
Twice in a row on sim (9caa2133), one packet: Red Acre farm-rules fix runs 781e7eb0 and 93e00846 (2026-10-25 23:10 and 23:16 CDT, 4-7 minutes in, both after a 429 retry at the start); in 93e00846 the call that broke came right after a foreground command was promoted to a background process (timeout over 600 s).

## Workers cannot reach the GPU, so GPU frame timing runs only on the host

Where: the worker sandbox on the iMac (agent-worker-runner unit; no `/dev/dri` inside).
What happens: a worker's headless Chromium falls back to llvmpipe or SwiftShader, and a headless sway with `WLR_RENDERER=gles2` fails with "Failed to open '/dev/dri/renderD128'". Every speed number a worker records is CPU only, and Foreman reruns the scripts on the host for the GPU numbers.
How found: Red Acre engine test run 758c362c (2026-10-24), its README notes and `native-sway-gles2.log`.

## The worker cargo proxy pins CARGO_HOME to the worker home

Where: `worker-host/bootstrap.sh`, the Rust proxy in the worker `.local/bin`.
What happens: the proxy exports `CARGO_HOME=/var/lib/agent-worker/.cache/cargo`, which overrides a packet's `CARGO_HOME=/tmp/...`. Where that folder is read-only, the worker calls `/usr/bin/cargo` directly to get past it.
How found: Red Acre engine test run 758c362c (2026-10-24), its report.

## Read-only reviewers get no Rust toolchain on the PATH

Where: the worker sandbox for `--access read` runs on the iMac.
What happens: a reviewer found no Rust toolchain and installed its own in `/tmp/rv-rustup` to run `cargo test`. With that toolchain absent, a mise `cargo-clippy` wrapper on the PATH ran a different toolchain without the wasm32 std, so wasm32 clippy failed with "can't find crate for std". Write-mode workers hit the same root: plain `/usr/bin/cargo` fails unless `RUSTUP_HOME=/var/lib/agent-worker/.state/rustup` is set, and with it the toolchain has the wasm32 target. The sandbox does not export that RUSTUP_HOME.
How found: Red Acre engine base review 29fbdb20 and fix worker beff40cb (2026-10-24), their reports.

## Tool-name repair notices in a worker's final text hide its OUTCOME line

Where: `worker-host/libexec/agent-worker-runner` `reported_outcome` (reads only the first non-empty line), and the Hermes harness, which prints `🔧 Auto-repaired tool name: 'mcp__tool_describe' -> 'tool_describe'` (and, after a context compaction, `⟳ compacting context…`) into the agent's final text.
What happens: a worker that calls `mcp__tool_describe` or `mcp__tool_call` gets these notices as the first lines of its final text. Its report starts `OUTCOME: COMPLETED` on the next line, but the run ends `status=blocked`, "worker exited without a machine-readable terminal outcome". Runs without the notices end `completed`.
How found: Red Acre runs on sim 2026-10-25: bfaead6e (farm rules) and 5f5cf248 (its review) blocked with the notices first; 02f61ed0 (HUD sketches) completed without them (`repo-worker --output <run>`). On the iMac (e3d78e60), 0fba52a9 (Red Acre clock and light) blocked with `⟳ compacting context…` first.

## Workers on sim have no vision_analyze

Where: the worker runtime on sim (repo-worker `--agent hermes`); the iMac's e3d78e60 runtime has the tool.
What happens: a packet that asks the worker to look at its own shots (`vision_analyze`) cannot be met on sim: the tool is not in the session and tool search does not find it. The worker measures pixels instead and ends BLOCKED; Foreman looks at the shots on the host.
How found: Red Acre play-farm worker 7f1d09fb on sim (2026-10-26), its report; the iMac menu-mockups worker 4d7852d8 the same day used the tool.

## A run that stops without its report loses the run's output

Where: repo-worker `--output` on sim (agent-workers state under `/var/lib/agent-worker/.local/state/agent-workers/runs/<runId>/`).
What happens: a worker run that stops without writing `final.txt` leaves `repo-worker --output <runId>` printing "final output is not available for run <runId>". The run's `stream.log` is gone too (the runs/ folder is not in the user's home), so there is no way to see what it did before it stopped. Whatever it committed stays in the clone, but anything uncommitted is only visible with `git status` in the clone itself.
How found: Red Acre runs on sim 2026-10-27: 2f34ad2a (check-scripts fix2), e2eebd33 (save-clock fix3), ec681976 (play-farm fix1), and 2f551689 (a soft-rounding review) all stopped with no report; three of the four left uncommitted work in their clones. Recovered by reading `git status` in each clone and relaunching a finisher worker on the same clone.

## A delegate_task child with an output_schema can lose its whole report
- Where: Foreman's `delegate_task` (Hermes harness), background children with `output_schema`.
- What happens: two host-setup children on 2026-10-27 ended `failed`. One stopped with "session storage was busy (another Hermes process was writing to the state database)". The other had its report rejected as not JSON; the retry turn no longer held the report, so it returned "nothing verified". In both cases the work on the host was done or half done, but no record of it came back.
- Found: deleg_db83d360 and deleg_4b317e4b (MacBook Pro worker-host setup); the Foreman re-read the host state by hand.

## install.sh --apply refuses while runs are active, and that is the only way to fix a host's retry limit
- Where: worker-host/install.sh (the active-runs guard), worker-host/libexec/agent-worker-hermes/host/hermes-worker/config.*.yaml.
- What happens: a host that still has the 3-retry config loses a worker run on every 5-minute internet drop, and the fix (api_max_retries: 12) needs --apply, which refuses while any run is active. On a busy host there is no gap, so the host keeps losing runs all day.
- Found: sim on 2026-10-27, two runs lost that way (a000f02f, d52e7ec8). Workaround used, safe only because the adapter builds each run's config.yaml from the template at launch: back the two installed yamls up and copy the repo's versions in when the only diff is api_max_retries. A real fix: install.sh gets a flag that replaces the retry settings alone while runs are active.


## chain-workers.sh gives up after 6 minutes when the host's slots are full
- Where: `worker-host/bin/chain-workers.sh` (the inner `for try in 1..6` loop, `sleep 60`, then `exit 1`).
- What happens: when the previous run ends and other chats hold every slot on the host, the chain waits only 6 minutes for a slot, prints `FAILED: repo-worker: N runs already active`, and drops the rest of the chain. The queued job never starts, and nothing tells the coordinator until the chain's own notice.
- Found: red-acre pause-a after title-a 54631b9b on the iMac, 2026-10-27 (7 runs from other chats, limit 2); the job was moved to the Pro by hand.

## Every Hermes launch hides the run list from the host owner for up to a second
- Where: `worker-host/libexec/agent-worker-broker` `launch()`, `ensure_directory(HERMES_RUNTIME_ROOT, mode=0o700, ...)`.
- What happens: the chmod 0700 zeroes the ACL mask on `/var/lib/agent-worker/.hermes-worker`, so the `u:hermes:r-x` grant the Hermes adapter sets stops working until a running adapter renews it (at most a second) or the new run's adapter starts. If the launch fails before its adapter runs and no other Hermes run is live, `hermes` cannot list or enter any run home until the next Hermes run.
- Found: reading the broker while adding the state.db read grant (e6ab0ff).

## The run-home traverse grant makes top-level other bits count for the host owner
- Where: `worker-host/libexec/agent-worker-hermes/host/bin/agent-hermes-worker` `grant_state_read` (`u:hermes:--x` on each Hermes run home).
- What happens: with `--x` on the run home, `hermes` can open any top-level entry it knows the name of, so that entry's other bits decide its access: a top-level file left 0644 (or a folder 0755) becomes readable by `hermes`, not just `state.db*`. The grant does not check the other entries' modes. Live hosts are clean today because workers run with `UMask=0077`; a file made with an explicit mode or a later chmod is not covered.
- Found: review of e6ab0ff (read grant on state.db).
