#!/usr/bin/env bash
# Compare or install the live worker-host system from this repository.
#
#   install.sh [--check]   read-only: sha256-compare every repository file with
#                          its installed target and every client path with its
#                          symlink into the repository; print DRIFT lines and
#                          exit 1 on any drift.
#   install.sh --apply     make the live copies come from the repository.
#                          Refuses while any worker run is active, while
#                          ~/.hermes/profiles/cal/state/HOLD-FOR-REBOOT exists,
#                          or while worker-host/ has uncommitted changes.
#                          Each replaced file is copied first to
#                          /var/backups/agent-worker/<timestamp>/<original path>.
#
# A systemd step --apply could not finish (daemon-reload after a unit changed,
# the broker restart when a run started during the apply) is recorded in
# /var/backups/agent-worker/pending; --check reports it as PENDING and the next
# --apply runs it.
#
# Exit status: 0 done or no drift, 1 drift (--check) or refused, 2 usage,
# 3 files installed but a recorded systemd step is still pending.
#
# WORKER_HOST_PREFIX (system targets) and WORKER_HOST_HOME (client paths) exist
# so tests can run against a scratch tree; leave them unset on the live host.
# Under WORKER_HOST_PREFIX the tree belongs to the caller: nothing goes through
# sudo, installed files keep the caller as owner, and systemctl commands are
# printed, never run.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX=${WORKER_HOST_PREFIX:-}
HOME_DIR=${WORKER_HOST_HOME:-/home/hermes}
CAL=$HOME_DIR/.hermes/profiles/cal
W=$CAL/workspace/scripts
C=$CAL/scripts
F=$HOME_DIR/.hermes/profiles/foreman/scripts
SKILL=$HOME_DIR/.hermes/profiles/foreman/skills/foreman-method/scripts
LAUNCHER=$W/repo-worker
HOLD=$CAL/state/HOLD-FOR-REBOOT
BACKUP_ROOT=$PREFIX/var/backups/agent-worker
LIBEXEC=$PREFIX/usr/local/libexec
UNITS=$PREFIX/etc/systemd/system
MOUNT_UNIT='var-lib-agent\x2dworker-coding\x2dagent\x2dsystem.mount'
PENDING=$BACKUP_ROOT/pending
RELOAD='daemon-reload'
RESTART='try-restart agent-worker-broker.service'

# <repository file>|<installed target>|<owner:group:mode for a new target>
SYSTEM_FILES=(
  "libexec/agent-worker-runner|$LIBEXEC/agent-worker-runner|root:root:755"
  "libexec/agent-worker-broker|$LIBEXEC/agent-worker-broker|root:root:755"
  "libexec/agent-worker-codex-auth-sync|$LIBEXEC/agent-worker-codex-auth-sync|root:root:755"
  "libexec/agent-worker-coordination-probe|$LIBEXEC/agent-worker-coordination-probe|root:root:755"
  "libexec/agent-worker-hermes/host/bin/agent-hermes-worker|$LIBEXEC/agent-worker-hermes/host/bin/agent-hermes-worker|root:root:755"
  "libexec/agent-worker-hermes/host/hermes-worker/config.read.yaml|$LIBEXEC/agent-worker-hermes/host/hermes-worker/config.read.yaml|root:root:444"
  "libexec/agent-worker-hermes/host/hermes-worker/config.write.yaml|$LIBEXEC/agent-worker-hermes/host/hermes-worker/config.write.yaml|root:root:444"
  "etc/agent-worker/defaults.json|$PREFIX/etc/agent-worker/defaults.json|root:root:644"
  "etc/sudoers.d/portfolio-worker-coordination|$PREFIX/etc/sudoers.d/portfolio-worker-coordination|root:root:440"
  "systemd/agent-worker-broker.service|$UNITS/agent-worker-broker.service|root:root:644"
  "systemd/agent-worker-broker.socket|$UNITS/agent-worker-broker.socket|root:root:644"
  "systemd/agent-worker-codex-auth-sync.service|$UNITS/agent-worker-codex-auth-sync.service|root:root:644"
  "systemd/agent-worker-codex-auth-sync.timer|$UNITS/agent-worker-codex-auth-sync.timer|root:root:644"
  "systemd/$MOUNT_UNIT|$UNITS/$MOUNT_UNIT|root:root:644"
)

