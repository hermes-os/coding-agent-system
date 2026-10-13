#!/usr/bin/env bash
# Open a herdr tab that shows a repo-worker run live (read-only).
# Usage: worker-pane.sh <runId> <short-label>
# The tab opens in the herdr workspace named after the run's repo (lane clones
# map to their canonical repo), so each repo's space holds its shell and its
# live runs. Unknown repos fall back to a "workers" workspace.
# Prints "<tab_id> <pane_id>".
set -euo pipefail
run=$1
label=${2:-${run:0:8}}
viewer=/home/hermes/.hermes/profiles/foreman/scripts/watch-worker.py
root=/home/hermes/Projects/hermes-os
# ashwren-legacy comes before ashwren so the longer name wins.
repos="ashwren-legacy ashwren coding-agent-system coding-agent-vm-setup hearth hermes-apple-bridge imessage-sidecar inkwell kestrel linq-sidecar marquee marvin-legal-management nomad rpo-wellness tape-machine"

repo_path=$(sudo -n python3 -c '
import json,sys
print(json.load(open(sys.argv[1])).get("repo",""))' \
  "/var/lib/agent-worker/.local/state/agent-workers/runs/$run/metadata.json" 2>/dev/null || true)
base=$(basename "${repo_path:-none}")
name=workers
for r in $repos; do
  case "$base" in "$r"|"$r"-*) name=$r; break ;; esac
done
cwd=$root/$name; [ -d "$cwd" ] || cwd=$root

ws=$(herdr workspace list | python3 -c '
import json,sys
for w in json.load(sys.stdin)["result"]["workspaces"]:
    if w.get("label") == sys.argv[1]: print(w["workspace_id"]); break' "$name")
if [ -z "$ws" ]; then
  ws=$(herdr workspace create --label "$name" --cwd "$cwd" --no-focus \
    | python3 -c 'import json,sys; r=json.load(sys.stdin)["result"]; print((r.get("workspace") or r)["workspace_id"])')
fi
tab=$(herdr tab create --workspace "$ws" --label "$label ${run:0:8}" --cwd "$cwd" --no-focus)
pane=$(printf '%s' "$tab" | python3 -c '
import json,sys
r=json.load(sys.stdin)["result"]
def find(o):
    if isinstance(o,dict):
        if "pane_id" in o: return o["pane_id"]
        for v in o.values():
            p=find(v)
            if p: return p
    if isinstance(o,list):
        for v in o:
            p=find(v)
            if p: return p
print(find(r) or "")')
tab_id=$(printf '%s' "$tab" | python3 -c '
import json,sys
r=json.load(sys.stdin)["result"]
print((r.get("tab") or r).get("tab_id",""))')
herdr pane run "$pane" "sudo -n python3 $viewer $run" >/dev/null
echo "$tab_id $pane"
