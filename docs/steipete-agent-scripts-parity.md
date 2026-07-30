---
summary: Source-to-local parity ledger for the compatible parts of steipete/agent-scripts.
read_when:
  - Auditing upstream parity or deciding whether to activate a conditional skill.
---

# Steipete Agent Scripts Parity

Reference: `steipete/agent-scripts` commit
`bb3688355a4c1894dd53b4ed867d1600918fadf0` from 2026-07-23.

`Repository-adopted` preserves the compatible behavior in this repository.
`Control-plane adopted` preserves it in the private OpenClaw workspace and does
not claim that the implementation lives here. `Adapted` preserves the useful
behavior while removing a model, account, machine, owner, or host assumption.
`Equivalent` names an existing implementation. `Conditional` means the
behavior is suitable only when its named dependency or task exists. `Excluded`
means it is specific to Peter's environment or conflicts with this system.

Control-plane proof is owned by the OpenClaw workspace's `ORCHESTRATION.md`,
`scripts/repo-worker`, `scripts/orchestrator-watch`, and
`scripts/validate-workspace`. Repository checks can validate the policy side
but intentionally cannot inspect that private memory boundary.

## Policy And Helpers

| Upstream surface | Local result |
| --- | --- |
| concise shared `AGENTS.MD` plus repo pointer | Repository equivalent: canonical global policy and managed host pointers |
| coordinator delegates build work and verifies it | Repository-adapted: provider-neutral `worker-first` |
| fresh session for a new work order | Control-plane adapted across three providers |
| capture session ID and deterministic resume | Control-plane adopted for Codex, Claude Code, and policy-current Kimi sessions |
| harness-visible background task | Control-plane adapted as a transient user service with durable status and logs |
| liveness watchdog | Control-plane adapted with activity age and explicit resume |
| one project thread per repository | Control-plane adopted |
| support subagents are read-only | Control-plane adopted |
| project workers never create task workers | Control-plane adopted |
| five-minute root activation watch | Control-plane adopted |
| queue refill and owner decision briefs | Control-plane adapted to the private owner boundary |
| exact-head serialized public actions | Repository equivalent: `portfolio` leases |
| `committer` | Repository equivalent |
| `docs-list` | Repository equivalent |
| recoverable trash | Repository equivalent: `agent-trash` |
| skill validation and hook | Repository equivalent: `maintain-skills` and dispatcher |
| skill mirror and stale-link pruning | Repository equivalent: managed installer |
| browser helper | Conditional equivalent when the installed browser plugin is available |
| slash commands for pickup/handoff/fix/land/release | Repository equivalent |

## Skills

| Upstream skill | Result |
| --- | --- |
| `agent-transcript` | Conditional: only for an authorized GitHub publication workflow |
| `beeper` | Excluded: service and local cache absent |
| `browser-use` | Equivalent: installed browser capability |
| `clawsweeper-status` | Excluded: Peter-specific service |
| `clickclack` | Excluded: Peter-specific product operations |
| `cloudflare-registrar` | Conditional: Cloudflare tooling exists as an optional plugin |
| `codex-debugging` | Conditional: useful only in a Codex source checkout |
| `codex-first` | Adapted as provider-neutral `worker-first` |
| `codex-huge-context` | Excluded: Peter-specific route, model pins, and Keychain flow |
| `create-cli` | Repository-adapted with the compatible contract retained and workspace paths removed |
| `discord-clawd` | Excluded: Discord relay is not configured |
| `domain-dns-ops` | Conditional: activate for an explicitly named domain/provider |
| `fleet-maintenance` | Excluded: Peter-specific Mac fleet |
| `frontend-design` | Equivalent: installed frontend skills |
| `github-author-context` | Adapted into provider-neutral GitHub triage |
| `github-cache-hygiene` | Conditional: its `gh` and cache stack are absent |
| `github-deep-review` | Equivalent: `review` plus repository evidence |
| `github-project-triage` | Repository-adapted without Peter-specific owners, authority, or RepoBar |
| `hopper-debugger` | Excluded: Hopper and Apple host absent |
| `instruments-profiling` | Excluded on this host |
| `mac-maintenance` | Excluded on this host |
| `maintainer-orchestrator` | Control-plane adapted in OpenClaw plus repository `portfolio` policy |
| `markdown-converter` | Conditional: converter dependencies are absent |
| `nano-banana-pro` | Equivalent: installed image generation |
| `native-app-performance` | Conditional on an Apple build host |
| `notcrawl` | Excluded: Notion archive is absent |
| `npm` | Equivalent for repository releases; credential-specific flow excluded |
| `obsidian` | Excluded: local memory-wiki is the selected knowledge store |
| `one-password` | Conditional: `op` is absent |
| `openai-image-gen` | Equivalent: installed image generation |
| `openclaw-relay` | Conditional: `acpx` relay is absent |
| `oracle` | Conditional: executable is absent |
| `peekaboo` | Excluded on this host |
| `release-mac-app` | Excluded on this host |
| `release-tweets` | Excluded: public posting is not a default maintainer action |
| `reminders` | Excluded on this host |
| `remote-mac` | Excluded: Peter-specific hosts |
| `skill-cleaner` | Equivalent: `maintain-skills` |
| `sonos` | Excluded: service is not configured |
| `speaking` | Excluded: Peter-specific personal operations |
| `ssh-doctor` | Adapted for portable Linux/macOS diagnosis |
| `swift-concurrency-expert` | Conditional on an Apple or Swift repository |
| `swiftui-liquid-glass` | Conditional on an Apple build host |
| `swiftui-performance-audit` | Conditional on an Apple build host |
| `swiftui-view-refactor` | Conditional on a SwiftUI repository |
| `things-todo` | Excluded on this host |
| `twilio-sms` | Excluded: account and channel are not configured |
| `video-transcript-downloader` | Conditional: `yt-dlp` and `ffmpeg` are absent |
| `vm-lab` | Excluded on this host |
| `whatsapp` | Excluded: channel and archive tools are absent |
| `wrangler` | Equivalent when the Cloudflare plugin is active; CLI absent |
| `xcode-sync` | Excluded on this host |
| `xurl` | Excluded: account and executable are absent |
