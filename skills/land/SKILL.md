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
5. In orchestrated or potentially concurrent work, acquire the repository lease
   through `portfolio` and verify the reviewed exact head. Branch drift
   invalidates admission and requires synchronization and review.
6. Immediately before a push, status, merge, or other provider write, acquire
   the public lease and reverify the exact head. Perform one synchronous write,
   verify its response, and release the public lease immediately.
7. Observe required CI and normal deployment or publication without holding the
   public lease. Reacquire and reverify it for each later provider write. Run the
   narrowest useful live smoke when applicable.
8. Release the repository lease when ownership ends, return to the expected
   branch and state, and report commit, remote, checks, deployment, and risk.

Never include unrelated files, secrets, generated credentials, or unverified
claims. Stop only for a real conflict, failed proof, or an irreversible effect
outside the user's stated delivery scope.
