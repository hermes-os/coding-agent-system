#!/usr/bin/env bash
# Install the canonical agent system into Codex, Claude Code, and Cursor homes.
set -euo pipefail

SYSTEM_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENTS_HOME="${AGENTS_HOME:-$HOME/.agents}"
COORDINATION_REPO="${AGENT_COORDINATION_REPO_DIR:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --coordination-repo)
      [[ $# -ge 2 ]] || { echo "Error: --coordination-repo requires a path." >&2; exit 2; }
      COORDINATION_REPO=$2
      shift 2
      ;;
    *)
      printf 'Error: unknown argument: %s\n' "$1" >&2
      exit 2
      ;;
  esac
done

catalog_rows() {
  local section=$1
  python3 - "$SYSTEM_ROOT/system.json" "$section" <<'PY'
import json
from pathlib import Path
import sys

catalog = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if sys.argv[2] == "skills":
    for skill in catalog["skills"]:
        print(f'{skill["name"]}\t{int(skill["command"])}')
elif sys.argv[2] == "binaries":
    for binary in catalog["binaries"]:
        print(f'{binary["name"]}\t{binary["source"]}')
else:
    raise SystemExit(f"unknown catalog section: {sys.argv[2]}")
PY
}

remove_managed_path() {
  local path=$1
  if [[ -L "$path" || -f "$path" ]]; then
    rm -f "$path"
  elif [[ -d "$path" ]]; then
    rm -rf "$path"
  fi
}

link_managed() {
  local target=$1 link=$2
  if [[ -L "$link" && "$(readlink "$link")" == "$target" ]]; then
    return 0
  fi
  mkdir -p "$(dirname "$link")"
  remove_managed_path "$link"
  ln -s "$target" "$link"
  printf 'linked %s -> %s\n' "$link" "$target"
}

mkdir -p \
  "$AGENTS_HOME/skills" \
  "$AGENTS_HOME/hooks" \
  "$AGENTS_HOME/bin" \
  "$AGENTS_HOME/shell" \
  "$HOME/.codex/prompts" \
  "$HOME/.claude/commands" \
  "$HOME/.claude/skills" \
  "$HOME/.cursor/commands" \
  "$HOME/.local/bin"

link_managed "$SYSTEM_ROOT/AGENTS.md" "$AGENTS_HOME/AGENTS.md"
link_managed "$SYSTEM_ROOT/hooks/dispatch.py" "$AGENTS_HOME/hooks/dispatch.py"
link_managed "$SYSTEM_ROOT/shell/default-invocations.sh" "$AGENTS_HOME/shell/default-invocations.sh"

while IFS=$'\t' read -r name source; do
  link_managed "$SYSTEM_ROOT/$source" "$AGENTS_HOME/bin/$name"
  link_managed "$SYSTEM_ROOT/$source" "$HOME/.local/bin/$name"
done < <(catalog_rows binaries)

while IFS=$'\t' read -r name is_command; do
  skill="$SYSTEM_ROOT/skills/$name"
  [[ -f "$skill/SKILL.md" ]] || { printf 'Missing catalog skill: %s\n' "$name" >&2; exit 1; }
  link_managed "$skill" "$AGENTS_HOME/skills/$name"
  link_managed "$skill" "$HOME/.claude/skills/$name"
  if [[ "$is_command" == "1" ]]; then
    source="$skill/SKILL.md"
    link_managed "$source" "$HOME/.codex/prompts/$name.md"
    link_managed "$source" "$HOME/.claude/commands/$name.md"
    install -m 0644 "$source" "$HOME/.cursor/commands/$name.md"
  fi
done < <(catalog_rows skills)

link_managed "$SYSTEM_ROOT/AGENTS.md" "$HOME/.codex/AGENTS.md"
link_managed "$SYSTEM_ROOT/AGENTS.md" "$HOME/.claude/CLAUDE.md"
link_managed "$SYSTEM_ROOT/AGENTS.md" "$HOME/.claude/AGENTS.md"

configure_args=(--system-root "$SYSTEM_ROOT")
if [[ -n "$COORDINATION_REPO" ]]; then
  configure_args+=(--coordination-repo "$COORDINATION_REPO")
fi
python3 "$SYSTEM_ROOT/configure-hosts.py" "${configure_args[@]}"

echo "Agent system installed from $SYSTEM_ROOT"
