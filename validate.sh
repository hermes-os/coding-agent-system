#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONDONTWRITEBYTECODE=1

bash -n \
  "$ROOT/install.sh" \
  "$ROOT/bin/committer" \
  "$ROOT/host/local/bin/agent-claude" \
  "$ROOT/host/local/bin/agent-codex" \
  "$ROOT/host/local/shell/default-invocations.sh"
while IFS= read -r -d '' script; do
  python3 - "$script" <<'PY'
import ast
from pathlib import Path
import sys

path = Path(sys.argv[1])
ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
PY
done < <(find "$ROOT" -type f -name '*.py' -print0)
for script in \
  "$ROOT/bin/agent-repo-adopt" \
  "$ROOT/bin/agent-repo-check" \
  "$ROOT/bin/agent-system-doctor" \
  "$ROOT/bin/agent-trash" \
  "$ROOT/bin/docs-list"; do
  python3 - "$script" <<'PY'
import ast
from pathlib import Path
import sys

path = Path(sys.argv[1])
ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
PY
done
"$ROOT/skills/maintain-skills/scripts/skill-audit.py" \
  --root "$ROOT/skills" \
  --check \
  --strict \
  --model-neutral
"$ROOT/bin/agent-repo-check" --repo "$ROOT" --strict
python3 -m unittest discover -s "$ROOT/tests" -p 'test_*.py'
git -C "$ROOT" diff --check

echo "Agent system validation passed."
