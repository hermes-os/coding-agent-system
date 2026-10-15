#!/usr/bin/env bash
# Open a herdr tab that shows a repo-worker run live (read-only).
# Usage: worker-pane.sh <runId> <short-label>
# The tab opens in the herdr workspace named after the run's repo (lane clones
# map to their canonical repo), so each repo's space holds its shell and its
# live runs. Unknown repos fall back to a "workers" workspace.
# Prints "<tab_id> <pane_id>".
# WORKER_HOST=<ssh alias> (e.g. air) watches a run on that host: the tab still
# opens in this host's herdr, and the viewer runs there over ssh.
set -euo pipefail
run=$1
label=${2:-${run:0:8}}
# readlink -f: the client path is a symlink into worker-host/bin, where the viewer sits.
viewer=$(dirname "$(readlink -f "$0")")/watch-worker.py
root=/home/hermes/Projects/hermes-os
# ashwren-legacy comes before ashwren so the longer name wins.
repos="ashwren-legacy ashwren coding-agent-system coding-agent-vm-setup hearth hermes-apple-bridge imessage-sidecar inkwell kestrel linq-sidecar marquee marvin-legal-management nomad red-acre rpo-wellness tape-machine"

meta=/var/lib/agent-worker/.local/state/agent-workers/runs/$run/metadata.json
host=${WORKER_HOST:-}
if [ -n "$host" ]; then
  repo_path=$(ssh -o BatchMode=yes "$host" "sudo -n cat $meta" 2>/dev/null \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("repo",""))' 2>/dev/null || true)
else
  repo_path=$(sudo -n python3 -c '
import json,sys
print(json.load(open(sys.argv[1])).get("repo",""))' "$meta" 2>/dev/null || true)
fi
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
tab=$(herdr tab create --workspace "$ws" --label "$label${host:+@$host} ${run:0:8}" --cwd "$cwd" --no-focus)
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
if [ -n "$host" ]; then
  herdr pane run "$pane" "ssh -t $host sudo -n python3 $viewer $run" >/dev/null
else
  herdr pane run "$pane" "sudo -n python3 $viewer $run" >/dev/null
fi
echo "$tab_id $pane"
