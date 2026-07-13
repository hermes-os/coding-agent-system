#!/usr/bin/env bash
# Install the canonical agent system into Codex, Claude Code, and Cursor homes.
set -euo pipefail

SYSTEM_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENTS_HOME="${AGENTS_HOME:-$HOME/.agents}"

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
  "$HOME/.codex/prompts" \
  "$HOME/.claude/commands" \
  "$HOME/.claude/skills" \
  "$HOME/.cursor/commands" \
  "$HOME/.local/bin"

link_managed "$SYSTEM_ROOT/AGENTS.md" "$AGENTS_HOME/AGENTS.md"
link_managed "$SYSTEM_ROOT/hooks/dispatch.py" "$AGENTS_HOME/hooks/dispatch.py"
link_managed "$SYSTEM_ROOT/bin/docs-list" "$AGENTS_HOME/bin/docs-list"
link_managed "$SYSTEM_ROOT/bin/agent-system-doctor" "$AGENTS_HOME/bin/agent-system-doctor"
link_managed "$SYSTEM_ROOT/bin/docs-list" "$HOME/.local/bin/docs-list"
link_managed "$SYSTEM_ROOT/bin/docs-list" "$HOME/.local/bin/agent-docs-list"
link_managed "$SYSTEM_ROOT/bin/agent-system-doctor" "$HOME/.local/bin/agent-system-doctor"

for skill in "$SYSTEM_ROOT"/skills/*; do
  [[ -f "$skill/SKILL.md" ]] || continue
  name="$(basename "$skill")"
  link_managed "$skill" "$AGENTS_HOME/skills/$name"
  link_managed "$skill" "$HOME/.claude/skills/$name"
done

link_managed "$SYSTEM_ROOT/AGENTS.md" "$HOME/.codex/AGENTS.md"
link_managed "$SYSTEM_ROOT/AGENTS.md" "$HOME/.claude/CLAUDE.md"
link_managed "$SYSTEM_ROOT/AGENTS.md" "$HOME/.claude/AGENTS.md"

for name in handoff pickup delegate review; do
  source="$SYSTEM_ROOT/skills/$name/SKILL.md"
  link_managed "$source" "$HOME/.codex/prompts/$name.md"
  link_managed "$source" "$HOME/.claude/commands/$name.md"
  install -m 0644 "$source" "$HOME/.cursor/commands/$name.md"
done

python3 "$SYSTEM_ROOT/configure-hosts.py" --system-root "$SYSTEM_ROOT"

if [[ "${AGENT_SYSTEM_PRUNE_LEGACY:-0}" == "1" ]]; then
  legacy_paths=(
    "$HOME/.ai"
    "$HOME/ClaudeVault/personas/Cal"
    "$HOME/.claude/.git"
    "$HOME/.claude/scripts/tc-hook.log"
    "$HOME/.claude/settings.json.orig"
    "$HOME/.codex/CODEX_OPERATING_MANUAL.md"
    "$HOME/.agents/skills/drive"
    "$HOME/.agents/skills/steer"
    "$HOME/.codex/skills/pregen"
    "$HOME/.codex/agents"
    "$HOME/.claude/agents"
    "$HOME/.claude/blueprints"
    "$HOME/.claude/specs"
    "$HOME/.claude/commands/hello-cal.md"
    "$HOME/.claude/hooks/cal-journal-rollup-gate.py"
    "$HOME/.claude/hooks/cal-journal-tick.sh"
    "$HOME/.claude/hooks/codex-session-baseline.sh"
    "$HOME/.claude/hooks/codex-stop-verification.py"
    "$HOME/.claude/plugins/cache/claude-plugins-official/claude-code-setup"
    "$HOME/.claude/plugins/cache/claude-plugins-official/claude-md-management"
    "$HOME/.claude/plugins/cache/claude-plugins-official/code-review"
    "$HOME/.claude/plugins/cache/claude-plugins-official/code-simplifier"
    "$HOME/.claude/plugins/cache/claude-plugins-official/coderabbit"
    "$HOME/.claude/plugins/cache/claude-plugins-official/ralph-loop"
    "$HOME/.claude/plugins/cache/claude-plugins-official/superpowers"
    "$HOME/.claude/plugins/cache/karpathy-skills"
    "$HOME/.codex/plugins/cache/claude-plugins-official/claude-code-setup"
    "$HOME/.codex/plugins/cache/claude-plugins-official/claude-md-management"
    "$HOME/.codex/plugins/cache/claude-plugins-official/code-review"
    "$HOME/.codex/plugins/cache/claude-plugins-official/code-simplifier"
    "$HOME/.codex/plugins/cache/claude-plugins-official/superpowers"
    "$HOME/.codex/plugins/cache/karpathy-skills"
    "$HOME/.codex/plugins/.marketplace-plugin-source-staging"
  )
  for path in "${legacy_paths[@]}"; do
    remove_managed_path "$path"
  done
  for path in "$HOME"/.claude/settings.json.bak.*; do
    remove_managed_path "$path"
  done
  rmdir "$HOME/.claude/scripts" "$HOME/.claude/hooks" 2>/dev/null || true
fi

echo "Agent system installed from $SYSTEM_ROOT"
