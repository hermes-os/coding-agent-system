#!/usr/bin/env bash
# Block until any named repo-worker run reaches a terminal state, or its log
# goes quiet long enough to call it stalled. Run under a notifying background
# process so Cal gets a turn the moment a worker needs the next step.
# Usage: wait-for-workers.sh <run-id>... (full or unique-prefix ids)
set -u
RUNS=/var/lib/agent-worker/.local/state/agent-workers/runs
WORKER_HOMES=/var/lib/agent-worker/.hermes-worker
STALL_SECONDS=${STALL_SECONDS:-2700}
POLL_SECONDS=${POLL_SECONDS:-60}

[ $# -gt 0 ] || { echo "usage: wait-for-workers.sh <run-id>..." >&2; exit 2; }

dirs=()
for id in "$@"; do
  match=("$RUNS"/"$id"*/)
  [ -d "${match[0]}" ] || { echo "no run matches $id" >&2; exit 2; }
  dirs+=("${match[0]%/}")
done

while :; do
  for d in "${dirs[@]}"; do
    id=$(basename "$d")
    status=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("status","unknown"))' "$d/metadata.json" 2>/dev/null || echo unknown)
    case "$status" in
      completed|failed|stopped|dead|blocked|unverified)
        echo "WORKER FINISHED: $id status=$status"
        # Owner's reboot hold: the dispatching session reads this line and must not launch the next worker.
        [ -e /home/hermes/.hermes/profiles/cal/state/HOLD-FOR-REBOOT ] && \
          echo "HOLD FOR REBOOT IS ON: do not launch new workers or dispatches. Read the file state/HOLD-FOR-REBOOT."
        exit 0 ;;
    esac
    # Hermes workers write live progress only to their runtime agent.log; the run
    # directory goes quiet after launch.
    newest=$( { stat -c %Y "$d"/* 2>/dev/null
                sudo -n stat -c %Y "$WORKER_HOMES/$id/logs/agent.log" 2>/dev/null; } | sort -n | tail -1)
    if [ -n "$newest" ] && [ $(( $(date +%s) - newest )) -gt "$STALL_SECONDS" ]; then
      echo "WORKER STALLED: $id status=$status no output for $(( ( $(date +%s) - newest ) / 60 ))m"
      exit 0
    fi
  done
  sleep "$POLL_SECONDS"
done