# <repository file>|<client path that becomes a symlink to it>
CLIENT_LINKS=(
  "libexec/agent-worker-runner|$W/repo-worker"
  "libexec/agent-worker-broker|$W/agent-worker-broker"
  "libexec/agent-worker-hermes/host/bin/agent-hermes-worker|$W/agent-hermes-worker"
  "libexec/agent-worker-hermes/host/hermes-worker/config.read.yaml|$W/agent-hermes-worker.config.read.yaml"
  "libexec/agent-worker-hermes/host/hermes-worker/config.write.yaml|$W/agent-hermes-worker.config.write.yaml"
  "libexec/agent-worker-codex-auth-sync|$W/agent-worker-codex-auth-sync"
  "libexec/agent-worker-coordination-probe|$W/agent-worker-coordination-probe"
  "etc/agent-worker/defaults.json|$CAL/workspace/config/agent-worker-defaults.json"
  "bin/wait-for-workers.sh|$C/wait-for-workers.sh"
  "bin/worker-watchdog.sh|$C/worker-watchdog.sh"
  "bin/model-usage-watch-v20260930.py|$C/model-usage-watch-v20260930.py"
  "bin/worker-pane.sh|$F/worker-pane.sh"
  "bin/watch-worker.py|$F/watch-worker.py"
  "bin/chain-workers.sh|$SKILL/chain-workers.sh"
)
for test in "$REPO"/tests/test-*; do
  name=$(basename "$test")
  # Only tests that lived in the cal workspace go back there as symlinks.
  case "$name" in
    test-repo-worker-symlink-client|test-install-check|test-install-apply) continue ;;
  esac
  CLIENT_LINKS+=("tests/$name|$W/$name")
done

usage() {
  echo "usage: install.sh [--check | --apply]" >&2
  exit 2
}

mode=check
case "${1:-}" in
  "" | --check) mode=check ;;
  --apply) mode=apply ;;
  *) usage ;;
esac
[[ $# -le 1 ]] || usage

as_root() {
  if [[ -n $PREFIX ]]; then "$@"; else sudo -n "$@"; fi
}

# Root-only paths (/etc/agent-worker, /etc/sudoers.d) are read through sudo -n.
as_reader() {
  if [[ -r "${*: -1}" ]]; then "$@"; else as_root "$@"; fi
}

target_exists() {
  [[ -e "$1" ]] || as_root test -e "$1" 2>/dev/null
}

# install_as <owner> <group> <mode> <install arguments>; a scratch prefix
# cannot chown to root, so there the caller keeps ownership.
install_as() {
  local owner=$1 group=$2 mode=$3
  shift 3
  if [[ -n $PREFIX ]]; then
    install -m "$mode" "$@"
  else
    sudo -n install -o "$owner" -g "$group" -m "$mode" "$@"
  fi
}

run_systemctl() {
  if [[ -n $PREFIX ]]; then
    echo "would run: sudo -n systemctl $*"
  else
    sudo -n systemctl "$@"
  fi
}

sha_of() {
  as_reader sha256sum "$1" 2>/dev/null | cut -d' ' -f1
}

drift=0
changed_system=()
changed_links=()

check_system() {
  local entry rel target want have
  for entry in "${SYSTEM_FILES[@]}"; do
    IFS='|' read -r rel target _ <<<"$entry"
    want=$(sha_of "$REPO/$rel")
    if ! target_exists "$target"; then
      echo "DRIFT missing   $target (repo $rel)"
      drift=1
      changed_system+=("$entry")
      continue
    fi
    have=$(sha_of "$target")
    if [[ -z "$have" ]]; then
      echo "DRIFT unreadable $target (sudo -n unavailable)"
      drift=1
      continue
    fi
    if [[ "$have" != "$want" ]]; then
      echo "DRIFT content   $target differs from $rel"
      drift=1
      changed_system+=("$entry")
    fi
  done
}

check_links() {
  local entry rel path
  for entry in "${CLIENT_LINKS[@]}"; do
    IFS='|' read -r rel path <<<"$entry"
    if [[ -L "$path" && "$(readlink -f "$path")" == "$REPO/$rel" ]]; then
      continue
    fi
    if [[ ! -e "$path" && ! -L "$path" ]]; then
      echo "DRIFT missing   $path (link to $rel)"
    elif [[ -L "$path" ]]; then
      echo "DRIFT link      $path points at $(readlink "$path"), not $rel"
    elif [[ "$(sha_of "$path")" == "$(sha_of "$REPO/$rel")" ]]; then
      echo "DRIFT copy      $path is a copy of $rel (same content), not a symlink"
    else
      echo "DRIFT copy      $path differs from $rel and is not a symlink"
    fi
    drift=1
    changed_links+=("$entry")
  done
}

# One systemctl argument line per step an earlier --apply left unfinished.
need_reload=0
need_restart=0
check_pending() {
  local step
  while IFS= read -r step; do
    case "$step" in
      "$RELOAD") need_reload=1 ;;
      "$RESTART") need_restart=1 ;;
      *) continue ;;
    esac
    echo "PENDING         sudo systemctl $step (an earlier --apply did not finish it)"
    drift=1
  done < <(as_reader cat "$PENDING" 2>/dev/null || true)
}

