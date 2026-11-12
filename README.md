# coding-agent-system

How Hermes's agents work: one agreement, one launcher, one environment.

Every coding worker, reviewer and study-guide author is a profile of the Hermes
agent harness. A coding task is a card on Hermes's kanban board. The worker
that takes it gets a container of its own and a branch of its own, and owns
the codebase while it works. This repository holds everything that makes that
true on a host.

| Path | What it is |
| --- | --- |
| `working-agreement.md` | The agreement every agent reads, in every repository. |
| `profiles/<name>/` | A Hermes profile: `intro.md` opens its prompt, `profile.json` is its configuration. |
| `workbench/Containerfile` | The image a profile's shell, file and code tools run in. |
| `setup.sh` | Puts all of this on a host. |
| `bin/` | Commands for work in any repository: `committer`, `agent-trash`, `agent-session-recover`. |
| `skills/` | Skills for Claude Code and Codex sessions in any repository. |

## How a task flows

1. **A card.** An agent, or Hermes himself, writes the task: the outcome, why
   it matters, and what done means. It goes on the board assigned to `worker`,
   with a worktree workspace on the repository's clean clone:

   ```bash
   hermes kanban create "<title>" --body-file task.md \
     --assignee worker --workspace worktree:$HOME/workbench/<repo>
   ```

   Inside the harness the same thing is `kanban_create` with assignee `worker`,
   workspace kind `worktree` and workspace path `/home/hermes/workbench/<repo>`.

2. **A worker.** The board's dispatcher, which runs inside the Hermes gateway,
   starts `hermes -p worker chat -q "work kanban task <id>"`. Kanban makes a git
   worktree at `~/workbench/<repo>/.worktrees/<task-id>` on branch
   `wt/<task-id>`.

3. **A workbench.** The agent runs on the host, but its shell, file and code
   tools run in a rootless podman container made from `localhost/workbench:latest`
   for this one task. The container sees `~/workbench` and a shared package
   cache. It has no keys, no tokens, no SSH, no `~/.hermes` and none of
   Hermes's own working copies, so the worker cannot push or reach an account.
   Inside, the worker can install, build and rebuild whatever the task needs.

4. **A review.** The worker commits on its branch and hands the card to the
   `reviewer` profile. The dispatcher starts the reviewer in its own container.
   It sees `~/workbench` through a layer of its own, so it builds and tests the
   branch in place and nothing it writes reaches the worker's files. The
   reviewer reads the branch, runs what matters, and gives one verdict: it
   approves and the card is done, it sends the card back to the worker with
   each defect named, or it blocks the card with a question for Hermes.

5. **A merge.** The agent that made the card reads the diff once the card is
   done, merges the branch and pushes to `origin`, Hermes's own Git server.

   A card that builds on another card's work waits for that merge, not for the
   other card's `done`: the board starts a `--parent` child the minute its
   parent is done, on a worktree cut from a `main` that does not hold the
   parent's work yet. Park such a card with `hermes kanban schedule <id>
   "<reason>"` when you make it, and release it with `hermes kanban unblock
   <id>` after the merge.

Each profile runs on the one model its `profile.json` names. There is no
fallback chain: a run that cannot reach its model fails with the provider's
own error.

## Study-guide authors

An Ashwren study guide is written in rounds on the host `sim`. Ashwren's
`tools/run-guide.sh` starts each round as `hermes -p author --oneshot` and
names the guide's work directory as the container's one volume, at
`/workspace`. The round sees that folder and nothing else of the host, and has
no network. The profile's settings leave `terminal.docker_volumes` out on
purpose: a volume set in the profile would replace the one the launch names.

## Set up a host

A host needs the Hermes agent with its gateway running, rootless `podman`,
`git` and `python3`, and SSH access to the Git server for the clones.

```bash
git clone git@git.imhermes.dev:hermes/coding-agent-system.git ~/Projects/hermes-os/coding-agent-system
cd ~/Projects/hermes-os/coding-agent-system

./setup.sh links          # the working agreement as ~/AGENTS.md and ~/.claude/CLAUDE.md
./setup.sh tools          # bin/ into ~/.local/bin; skills/ into ~/.agents/skills and ~/.claude/skills
./setup.sh worker         # build the image, then write the profile
./setup.sh reviewer
./setup.sh author         # on sim, the guide host
./setup.sh repo <name>    # the workers' clean clone ~/workbench/<name>, made or fast-forwarded
```

Every command can be run again. `./setup.sh <profile>` brings the profile back
to exactly what this repository says: its settings, its `SOUL.md`, and its
skills. `links` and `tools` make links into this checkout, so a `git pull`
here updates the agreement, the commands and the skills on the host; `tools`
also removes the link of a command or skill that was deleted here. Profiles and
the image are copies, so run `./setup.sh <profile>` again after a pull that
changes `profiles/` or `workbench/`.

`setup.sh` does not sign a profile in. Each profile needs its model provider's
sign-in on the host, held by the Hermes process and never by the container.

Workers see a repository as it is on the Git server. Push what a task depends
on, then run `./setup.sh repo <name>` before making the card.

## Add a profile

Make `profiles/<name>/` with two files, then run `./setup.sh <name>`:

- `intro.md`: who the agent is, what its workbench is, and how it hands work
  back. It opens the profile's `SOUL.md`.
- `profile.json`:
  - `description`: one line, shown in Hermes's profile list.
  - `agreement`: `true` puts `working-agreement.md` after the intro.
  - `skills`: names of skills bundled with Hermes, copied into the profile.
  - `config`: Hermes settings as `hermes config set` takes them, such as the
    model, the toolsets, and the container's image, volumes and limits.

The tests set up every folder under `profiles/`, so a new profile is covered
when it is added.

## Develop

```bash
python3 -m unittest discover -s tests
```

`AGENTS.md` says what an agent working here must know.

## Attribution

Parts of `bin/` and `skills/` are adapted from Peter Steinberger's
`agent-scripts` work. `STEIPETE_AGENT_SCRIPTS_LICENSE` and
`OPENCLAW_AGENT_SKILLS_LICENSE` carry the licenses of the adapted material.
Everything else is MIT licensed under `LICENSE`.
