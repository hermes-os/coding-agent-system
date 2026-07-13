---
name: capabilities
description: "Inventory installed tools, host adapters, and scoped skills for task routing."
---

# Capabilities

Generate the current host inventory on demand:

```bash
agent-capabilities --repo "$PWD"
```

Use `--json` for machine-readable routing. The helper reports executable paths,
host adapter presence, and skill names; it never reads or prints environment
values, credentials, or secret files.

Choose the smallest relevant tool and skill set from the live result. Verify a
tool's own help or current primary documentation before relying on unstable
flags or provider behavior. Do not persist a static `tools.md`; rerun the
inventory when the host changes.
