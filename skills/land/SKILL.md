---
name: land
description: "Verify and complete an authorized commit, push, merge, ship, or deployment sequence."
---

# Land

Treat explicit delivery language as authorization for the complete matching
sequence. Follow the repository's direct-push, branch, pull-request, deployment,
and changelog conventions without asking for the same approval again.

## Workflow

1. Inspect branch, upstream, working tree, unpushed commits, review state, and
   concurrent changes. Identify the exact files owned by this change.
2. Review the final diff and run fresh focused checks plus the required gate.
   Do not land known failures or present old evidence as current.
3. Commit only intended paths. Prefer `committer "<message>" <path>...` when
   available; it leaves unrelated staged work intact. Use the repository's
   commit style.
4. Synchronize without discarding work. Fast-forward clean branches; rebase,
   merge, or force-with-lease only when the repository convention and stated
   scope require it.
5. Push the intended branch. Merge a pull request only when that is the chosen
   repository path, and verify the remote state rather than assuming success.
6. Observe required CI and normal deployment or publication triggered by the
   authorized action. Run the narrowest useful live smoke when applicable.
7. Return to the repository's expected branch/state and report commit, remote,
   checks, deployment, and residual risk.

Never include unrelated files, secrets, generated credentials, or unverified
claims. Stop only for a real conflict, failed proof, or an irreversible effect
outside the user's stated delivery scope.