check_system
check_links
check_pending
echo "checked ${#SYSTEM_FILES[@]} installed files and ${#CLIENT_LINKS[@]} client paths: ${#changed_system[@]} installed and ${#changed_links[@]} client paths drift"

if [[ $mode == check ]]; then
  exit "$drift"
fi

# --apply from here on.
if [[ $drift -eq 0 ]]; then
  echo "nothing to apply"
  exit 0
fi
if [[ -e "$HOLD" ]]; then
  echo "refusing: $HOLD exists (owner's reboot hold)" >&2
  exit 1
fi

active_runs() {
  # Fails closed: no launcher, an error, or unparsable output counts as active.
  local listing
  [[ -x "$LAUNCHER" ]] || { echo "unknown"; return; }
  if ! listing=$("$LAUNCHER" --list --active 2>/dev/null); then
    echo "unknown"
    return
  fi
  python3 -c '
import json, sys
try:
    runs = json.load(sys.stdin)
except ValueError:
    print("unknown"); raise SystemExit
print(len(runs) if isinstance(runs, list) else "unknown")' <<<"$listing"
}

require_idle() {
  local count
  count=$(active_runs)
  if [[ "$count" != 0 ]]; then
    echo "refusing: worker runs active ($count per $LAUNCHER --list --active)" >&2
    exit 1
  fi
}
require_idle

# Only committed content is installed: a local edit or an untracked file under
# worker-host/ would reach the live host without review.
if ! uncommitted=$(git -c core.fsmonitor=false -C "$REPO" status --porcelain -- . 2>&1); then
  echo "refusing: cannot read git status of $REPO: $uncommitted" >&2
  exit 1
fi
if [[ -n $uncommitted ]]; then
  echo "refusing: $REPO has uncommitted changes; --apply installs committed content only:" >&2
  printf '%s\n' "$uncommitted" >&2
  exit 1
fi

