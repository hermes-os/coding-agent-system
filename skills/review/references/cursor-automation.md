# Cursor Autoreview Automation

Use two thin Cursor Automations. The canonical `review` skill and
`agent-autoreview` helper own behavior; automation only supplies triggers.

## Change Review

Trigger on pull-request open/update and every push to the default branch.
Attach the target repository and use this instruction:

```text
Run the global review job for the exact GitHub event candidate. Read the global
policy and review skill only. Do not use or write Cursor Memories.

Resolve the event base and head SHAs, check out the exact head cleanly, and run
agent-autoreview prepare with the event's requested outcome. If
agent-autoreview status already matches this fingerprint, stop successfully.
Review only the frozen bundle, write result.json from its template, and run the
validator. Do not edit source, open a repair PR, merge, deploy, or publish.

To publish the idempotent commit status, acquire public:mutation with agent-lease,
verify the exact head, run agent-autoreview publish, and release the lease. A
findings verdict is a successful automation run with a failing review status;
report the structured findings for a separately assigned fix-issue job.
```

## Reconciliation

Run nightly. Inspect recent default-branch commits and open PR heads, then run
the same workflow only when the exact candidate lacks the autoreview status.
Process candidates serially. Do not perform broad repository review, repairs,
or queue maintenance in this automation.

Leave reviewer selection in Cursor's automation settings. The skill, prompt,
schema, and acceptance rules contain no reviewer identity.
