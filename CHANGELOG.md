# Changelog

This file records user-visible changes to the portable coding-agent system.

## Unreleased

- Workers run in the Hermes harness. A worker is the Hermes profile `worker`, started by a kanban card, with its shell and file tools inside a rootless podman container built from `workbench/Containerfile` (.NET 9, Python with pytest and uv, Node, Rust, Go, CMake, Chromium, Postgres). It works in a git worktree of a clean clone under `~/workbench`, commits on the card's own branch, and has no keys, so it cannot push. `./setup.sh worker` builds the image and sets up the profile from `profiles/worker/`, and `./setup.sh repo <name>` makes or updates the clean clone.
- Every card is reviewed. The worker hands its card to the Hermes profile `reviewer` (`profiles/reviewer/`), which gets a container of its own. It sees `~/workbench` through a layer of its own, so it builds and tests the branch in place and nothing it writes reaches the worker's files. It approves the branch, sends the card back to the worker with each defect named, or blocks it with a question for Hermes. The agent that made the card merges and pushes an approved branch.
- An agent in the workbench is the host user, not root, so a repository's gate behaves in the container as it does on the host: tests that refuse to run as root run, Chromium's sandbox starts, and a file the user may not read stays unreadable. The agent still owns its environment: `pacman` installs packages without root, and `throwaway-postgres` starts a database for tests.
- `./setup.sh <profile>` takes a setting out of the profile when `profile.json` stops naming it. It used to leave the old value in place.
- Study-guide authors run in the Hermes harness too. The profile `author` does one round of one Ashwren guide in a workbench container that sees only that guide's work directory and has no network. Ashwren's `tools/run-guide.sh` starts it.
- The old worker machine is removed, and this repository now holds only the new one. Gone: the `repo-worker` launcher with its broker, supervisor, Hermes adapter, usage watch and wait and chain scripts (`worker-host/`); the `agent-claude`, `agent-codex` and `agent-kimi` launchers and the Kimi session guard; the hook dispatcher; `install.sh`, `configure-hosts.py`, `system.json`, `validate.sh` and `action.yml`; the commands `agent-repo-check`, `agent-repo-adopt`, `agent-system-doctor`, `docs-list`, `tirith-install`, `agent-autoreview`, `agent-capabilities`, `agent-skill-audit`, `agent-lease`, `agent-forge-handoff` and `agent-repo-inventory`; the skills `capabilities`, `maintain-skills`, `portfolio` and `worker-first`; and `docs/`. `./setup.sh tools` is the one install step for what stays: it links `committer`, `agent-trash` and `agent-session-recover` into `~/.local/bin` and the eleven skills into `~/.agents/skills` and `~/.claude/skills`, and removes the link of anything deleted here. The skills `delegate`, `review`, `land` and `fix-issue` follow the working agreement: a task states its outcome and goes to a worker as a kanban card, a review gives one verdict, and finished work is pushed. The gate is `python3 -m unittest discover -s tests`, and it now tests `setup.sh`. The repository has its own `AGENTS.md` again.
- The working agreement, loaded by every coding agent, is now `working-agreement.md` (it was `AGENTS.md`); `./setup.sh links` links it as `~/AGENTS.md` and `~/.claude/CLAUDE.md`. It is rewritten around ownership: the codebase and its environment are the worker's own, workers fix the architecture and the problems they find instead of making the smallest possible change, may add dependencies with a stated reason, and finish through ordinary obstacles. The agent that was given a task directly pushes finished work to `origin`, the primary Git server, without asking; a dispatched worker leaves its commits for the agent that dispatched it. Asking first is kept for releasing, deploying, publishing outside Git, making private things public, production data and decisions a repository reserves for Hermes. Shared-machine rules (leave others' changes alone, `agent-trash`, one heavy build at a time) now apply only when working on Hermes's computer.
- `committer` during a merge says to finish with `git commit`. It used to fail with git's "cannot do a partial commit during a merge".

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
