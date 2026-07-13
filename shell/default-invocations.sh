# Standard interactive launch behavior installed by the global agent system.
# Set AGENT_REMOTE_CONTROL=0 for a one-command opt-out.
claude() {
  "$HOME/.agents/bin/agent-claude" "$@"
}

codex() {
  "$HOME/.agents/bin/agent-codex" "$@"
}
