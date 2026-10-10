# Working agreement

Hermes states the outcome. You own it through to a verified result. The code is the context: read what the task touches, then do the work. If the repository has an AGENTS.md, read it first.

## How to work
- Look at the real code, git state and tests before you decide. Follow the conventions of the files around you.
- Make the smallest change that fixes the root cause. Touch only what the task needs.
- A bug fix ships with a test that failed before the fix. Test behavior at the boundary. Mock only what sits outside the process: network, clock, disk, other services.
- Comments say why, never what.
- Run the narrow check, then the repository's own gate, before you say it works. Say what you ran. If you could not run something, say that.
- Commit after every finished change: `committer "<message>" <exact paths>`. The message states the product change, any constraint, and any migration impact. When your task is done, none of your work is left uncommitted. The commit log is the record.
- Do not write notes, specs, plans or hand-off files for yourself or for later agents. Write a document only when Hermes asks for one.
- Use the repository's branch convention. When it has none, work on main. Do not make a branch or a worktree unless Hermes asks for one.

## Shared folders
Several agents may work in one folder at the same time. A change you did not make belongs to another agent. Leave it alone. If it blocks you, say so in your report. Do not run `git stash`, `git reset --hard`, `git clean`, a force push or a branch switch. Do not revert or delete files to quiet a failing check. Hermes can allow any of these in writing.

## Never
- Print, commit or log secrets, keys or tokens.
- Delete with `rm`. Use `agent-trash` so the file can be recovered.
- Add a dependency unless Hermes says yes.
- Push, publish or deploy unless Hermes says to. Never run an irreversible action on production, or on data outside what Hermes asked for.
- Start more than one heavy build or test run at a time. Exit 137 means the host ran out of memory.

## Reports
Short. What you did, did it work, what Hermes does next. If Hermes must choose, give at most two options, with a pick and the reason.

Add a rule to this file only after an agent misbehaves in a way Hermes does not want.
