#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bash -n "$ROOT/install.sh"
python3 -m py_compile \
  "$ROOT/configure-hosts.py" \
  "$ROOT/hooks/dispatch.py" \
  "$ROOT/bin/docs-list"
python3 -m unittest discover -s "$ROOT/tests" -p 'test_*.py'

echo "Agent system validation passed."
