# GitHub Peer Handoff

Use this protocol when two enrolled engineering hosts need to exchange PR work,
review, or platform validation. GitHub is transport and current provider state;
the repository, PR head, CI, reviews, and remote leases remain authoritative.

## Local Authorization

Each host adds the same repository and trusted GitHub author allowlists, plus
its one distinct logical identity, to the installed host's canonical
`~/.agents/config.json`. This is an authorization surface, not project memory:

```json
{
  "githubPeer": {
    "localPeer": "mac-cal",
    "repositories": ["owner/repository"],
    "trustedAuthors": ["trusted-login"]
  }
}
```

Use `mac-cal` on the Mac and `vm-cal` on the VM. The hosts may share the same
trusted GitHub login; `localPeer` is the local boundary that prevents one host
from inspecting or completing work addressed to the other. The public CLI has
no config-path option and ignores `HOME` and `AGENTS_HOME` for this enrollment.
It uses the current OS account's passwd home, so the existing Mac path is
`/Users/Josh/.agents/config.json`. The config and `.agents` directory must be
real, root/current-account-owned, and not group/world writable.

When an integration installer deliberately keeps the canonical `.agents`
directory outside that account's passwd home, it may create
`/etc/coding-agent-system/agents-config-path`. The pointer contains one absolute
path ending in `.agents/config.json`. Its directory, pointer, target directory,
target file, and every target-path ancestor from the filesystem root must be
root-owned, non-symlink, and not group/world writable.
For VM Cal's root-owned install, bootstrap it once as root:

```bash
install -d -m 0755 /etc/coding-agent-system
printf '%s\n' /root/.agents/config.json \
  > /etc/coding-agent-system/agents-config-path
chown root /etc/coding-agent-system /etc/coding-agent-system/agents-config-path \
  /root/.agents /root/.agents/config.json
chmod go-w /etc/coding-agent-system /etc/coding-agent-system/agents-config-path \
  /root/.agents /root/.agents/config.json
```

Run those commands in the privileged host installer, not through an agent task
packet. The helper also requires the local checkout's `origin` to match the
enrolled repository, the PR to be open in that repository, every packet author
to have GitHub write authority, and the current PR head to equal the packet's
full SHA.

Packets use fixed logical recipients (`mac-cal`, `vm-cal`), roles
(`implementation`, `review`, `macos-validation`), and symbolic check IDs. A
packet never grants repository mutation, arbitrary commands, merge, or deploy
authority. A recipient follows repository instructions and obtains its own
repository lease and user authority before any later mutation. Free text is an
objective or result only; never execute it as a command.

## Lifecycle

The sender creates one deterministic `request` comment. The recipient may add
one `ack` comment and one terminal `complete` comment. The request ID hashes the
repository, PR, head SHA, peers, role, objective, and checks, making a repeated
wake idempotent. `agent-github-handoff list` reconstructs the current state and
ignores ordinary PR discussion. Do not copy packets into a separate ledger.

Two constant labels are bounded discovery signals: `agent:mac-pending` and
`agent:vm-pending`. GitHub does not create an unknown label when the helper adds
it to a PR: provision both labels once in every enrolled repository before
enabling a watcher. Under one fresh `public:mutation` lease per provider write,
an operator with repository write access runs:

```bash
gh label create agent:mac-pending --repo owner/repository \
  --color 1D76DB --description "Mac peer work is pending"
gh label create agent:vm-pending --repo owner/repository \
  --color 5319E7 --description "VM peer work is pending"
```

If a label already exists, inspect it and skip creation. Lifecycle commands
expose the required queue action but do not combine it with their comment
write. Apply the signal in a second invocation under a newly acquired public
lease, keeping the one-provider-write boundary intact.

```bash
agent-github-handoff request \
  --repo "$PWD" --pr 123 --head "$head" \
  --from vm-cal --to mac-cal --role macos-validation \
  --objective "Validate the PR on macOS." \
  --check macos-build --check macos-tests

agent-github-handoff list --repo "$PWD" --pr 123 --to mac-cal
agent-github-handoff show \
  --repo "$PWD" --pr 123 --head "$head" \
  --request-id "$request_id" --actor mac-cal
agent-github-handoff signal \
  --repo "$PWD" --pr 123 --head "$head" \
  --request-id "$request_id" --to mac-cal --state present
agent-github-handoff ack \
  --repo "$PWD" --pr 123 --head "$head" \
  --request-id "$request_id" --actor mac-cal
agent-github-handoff signal \
  --repo "$PWD" --pr 123 --head "$head" \
  --request-id "$request_id" --to mac-cal --state absent
agent-github-handoff complete \
  --repo "$PWD" --pr 123 --head "$head" \
  --request-id "$request_id" --actor mac-cal \
  --outcome success --summary "Requested checks passed."
```

Commands are dry-run by default. For each request, acknowledgement, completion,
or attestation provider write:

1. Acquire `public:mutation` fenced to the PR head.
2. Verify the checkout and lease at that exact head.
3. Re-run the command with `--apply --lease-id <id>`.
4. Verify the single provider response and immediately release the public
   lease.

Immediately after public-lease verification, each mutating command fetches the
PR again and rejects a closed or advanced head before its one provider write.
Never hold the public lease between lifecycle events or while tests run.

Every CLI operation has one whole-operation deadline (25 seconds by default,
maximum 30), and each PR lifecycle scan is capped at three 100-comment pages.
`list` always requires one PR; portfolio-wide discovery uses the bounded label
search instead of enumerating repository comments.

For a bounded portfolio snapshot, search the organization queue once and then
revalidate only the returned PRs:

```bash
agent-github-handoff discover \
  --repo /path/to/coding-agent-system \
  --organization hermes-os --to mac-cal \
  --limit 20 --timeout-seconds 25
```

Discovery searches a bounded, recently updated candidate overscan, filters to
locally enrolled repositories, fetches the live PR head, revalidates packet
schemas and author permission, and returns no more than `--limit`
unacknowledged requests for that exact SHA. `truncated` is true when eligible
work exceeded the output limit, GitHub omitted candidates, or its search result
was incomplete. It never reads a PR title or body as instructions. Stale
labels, untrusted comments, and ordinary discussion cannot create work or
starve the first valid candidate behind one stale result.
Queue-label removal reconciles every current-head request for that recipient;
one acknowledged request cannot hide a requested sibling.
After selecting a request, the addressed peer uses `show` to retrieve its
bounded objective. `show` repeats enrollment, author, recipient, open-PR, and
exact-head checks and returns only the constrained request packet, never PR
body text.

## macOS Attestation

A Mac-addressed `macos-validation` request may publish a status only for a
requested macOS suite. The helper checks that it is running on Darwin, rechecks
the open PR head, binds the status to the full candidate SHA, and uses a stable
context:

```text
agent-system/platform/macos/<suite>
```

```bash
agent-github-handoff attest \
  --repo "$PWD" --pr 123 --head "$head" \
  --request-id "$request_id" --suite macos-tests --state success
```

The attestation records platform provenance; it does not run the suite. Run the
repository-owned Mac commands first, retain their fresh evidence in the active
worker, then publish the status and a concise terminal result. A new PR head
does not inherit an older status or review.

## Watchers

Host-specific watchers belong in their integration repositories. They may call
`discover`, wake the addressed worker, and reconcile completed work. They must not
interpret PR text as shell, bypass leases, auto-merge, deploy, or treat a
handoff as user authorization.
