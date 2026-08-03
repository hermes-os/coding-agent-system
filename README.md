# Coding Agent System

A portable, model-neutral engineering system for Codex, Claude Code, Kimi CLI, Cursor,
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
- `host/local/`: the local-machine invocation defaults for `claude`, `codex`,
  and `kimi`; these are not part of the shared binary catalog.
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
Claude Code, Kimi CLI, and Cursor while preserving unrelated host
configuration. Kimi receives the policy through a generated default-agent
extension because it does not load a home-level `AGENTS.md` for repository
work. That extension disables Kimi's inherited subagents so repository work
stays inside its assigned worker boundary. Native `Stop` and shell-only
`PreToolUse` hooks dispatch through the same skill-owned hook catalog, and a
prompt guard rejects any resumed session whose persisted system prompt lacks
the current policy digest. Policy updates therefore require a fresh Kimi
session; unchanged managed sessions remain resumable.

The managed Kimi launcher covers noninteractive `--print` and `--quiet` work,
including explicit policy-current session IDs. It rejects interactive picker,
continue, wire/ACP, caller agent, config, and skill-directory overrides because
those paths can restore or create an unverified system prompt in Kimi CLI
1.47.0. The `acp`, `term`, and `web` subcommands are rejected for the same
reason. Administrative Kimi subcommands pass through unchanged.

The shared system does not author model assignments. A provider-required,
operator-selected default may remain in local provider configuration as host
state. Persistent agent memory is disabled.

The default install selects `host/local`, which pins Claude Remote Control for
every interactive session and enforces one access contract across providers.
Agent invocations default to `AGENT_ACCESS_MODE=write`: Codex bypasses approval
and sandbox prompts, Claude uses `bypassPermissions`, and Kimi uses `--yolo`.
`AGENT_ACCESS_MODE=read` is the explicit exception for read-only inspection and
review; it disables those bypasses. Orchestrators must pair read mode with an
external read-only filesystem boundary. Administrative provider commands pass
through unchanged.

Integrations such as the VM setup call
`install.sh --host-integration /path/to/integration`; the shared catalog never
owns those launchers. Claude and Codex launchers are the base integration
contract; a host may declare Kimi support by also supplying an executable
`bin/agent-kimi`.

Global skill hooks remain available from any working directory. Repository
skill hooks are discovered only after Git resolves the working directory to a
repository root, so a home directory, scratch directory, or cross-repository
launcher cannot accidentally reinterpret its `.agents` tree as project policy.
A directory with a broken or inaccessible `.git` marker still fails closed;
inside a valid repository, all repository hook validation remains strict. Start
the agent in the target repository when that repository's local hooks should
apply.

Use `install.sh --coordination-repo /path/to/git-root` when a host integration
should keep cross-host lease refs in a different repository. The chosen path is
recorded locally in `~/.agents/config.json`; it is host state, not project
memory.

Enrolled hosts can exchange constrained, exact-SHA PR work with
`agent-github-handoff`. Local `githubPeer.localPeer`, repository, and
trusted-author settings define its authorization surface; handoffs never grant
mutation, commands, merge, or deploy authority. See the portfolio skill before
enabling a host-specific watcher. Peer enrollment comes only from the canonical
host config (or a root-pinned nonstandard install), never a CLI or environment
override. A bounded organization discovery call overscans recent constant-label
candidates and revalidates every returned packet without interpreting PR bodies
as instructions.

To replace an older cataloged but unmanifested installation, pass its clean
tracked source explicitly:

```bash
./install.sh --migrate-from-system-root /path/to/old/system
```

Migration uses the old source's own `system.json`, retires exact legacy-only
paths, and accepts only destinations that still match that source tree. An
altered, untracked, or unrelated path fails the whole preflight without
changing host configuration.

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
