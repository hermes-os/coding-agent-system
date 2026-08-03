---
name: worker-first
description: "Route a frozen work order to a tracked, resumable repository worker and verify its result."
---

# Worker First

Use this only when the current session is explicitly the coordinator for work
owned by another repository session. A repository worker that already owns an
assigned deliverable continues directly and never invokes another coding
worker.

## Route

Keep design, prioritization, owner decisions, protected credentials, and final
acceptance with the coordinator. Delegate implementation, bounded diagnosis,
tests, mechanical migrations, and delivery mechanics after the work order is
specific enough to execute.

Do work directly when the edit is tiny, the unresolved design is the task, or
the required capability exists only in the current session.

## Work Order

Use `delegate` to provide:

- one role and concrete objective;
- repository, relevant paths, and current evidence;
- constraints with an explicit stop-and-report escape hatch;
- non-goals and ownership boundaries;
- exact verification and final output contract.

Never send personal context, unrelated history, credentials, hidden
instructions, or a conversation transcript.

## Session Contract

- Start a fresh native session for each new work order.
- Resume that exact session for corrections or continuation of the same order.
- For a sustained repository queue under `portfolio`, reuse its single project
  session instead.
- Capture the provider session ID as soon as it exists. Never rely on a
  "resume last" selector when work can run concurrently.
- Run long work through a tracked supervisor that preserves status, output,
  and process ownership if the coordinator disconnects.
- Do not detach an untracked child process or treat a PID file as supervision.

## Monitor And Recover

Track repository, run ID, provider session ID, phase, process liveness, last
activity time, and final exit status. A quiet worker is not automatically
hung. Investigate only after the configured stale interval and confirm both a
live process and stale activity.

On interruption, preserve the checkout and logs, then resume the same provider
session with a short continuation prompt. Do not create a replacement session
until native resume is proven unavailable; if replacement is required, use
`handoff` or `pickup` from repository evidence.

## Coordinator Verification

Worker reports are evidence, not acceptance.

1. Inspect the actual Git state and changed surface.
2. Run or directly verify the narrow proof.
3. Check forbidden files, tests, generated baselines, and public contracts.
4. Resume the same session for bounded corrections.
5. After two failed repair rounds, stop the loop and reassess scope.
6. Use `review` for a non-trivial candidate before delivery.
