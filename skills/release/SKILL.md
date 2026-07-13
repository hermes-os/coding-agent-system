---
name: release
description: "Prepare, publish, and verify a repository-native software release."
---

# Release

A release request authorizes the repository's documented release sequence.
Discover the project's real process instead of assuming a package manager,
hosting provider, version scheme, or artifact format.

## Workflow

1. Read release documentation, package metadata, recent tags/releases,
   changelog convention, CI state, credentials boundary, and rollback path.
2. Define the release version, included commits, expected artifacts, target
   channels, and observable post-release checks. Resolve genuine ambiguity once.
3. Update version and release notes only where the project requires them.
   Preserve contributor credit and generated-file conventions.
4. Run the complete release gate and build artifacts from the exact candidate
   commit. Verify signatures, checksums, or provenance when the project uses
   them.
5. Use `land` for required commits and pushes, then publish through the
   repository's canonical tooling. Never expose credentials in output or logs.
6. Verify tags, package or artifact availability, release metadata, CI, and a
   representative install or live smoke. Report propagation delays honestly.
7. Leave the checkout in its expected post-release state and record durable
   release facts only in canonical changelog or release documentation.

Do not silently broaden a release into migrations, destructive cleanup, or
unrelated provider changes.
