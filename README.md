# Coding Agent System

A portable, model-neutral engineering system for Codex, Claude Code, Cursor,
and other coding-agent hosts. It keeps policy terse, loads workflows as skills,
dispatches skill-owned hooks, reconstructs work from repository evidence, and
uses deterministic checks for the parts that should not depend on judgment.

## Ownership

This repository owns the portable layer:

- `AGENTS.md`: canonical global engineering policy.
- `skills/`: assignable job contracts and their scripts, references, and hooks.
- `hooks/dispatch.py`: one host adapter for global and repository skill hooks.
- `bin/`: small deterministic helpers for continuity, delivery, review, and
  repository hygiene.
- `system.json`: the exact managed skill, command, binary, and hook catalog.
- `install.sh` and `configure-hosts.py`: idempotent shared installation plus a
  caller-selected host integration.
- `host/local/`: the local-machine invocation defaults for `claude` and
  `codex`; these are not part of the shared binary catalog.
- `tests/` and `validate.sh`: portable enforcement.

Product facts and workflows remain in each product repository. VM credentials,
VM launch behavior, and cloud bootstrap belong in
`hermes-os/coding-agent-vm-setup`, which pins this repository at an exact Git
revision and supplies its own host integration.

## Install

```bash
git clone https://github.com/hermes-os/coding-agent-system ~/coding-agent-system
~/coding-agent-system/install.sh
agent-system-doctor
```

The installer wires the canonical policy and skills into `~/.agents`, Codex,
Claude Code, and Cursor while preserving unrelated host configuration. Models
remain task-prompt assignments. Persistent agent memory is disabled.

The default install selects `host/local`, which keeps the requested local
Remote Control and bypass-permission invocation behavior. Integrations such as
the VM setup call `install.sh --host-integration /path/to/integration`; the
shared catalog never owns those launchers.

Use `install.sh --coordination-repo /path/to/git-root` when a host integration
should keep cross-host lease refs in a different repository. The chosen path is
recorded locally in `~/.agents/config.json`; it is host state, not project
memory.

## Repository Contract

Product repositories keep one root `AGENTS.md` beginning with:

```text
READ ~/.agents/AGENTS.md BEFORE ANYTHING (skip if missing).
```

`CLAUDE.md` is a symlink to `AGENTS.md`. Product-specific skills live under
`.agents/skills`. Cross-session work uses one mutable `docs/plan/<project>.md`;
ordinary work uses no tracker.

Run the deterministic repository check before delivery:

```bash
agent-repo-check --repo "$PWD" --strict
```

It validates instruction wiring, local skills and hooks, document metadata,
active-plan shape, and tracked high-risk clutter. Project tests and delivery
commands still come from the repository's own guide.

After the global-system revision is published, wire a repository to that exact
revision with:

```bash
agent-repo-adopt --repo "$PWD"
```

This creates only the `CLAUDE.md` pointer when missing and a managed GitHub
Actions workflow pinned to the full global-system commit SHA. It refuses to
overwrite an unrelated workflow or repository guide. Re-run with `--check` to
detect a stale pin without changing files.

## Validation

```bash
./validate.sh
./install.sh
agent-system-doctor --repo "$PWD"
```

The source catalog is intentionally small. Add a shared skill only when it is a
reusable job with a distinct output contract; keep product workflows local.

## Attribution

The architecture follows Peter Steinberger's public `agent-scripts` work. See
`STEIPETE_AGENT_SCRIPTS_LICENSE` and `OPENCLAW_AGENT_SKILLS_LICENSE` for adapted
components and their licenses. New repository code is MIT licensed.
