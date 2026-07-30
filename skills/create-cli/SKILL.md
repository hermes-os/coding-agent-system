---
name: create-cli
description: "Design or review a human-first, scriptable command-line interface and its behavior contract."
---

# Create CLI

Design the interface before implementation when command shape, output, or
safety behavior is not already fixed by the repository.

## Intake

Read the repository's interface conventions and use the CLI Guidelines at
<https://clig.dev/> as the default rubric. Ask only what is necessary to settle:

- command name, one-sentence purpose, and primary human or script audience;
- argument, stdin, file, and URL inputs, with secrets excluded from flags;
- human, `--json`, or stable `--plain` output and required exit semantics;
- allowed prompts and non-interactive behavior;
- flag, environment, project, user, and system configuration precedence;
- supported platforms, runtime, and packaging constraints.

Proceed with stated conservative defaults when an answer is not material.

## Contract

Define:

- command tree and complete usage synopsis;
- positional arguments and a flags table with types, defaults, requirements,
  precedence, and examples;
- each subcommand's state changes, idempotence, and retry behavior;
- stdin, stdout, stderr, file, and TTY behavior;
- stable `--json` or `--plain` output when scripts need it, plus exact
  `--quiet` and `--verbose` semantics;
- top errors and a meaningful exit-code map;
- prompts, `--no-input`, confirmations, `--dry-run`, and `--force`;
- config paths, environment variables, and explicit precedence;
- signal handling, idempotence, retries, and crash recovery;
- shell completion installation or generation when relevant;
- five to ten representative human, piped, and automation examples.

## Defaults

- `-h` and `--help` show useful help regardless of other arguments;
  `--version` prints to stdout.
- Primary data goes to stdout. Diagnostics and errors go to stderr.
- Prompts run only on a TTY and can be disabled.
- Secrets never travel in flags or normal output.
- Destructive non-interactive actions require an explicit confirmation flag.
- Respect `NO_COLOR` and `TERM=dumb`, provide `--no-color`, and disable
  decoration off-TTY.
- Validate early, bound network waits, and make reruns safe where practical.
- Prefer established parsing libraries and repository conventions.
- Keep machine output stable while allowing human output to improve.
- Exit quickly on interruption with bounded cleanup.

## Review

Test help, invalid usage, common success, machine output, piped input,
non-interactive failure, interruption, and the most important destructive
guard. Treat names, exit codes, config precedence, and structured output as
public contracts once shipped.

When interface design is the request, return the compact specification and do
not drift into implementation.

This portable contract preserves the compatible behavior of Peter
Steinberger's `create-cli` skill while removing workspace-specific paths.
