---
name: maintain-skills
description: "Audit skill validity, duplicates, metadata budget, hooks, and model-neutrality."
---

# Maintain Skills

Use the deterministic auditor before editing a skill catalog:

```bash
agent-skill-audit --live --codex-visible
```

`--live` scans user-installed and repository roots. Add `--all-caches` only for
storage and duplicate forensics; cache contents are not assumed model-visible.
The Codex probe reads its rendered skill catalog without calling a model.

For a canonical source tree or CI gate:

```bash
agent-skill-audit --root path/to/skills --check --strict --model-neutral
```

## Workflow

1. Read the report's validation errors, context budget, duplicate names/bodies,
   long descriptions, model pins, and hook-manifest findings.
2. Confirm which copy is canonical before changing aliases or duplicates.
3. Keep trigger metadata precise and short. Keep `SKILL.md` procedural and move
   deterministic work or conditional detail into sibling scripts/references.
4. Preserve repo-specific workflows in their owning repository. Shared jobs
   belong globally; host adapters only point to them.
5. Make small grouped changes, run the skill validator and system tests, then
   reinstall and run `agent-system-doctor`.

Do not delete skills from a warning alone. Verify real loading, ownership, and
replacement coverage first. Never add model identities or duplicate policy.
