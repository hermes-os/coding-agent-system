---
summary: Source-locked parity work for the portable parts of steipete/agent-scripts.
read_when:
  - Changing worker routing, portfolio orchestration, skill mirroring, or the OpenClaw control plane.
---

# Steipete Agent Scripts Parity

## Status

Complete. The reference is `steipete/agent-scripts` at
`bb3688355a4c1894dd53b4ed867d1600918fadf0` (2026-07-23). Parity means
preserving every compatible behavior, not copying Peter-specific identities,
accounts, model pins, macOS fleet rules, or unavailable integrations.

## Problem

Before this work, the system credited selected patterns from Peter's workspace
but did not provide its durable project-thread lifecycle, five-minute root
watch, deterministic resume, lane refill, or complete source-to-local parity
record. Repository workers were intentionally memory-isolated, but their
sessions were disposable and remained children of the OpenClaw gateway.

## Goals

- Preserve the one-root-orchestrator and one-execution-owner-per-repository
  boundary.
- Keep OpenClaw personal memory inaccessible to Codex, Claude Code, and Kimi.
- Give every installed CLI a native, resumable task or project session.
- Run active workers outside the gateway service cgroup and track them by run
  and provider session ID.
- Re-enter orchestration every five minutes while work, waits, or decisions
  remain.
- Port generic skills and map every upstream skill and helper to an adopted,
  adapted, equivalent, conditional, or excluded result.

## Non-Goals

- Copying Peter's personal identity, repository ownership, account routing,
  release authority, secret manager, Mac fleet, channels, or product policy.
- Pinning a model or making one provider the permanent implementation worker.
- Bulk-installing skills whose executable dependencies or services are absent.
- Loading OpenClaw memory, chat history, or persona into repository workers.
- Replacing repository code, tests, plans, and provider state with a global
  work diary.

## Decisions

- Adapt `$codex-first` as provider-neutral `worker-first`: coordinators freeze a
  self-contained work order, use a fresh resumable session for a new order,
  capture its ID, monitor liveness, and verify the result.
- Adapt `maintainer-orchestrator` to one persistent project session per
  repository. Project sessions process their queue serially and never fan out
  mutation-owning subagents.
- Keep active run metadata and provider session data outside `~/.openclaw`;
  expose only sanitized status to the private orchestrator.
- Use the existing managed installer instead of Peter's `sync-skills`. It
  already creates flat Claude links, global instruction pointers, collision
  preflights, and stale managed-path pruning.
- Use the existing `portfolio` leases as the exact-head public mutation gate.
- Keep the heartbeat as a wake-up and reconciliation mechanism, never project
  memory or a substitute for an active worker.
- Keep the complete source mapping in
  `docs/steipete-agent-scripts-parity.md`; active plans remain limited to
  execution state.

## Milestones

- [x] Freeze the upstream reference and inventory policy, 53 skills, helpers,
  and orchestration behavior.
- [x] Classify exact adoption, model-neutral adaptation, existing equivalents,
  conditional capabilities, and exclusions.
- [x] Implement portable skill and portfolio gaps in `coding-agent-system`.
- [x] Implement durable workers and compatible maintainer orchestration in the
  private OpenClaw workspace.
- [x] Enable and validate the five-minute watch without restarting the gateway.
- [x] Prove native session resume, service durability, skill discovery,
  monitoring, and OpenClaw-memory isolation.

## Verification

- `./validate.sh`: 106 tests pass with two expected case-insensitive-filesystem
  skips; strict skill audit, repository check, and `git diff --check` pass.
- OpenClaw workspace validator and configuration validation.
- New-session and explicit-resume smoke tests for Codex, Claude Code, and Kimi.
- Kimi resume accepts a policy-current session and rejects a stale policy
  digest before any new turn executes.
- Worker service remains outside `openclaw-gateway.service`.
- Read worker cannot write its repository or inspect `/root/.openclaw`.
- Heartbeat interval is five minutes, target remains `none`, and no gateway
  restart occurs.
- Source ledger covers every upstream skill and helper at the frozen commit.
- One independent Codex review session was resumed through each repair cycle
  and closed with no actionable findings.

## Open Questions

- None. Conditional skills become active only when the named executable,
  service, repository type, or user request makes them applicable.
