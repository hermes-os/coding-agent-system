# coding-agent-system

This repository is the machine every agent of Hermes's runs on: the working
agreement each agent reads, the Hermes profiles that do the work (`profiles/`),
the container image their tools run in (`workbench/`), `setup.sh`, which puts
all of it on a host, and the commands (`bin/`) and skills (`skills/`) shared by
every repository. `README.md` describes how a task flows through it.

## Gate

```bash
python3 -m unittest discover -s tests
```

The tests run `setup.sh` against a temporary HOME with stand-in `hermes` and
`podman` commands. They never touch the real profiles or build the image.

## What the code cannot tell you

- **The main checkout on a host is live.** `~/AGENTS.md`, `~/.claude/CLAUDE.md`,
  the commands in `~/.local/bin` and the skills in `~/.agents/skills` and
  `~/.claude/skills` are links into `~/Projects/hermes-os/coding-agent-system`.
  A commit that reaches that checkout changes what every agent on the host
  reads, at once. Profiles and the image are copies: they change only when
  someone runs `./setup.sh <profile>` on that host. The hosts are `imac`, `air`
  and `sim`.
- **`working-agreement.md` is in every agent's prompt on every run.** Each line
  costs every run, so it stays short. Sharpen its wording freely. Ask Hermes
  before changing what it asks of agents.
- **A worker holds no keys, by design.** Its container sees `~/workbench` and a
  package cache, nothing else. Do not add a volume, a variable or a tool that
  gives a profile credentials, `~/.hermes`, `~/Projects`, or a way to push.
- **One model per profile.** `fallback_providers` stays empty. A run that
  cannot reach its model fails with that provider's own error; it does not
  become a run somewhere else.
- **Configure Hermes, never patch it.** `setup.sh` uses only `hermes profile
  create`, `hermes config set` and Hermes's bundled skills, so a Hermes update
  cannot undo it. Keep it that way.
- **A gate line must run in the workbench.** Other repositories' gates run
  inside the worker's container, which has only what `workbench/Containerfile`
  installs. A command that a gate calls belongs in the image too.
- **`skills/` is for Claude Code and Codex sessions.** A skill earns its place
  when it helps in any repository. Hermes profiles take Hermes's own bundled
  skills, named in `profile.json`.
