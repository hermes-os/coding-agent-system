#!/usr/bin/env bash
# Queue repo-worker runs behind a running one: wait for <run-id>, then launch each
# spec in order, waiting for each to finish before the next (the broker allows one
# run per repo path, so writer -> reviewer -> fix -> reviewer on one repo is serial).
# A run that ends status=failed (provider stream fault, e.g. after a 429) is
# relaunched with the same spec, up to 8 times with growing sleeps; Hermes keeps
# his chosen model rather than downgrading. blocked/completed runs are not retried:
# read their output yourself.
# Run it with terminal(background=true, notify=true); the exit is the wake-up.
# To change a queued step (model, effort, cancel), kill this chain process only:
# the running worker is a system service and is not touched. Relaunch the chain
# with the new specs, waiting on the same run id.
#
# usage: chain-workers.sh <wait-run-id> "<repo>|<model>|<effort>|<read|write>|<packet-file>" ...
#   packet-file is relative to $PACKETS (default /home/hermes/Projects/cal-task-packets)
# Env: REPO_WORKER_MAX_ACTIVE (passed through; set only when Hermes raised it).
W=/home/hermes/.hermes/profiles/cal/workspace
# readlink -f: the client path is a symlink into worker-host/bin, where its siblings sit.
BIN=$(dirname "$(readlink -f "$0")")
WAIT=$BIN/wait-for-workers.sh
PACKETS=${PACKETS:-/home/hermes/Projects/cal-task-packets}
cd "$W" || exit 1
prev=$1; shift
"$WAIT" "$prev"
for spec in "$@"; do
  IFS='|' read -r repo model effort access packet <<<"$spec"
  for attempt in 1 2 3 4 5 6 7 8; do
    for try in 1 2 3 4 5 6; do
      out=$(scripts/repo-worker --agent hermes --model "$model" --effort "$effort" --access "$access" \
        --mode task --repo "$repo" --role worker --task-file "$PACKETS/$packet" 2>&1)
      id=$(echo "$out" | grep -oE '"runId": *"[^"]*"' | head -1 | cut -d'"' -f4)
      [ -n "$id" ] && break
      sleep 60   # slot or repo lease not free yet
    done
    echo "LAUNCHED $packet (attempt $attempt) -> ${id:-FAILED: $(echo "$out" | tail -1)}"
    [ -z "$id" ] && exit 1
    # Every run gets a watch pane, chained ones too (Hermes watches all runs).
    env -u WORKER_HOST "$BIN/worker-pane.sh" "$id" "${packet%.md}" || echo "PANE FAILED for $id"
    res=$("$WAIT" "$id"); echo "$res"
    echo "$res" | grep -q "status=failed" || break
    sleep $((attempt * 90))
  done
  prev=$id
done