for entry in "${SYSTEM_FILES[@]}"; do
  IFS='|' read -r rel _ <<<"$entry"
  if [[ $rel == etc/sudoers.d/* ]]; then
    as_root visudo -cf "$REPO/$rel" >/dev/null || {
      echo "refusing: visudo rejects $rel" >&2
      exit 1
    }
  fi
done

recorded=$(( need_reload + need_restart ))
write_pending() {
  local steps=()
  [[ $need_reload -eq 0 ]] || steps+=("$RELOAD")
  [[ $need_restart -eq 0 ]] || steps+=("$RESTART")
  [[ ${#steps[@]} -gt 0 || $recorded -gt 0 ]] || return 0
  as_root test -d "$BACKUP_ROOT" || install_as root root 0700 -d "$BACKUP_ROOT"
  { [[ ${#steps[@]} -eq 0 ]] || printf '%s\n' "${steps[@]}"; } | as_root tee "$PENDING" >/dev/null
  recorded=1
}

for entry in "${changed_system[@]}"; do
  IFS='|' read -r rel _ <<<"$entry"
  case "$rel" in
    systemd/*) need_reload=1 ;;
  esac
  case "$rel" in
    libexec/agent-worker-broker | systemd/agent-worker-broker.service) need_restart=1 ;;
  esac
done
# Recorded before the first file lands, so a step lost to an interruption or a
# run that starts mid-apply is reported now and finished by the next --apply.
write_pending
finished=0
report_pending() {
  [[ $finished -eq 0 && $(( need_reload + need_restart )) -gt 0 ]] || return 0
  echo "apply stopped early; pending steps are recorded in $PENDING:" >&2
  [[ $need_reload -eq 0 ]] || echo "  run \`sudo systemctl $RELOAD\`" >&2
  [[ $need_restart -eq 0 ]] || echo "  run \`sudo systemctl $RESTART\` when idle" >&2
}
trap report_pending EXIT

stamp=$(date +%Y%m%d-%H%M%S)
backup=$BACKUP_ROOT/$stamp
if [[ $(( ${#changed_system[@]} + ${#changed_links[@]} )) -gt 0 ]]; then
  install_as root root 0700 -d "$backup"
fi

back_up() {
  if [[ -e "$1" || -L "$1" ]] || as_root test -e "$1"; then
    as_root mkdir -p "$backup$(dirname "$1")"
    as_root cp -a "$1" "$backup$1"
  fi
}

for entry in "${changed_system[@]}"; do
  IFS='|' read -r rel target default <<<"$entry"
  if target_exists "$target"; then
    read -r owner group perm < <(as_root stat -c '%U %G %a' "$target")
  else
    IFS=':' read -r owner group perm <<<"$default"
    # An existing parent keeps its mode; only a missing one is made.
    d=$(dirname "$target")
    as_root test -d "$d" || install_as root root 0755 -d "$d"
  fi
  back_up "$target"
  install_as "$owner" "$group" "$perm" "$REPO/$rel" "$target"
  echo "installed $target ($owner:$group $perm)"
  case "$rel" in
    systemd/agent-worker-broker.socket)
      echo "NOTE: agent-worker-broker.socket changed; restart it by hand when no run is active" ;;
    systemd/agent-worker-codex-auth-sync.timer)
      echo "NOTE: restart agent-worker-codex-auth-sync.timer to load the new schedule" ;;
    systemd/var-lib-*)
      echo "NOTE: the coding-agent-system mount unit changed; it is not remounted here" ;;
  esac
done

for entry in "${changed_links[@]}"; do
  IFS='|' read -r rel path <<<"$entry"
  back_up "$path"
  mkdir -p "$(dirname "$path")"
  # A same-directory rename swaps the path in one step for running callers.
  ln -sfn "$REPO/$rel" "$path.worker-host-new"
  mv -Tf "$path.worker-host-new" "$path"
  echo "linked $path -> $REPO/$rel"
done

if [[ $need_reload -eq 1 ]]; then
  if run_systemctl $RELOAD; then
    need_reload=0
    write_pending
    echo "systemd daemon-reload done"
  else
    echo "units installed but systemd NOT reloaded; run \`sudo systemctl $RELOAD\`" >&2
  fi
fi
if [[ $need_restart -eq 1 ]]; then
  # The socket stays up; only the service process reloads the new broker. A run
  # that started during the apply keeps the old broker until the operator
  # restarts it.
  if [[ $need_reload -eq 1 ]]; then
    echo "broker installed but NOT restarted; run \`sudo systemctl $RELOAD\`, then \`sudo systemctl $RESTART\` when idle" >&2
  elif [[ $(active_runs) != 0 ]]; then
    echo "broker installed but NOT restarted; run \`sudo systemctl $RESTART\` when idle" >&2
  elif run_systemctl $RESTART; then
    need_restart=0
    write_pending
    echo "agent-worker-broker.service restarted (socket untouched)"
  else
    echo "broker installed but NOT restarted; run \`sudo systemctl $RESTART\` when idle" >&2
  fi
fi
finished=1
if [[ $(( ${#changed_system[@]} + ${#changed_links[@]} )) -gt 0 ]]; then
  echo "backups in $backup"
fi
if [[ $(( need_reload + need_restart )) -gt 0 ]]; then
  echo "pending steps stay recorded in $PENDING; install.sh --check lists them and the next --apply runs them" >&2
  exit 3
fi
