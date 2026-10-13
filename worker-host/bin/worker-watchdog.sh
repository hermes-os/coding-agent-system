#!/usr/bin/env bash
# Watchdog: report any repo-worker run that just reached a terminal state.
# Prints only when there is something NEW to say. Empty output = no message.
set -u

W=/home/hermes/.hermes/profiles/cal/workspace
STATE=/home/hermes/.hermes/profiles/cal/state/worker-watchdog-reported.txt
mkdir -p "$(dirname "$STATE")"
touch "$STATE"

shopt -s nullglob
for d in /var/lib/agent-worker/.local/state/agent-workers/runs/*/; do
  id=$(basename "$d")
  grep -qxF "$id" "$STATE" && continue

  meta="$d/metadata.json"
  [ -f "$meta" ] || continue

  read -r status outcome blocker < <(python3 - "$meta" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    print("unknown - -"); raise SystemExit
s = d.get("status", "unknown")
o = d.get("outcome", "-")
b = d.get("blocker", "-") or "-"
b = b.replace(" ", "_")[:90]
print(f"{s} {o} {b}")
PY
)

  case "$status" in
    completed|failed|stopped|dead|blocked|unverified) ;;
    *) continue ;;
  esac

  # record before printing so a crash cannot double-report
  echo "$id" >> "$STATE"

  started=$(python3 -c "
import json,sys
try:
    d=json.load(open('$meta'))
    print(d.get('createdAt','?')[:16])
except Exception: print('?')
" 2>/dev/null)

  # only recent work: stale zombie runs from other lanes must not ping anyone
  recent=$(python3 - "$meta" <<'PY'
import json, sys, datetime
try:
    d = json.load(open(sys.argv[1]))
    c = d.get("createdAt")
    t = datetime.datetime.fromisoformat(c.replace("Z", "+00:00"))
    age = datetime.datetime.now(datetime.timezone.utc) - t
    print("yes" if age.total_seconds() < 43200 else "no")
except Exception:
    print("no")
PY
)
  [ "$recent" = "yes" ] || { echo "$id" >> "$STATE"; continue; }

  role=$(python3 -c "
import json,sys
try:
    d=json.load(open('$meta'))
    print((d.get('role') or d.get('label') or 'run')[:60])
except Exception: print('run')
" 2>/dev/null)

  printf 'WORKER DONE: %s | %s | started %s UTC | outcome: %s%s\n' \
    "$id" "$role" "$started" "$status" "$([ "$blocker" != "-" ] && echo " — $blocker")"
done
