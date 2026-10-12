---
name: land
description: "Push and deploy reviewed commits through the repository's own delivery path."
---

# Land

The coordinator lands work; repository workers never push, publish, or deploy.
Land only commits a fresh reviewer approved (`VERDICT: APPROVE`) for the exact
range being pushed. Follow the repository's direct-push, branch, deployment,
and changelog conventions without asking for the same approval again.

## Workflow

1. Inspect branch, upstream, working tree, unpushed commits, and concurrent
   changes. Confirm the approved review covers every commit about to be pushed;
   a commit after the reviewed head needs its own review first.
2. Run `agent-repo-check --repo "$PWD"` when available, then fresh focused
   checks plus the required gate. Do not land known failures or present old
   evidence as current.
3. Commit anything left only through `committer "<message>" <path>...`, and
   then review it before pushing.
4. Synchronize without discarding work. Fast-forward clean branches; rebase or
   merge only when the repository convention requires it. Rebased commits need
   their range checked again.
5. Push, then observe required CI.
6. Deploy through the repository's release path, dry run first where it has
   one. When deploying, turn the `CHANGELOG.md` `## Unreleased` section into the
   release heading the file's format uses. Run the narrowest useful live smoke.
7. Return to the expected branch and state, and report commit range, remote,
   checks, deployment, and risk.

Never include unrelated files, secrets, generated credentials, or unverified
claims. Stop only for a real conflict, failed proof, or an irreversible effect
outside the owner's stated delivery scope.
