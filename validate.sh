#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$ROOT/.." && pwd)"

bash -n \
  "$ROOT/install.sh" \
  "$ROOT/bin/committer" \
  "$ROOT/bin/agent-claude" \
  "$ROOT/bin/agent-codex" \
  "$ROOT/shell/default-invocations.sh" \
  "$REPO_ROOT/bootstrap.sh" \
  "$REPO_ROOT"/claude-code/*.sh \
  "$REPO_ROOT"/codex/*.sh \
  "$REPO_ROOT"/lib/*.sh
while IFS= read -r -d '' script; do
  python3 -m py_compile "$script"
done < <(find "$ROOT" -type f -name '*.py' -print0)
"$ROOT/skills/maintain-skills/scripts/skill-audit.py" \
  --root "$ROOT/skills" \
  --check \
  --strict \
  --model-neutral
python3 -m unittest discover -s "$ROOT/tests" -p 'test_*.py'

echo "Agent system validation passed."
