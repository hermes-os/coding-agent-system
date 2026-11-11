---
name: land
description: "Bring finished commits to origin: gate, synchronize, push, and watch CI."
---

# Land

Finished work is pushed to `origin` once its gate passes. `origin` is Hermes's
own Git server; it mirrors each push to GitHub by itself. The same steps land a
worker's branch after its kanban card is done: read the diff, merge it into the
main line, then continue from step 2.

## Workflow

1. Inspect the branch, its upstream, the working tree, the unpushed commits,
   and changes that are not yours. Leave those alone.
2. Run the repository's gate now. Do not land a known failure or present old
   evidence as current.
3. Commit anything left with `committer "<message>" <path>...`. A user-visible
   change carries its `CHANGELOG.md` line in the same commit.
4. Synchronize without discarding work. Fast-forward a clean branch; rebase or
   merge only when the repository's convention asks for it, and run the gate
   again afterwards.
5. Push, then watch the CI the repository requires.
6. Report the commit range, the remote, the checks, and any risk that remains.

## Deploying

A deploy reaches real people, so it needs Hermes's word for this change or a
repository `AGENTS.md` that says pushes deploy. Then use the repository's own
release path, dry run first where it has one, and run the narrowest useful live
smoke. When the landing is a release, turn the `CHANGELOG.md` `## Unreleased`
section into the heading the file's format uses (none yet: `## YYYY-MM-DD`) and
push that commit with the rest.

Never include unrelated files, secrets, or unverified claims.
