#!/usr/bin/env bash
# Install the canonical agent system into Codex, Claude Code, and Cursor homes.
set -euo pipefail

SYSTEM_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COORDINATION_REPO="${AGENT_COORDINATION_REPO_DIR:-}"
HOST_INTEGRATION="${AGENT_HOST_INTEGRATION_DIR:-$SYSTEM_ROOT/host/local}"
MIGRATE_FROM_SYSTEM_ROOT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --coordination-repo)
      [[ $# -ge 2 ]] || { echo "Error: --coordination-repo requires a path." >&2; exit 2; }
      COORDINATION_REPO=$2
      shift 2
      ;;
    --host-integration)
      [[ $# -ge 2 ]] || { echo "Error: --host-integration requires a path." >&2; exit 2; }
      HOST_INTEGRATION=$2
      shift 2
      ;;
    --migrate-from-system-root)
      [[ $# -ge 2 ]] || { echo "Error: --migrate-from-system-root requires a path." >&2; exit 2; }
      MIGRATE_FROM_SYSTEM_ROOT=$2
      shift 2
      ;;
    *)
      printf 'Error: unknown argument: %s\n' "$1" >&2
      exit 2
      ;;
  esac
done

configure_args=(--system-root "$SYSTEM_ROOT" --host-integration "$HOST_INTEGRATION")
if [[ -n "$COORDINATION_REPO" ]]; then
  configure_args+=(--coordination-repo "$COORDINATION_REPO")
fi
if [[ -n "$MIGRATE_FROM_SYSTEM_ROOT" ]]; then
  configure_args+=(--migrate-from-system-root "$MIGRATE_FROM_SYSTEM_ROOT")
fi
python3 "$SYSTEM_ROOT/configure-hosts.py" "${configure_args[@]}"

echo "Agent system installed from $SYSTEM_ROOT"
