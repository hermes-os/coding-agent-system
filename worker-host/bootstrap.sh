#!/usr/bin/env bash
# Recreates the repo-worker host layout (user, worker home, tmpfiles, /opt
# parents, install.sh --apply, units) on a fresh Arch/Omarchy host. Mapped from
# the iMac and the Air, which were set up by hand.
#
#   sudo WORKER_GIT_NAME=<name> WORKER_GIT_EMAIL=<email> [ENABLE_CODEX_SYNC=1] \
#     bash worker-host/bootstrap.sh [--dry-run]
#
# Variables go after `sudo`: its env_reset drops any set before it.
#
# Idempotent: every step checks first and changes only what differs, so it can
# be rerun after each manual step (clone, runtime copy, logins). Phases that
# need something not there yet are skipped with a note, and the closing list
# shows what is still left.
#
# Evidence tags [E:...] name the inventory capture (kept outside the repo) holding the command output
# each value came from:
#   raw-imac-1.txt  id/getent/ls/getfacl of /var/lib/agent-worker, /opt, /etc, sudoers
#   raw-imac-2.txt  modes of every top-level worker-home entry, .local, .gitconfig keys
#   raw-imac-3.txt  systemd unit state, mount, tmpfiles, ACLs, /opt sizes and owners
#   raw-imac-4.txt  tmpfiles content, packages, worker PATH tools, rustup proxy, logins (meta)
#   raw-air.txt     the same layout on the Air (second host, set up by hand)
#   raw-sim.txt     what sim has today
#   SRC:<path>      a source file in coding-agent-system/worker-host (read, not run)
set -euo pipefail

DRY=0
case "${1:-}" in
  --dry-run) DRY=1 ;;
  "") ;;
  *) echo "usage: bootstrap.sh [--dry-run]" >&2; exit 2 ;;
esac

CALLER=hermes                                   # [E:SRC:libexec/agent-worker-broker CALLER_NAME]
WU=agent-worker                                 # [E:SRC:libexec/agent-worker-broker WORKER_NAME]
WH=/var/lib/agent-worker                        # [E:raw-imac-1 getent passwd]
CALLER_HOME=/home/$CALLER
REPO=$CALLER_HOME/Projects/hermes-os/coding-agent-system
CAL=$CALLER_HOME/.hermes/profiles/cal
LAUNCHER=$CAL/workspace/scripts/repo-worker
RELEASE=e3d78e60dd7a632bf01b21ece2f377f5aabc9aeb   # [E:SRC:libexec/agent-worker-hermes/host/bin/agent-hermes-worker TRUSTED_HERMES_SOURCE]
PY_DIR=cpython-3.14.7-linux-x86_64-gnu          # [E:same file, TRUSTED_HERMES_INTERPRETER]
PY_MINOR=3.14
MOUNT_UNIT='var-lib-agent\x2dworker-coding\x2dagent\x2dsystem.mount'
# Worker commit identity; the iMac's worker .gitconfig and `git config --global`
# both say user.name=Hermes [E:raw-imac-2 "gitconfig user"]. Pass both or the
# step is listed as left by hand (sim has no global identity [E:raw-sim]).
WORKER_GIT_NAME=${WORKER_GIT_NAME:-}
WORKER_GIT_EMAIL=${WORKER_GIT_EMAIL:-}

left=()
note() { printf '  - %s\n' "$*"; }
todo() { left+=("$*"); }
# Print what is left even when a step aborts under set -e.
print_left() {
  ((${#left[@]})) || return 0
  printf '\n== left by hand\n'
  local item
  for item in "${left[@]}"; do note "$item"; done
}
trap print_left EXIT
run() {
  if ((DRY)); then printf 'would run: %s\n' "$*"; else "$@"; fi
}
step() { printf '\n== %s\n' "$*"; }
# octal 0711 -> 711, 2750 -> 2750: the form `stat -c %a` prints.
octal() { printf '%o' "$((8#$1))"; }

# ensure_dir <path> <owner> <group> <mode>: create, or correct owner/mode.
ensure_dir() {
  local path=$1 owner=$2 group=$3 mode=$4 have
  if [[ -L $path ]]; then echo "refusing: $path is a symlink" >&2; exit 1; fi
  if [[ ! -d $path ]]; then
    run install -d -o "$owner" -g "$group" -m "$mode" "$path"
    echo "created $path ($owner:$group $mode)"
    return
  fi
  have=$(stat -c '%U:%G %a' "$path")
  if [[ $have != "$owner:$group $(octal "$mode")" ]]; then
    run chown "$owner:$group" "$path"
    run chmod "$mode" "$path"
    echo "fixed $path: was $have, now $owner:$group $mode"
  fi
}

# ensure_file <path> <owner> <group> <mode> <content>: write when content differs.
ensure_file() {
  local path=$1 owner=$2 group=$3 mode=$4 content=$5
  if [[ -f $path ]] && [[ "$(cat "$path")" == "$content" ]]; then
    [[ "$(stat -c '%U:%G %a' "$path")" == "$owner:$group $(octal "$mode")" ]] && return 0
  fi
  if ((DRY)); then echo "would write $path ($owner:$group $mode)"; return; fi
  local tmp
  tmp=$(mktemp "$(dirname "$path")/.bootstrap.XXXXXX")
  printf '%s\n' "$content" >"$tmp"
  chown "$owner:$group" "$tmp"; chmod "$mode" "$tmp"
  mv -f "$tmp" "$path"
  echo "wrote $path ($owner:$group $mode)"
}

# ---------------------------------------------------------------- preflight
step "0. preflight"
# Root in both modes: a non-root dry run cannot see inside .broker and
# reports false actions.
if [[ $EUID -ne 0 ]]; then echo "run with sudo" >&2; exit 1; fi
[[ -d /run/systemd/system ]] || { echo "systemd is not PID 1" >&2; exit 1; }
getent passwd "$CALLER" >/dev/null || { echo "no user $CALLER" >&2; exit 1; }
getent group "$CALLER" >/dev/null || { echo "no group $CALLER (broker socket group)" >&2; exit 1; }
# The sandbox is systemd-run transient units plus setpriv, not bubblewrap
# [E:SRC:libexec/agent-worker-broker launch() systemd-run ... ; runner
# provider_process_command /usr/bin/setpriv]. setfacl is required by
# provision_repo_acl [E:SRC:agent-worker-broker "setfacl is required"].
missing=()
for cmd in /usr/bin/python3 /usr/bin/setpriv /usr/bin/systemd-run /usr/bin/setfacl /usr/bin/git /usr/bin/visudo /usr/bin/systemd-tmpfiles; do
  [[ -x $cmd ]] || missing+=("$cmd")
done
if ((${#missing[@]})); then
  echo "missing required commands: ${missing[*]} (packages: python util-linux systemd acl git sudo)" >&2
  exit 1
fi
note "required commands present"
# Worker toolchains must be on /usr/bin: the worker PATH is
# /var/lib/agent-worker/.local/bin:/usr/local/bin:/usr/bin:/bin and
# /home/hermes is invisible to workers [E:SRC:agent-worker-broker PATH=...;
# raw-imac-4 "which on worker PATH"]. sim lacks node/npm/pnpm/uv [E:raw-sim].
tools_missing=()
for t in node npm pnpm cargo qmake6 chromium dotnet deno; do
  PATH=/usr/local/bin:/usr/bin:/bin command -v "$t" >/dev/null || tools_missing+=("$t")
done
if ((${#tools_missing[@]})); then
  todo "system tools missing on the worker PATH: ${tools_missing[*]} (iMac/Air: pacman nodejs npm pnpm; never via mise under /home/hermes). Omarchy refuses a bare -Syu: follow the foreman-method toolchain pitfall."
fi

# --------------------------------------------------------- 1. user and group
step "1. system user and group $WU"
# iMac uid/gid 959, Air 961, both system ids with own group, no supplementary
# groups, home /var/lib/agent-worker, shell /usr/sbin/nologin, password locked
# [E:raw-imac-1 "## id", "shadow status"; raw-air]. Nothing pins the number
# (runner/broker use getpwnam), and 961 is cups-browsed on sim [E:raw-sim], so
# let useradd pick.
if ! getent group "$WU" >/dev/null; then run groupadd --system "$WU"; echo "created group $WU"; fi
if ! getent passwd "$WU" >/dev/null; then
  run useradd --system --gid "$WU" --home-dir "$WH" --no-create-home \
    --shell /usr/sbin/nologin --comment "" "$WU"
  echo "created user $WU"
elif [[ "$(getent passwd "$WU" | cut -d: -f6,7)" != "$WH:/usr/sbin/nologin" ]]; then
  echo "refusing: existing $WU has home/shell $(getent passwd "$WU" | cut -d: -f6,7), want $WH:/usr/sbin/nologin" >&2
  exit 1
fi
if ((!DRY)); then
  [[ "$(passwd -S "$WU" | awk '{print $2}')" == L ]] || { passwd -l "$WU" >/dev/null; echo "locked $WU password"; }
fi

# --------------------------------------------------------- 2. worker home
step "2. worker home layout under $WH"
# Owners and modes copied from the iMac; the Air matches [E:raw-imac-2 "stat
# top", ".local tree"; raw-air]. Items the broker/runner create on demand
# (workspaces/<key>, .broker/runs, state/runs/<id>, .hermes-worker/<id>) are
# made here only as their parents.
ensure_dir "$WH"                    root root 0711
ensure_dir "$WH/.broker"            root root 0700   # TRUST_ROOT, root-only trust records
ensure_dir "$WH/.broker/runs"       root root 0700
ensure_dir "$WH/workspaces"         root root 0711   # bind targets per repo
ensure_dir "$WH/toolchains"         root root 0755
ensure_dir "$WH/.local"             root root 0711
ensure_dir "$WH/.local/state"       root root 0711
# Run registry readable by the caller: root:hermes 2750 [E:raw-imac-3 "state dir modes"]
for d in "" /runs /projects /locks /repo-acl; do
  ensure_dir "$WH/.local/state/agent-workers$d" root "$CALLER" 2750
done
ensure_dir "$WH/.local/bin"         "$WU" "$WU" 0700
ensure_dir "$WH/.local/share"       "$WU" "$WU" 0700
for d in .agents .cache .claude .codex .config .hermes .hermes-worker .kimi .ssh .state; do
  ensure_dir "$WH/$d" "$WU" "$WU" 0700
done
# Mount point for the read-only bind of coding-agent-system [E:SRC:systemd/$MOUNT_UNIT].
[[ -d $WH/coding-agent-system ]] || ensure_dir "$WH/coding-agent-system" root root 0755

# Rust: proxies in .local/bin pin RUSTUP_HOME/CARGO_HOME inside the worker home,
# default toolchain "worker-stable" links to a root-owned copy under
# toolchains/ [E:raw-imac-4 "rustup wrapper", "rustup settings"].
PROXY='#!/bin/sh
set -eu
export RUSTUP_HOME=/var/lib/agent-worker/.state/rustup
export CARGO_HOME=/var/lib/agent-worker/.cache/cargo
name=${0##*/}
case "$name" in
  cargo|rustc|rustup|rustfmt|cargo-fmt|cargo-clippy|clippy-driver) exec "/usr/bin/$name" "$@" ;;
  *) printf '"'"'%s\n'"'"' '"'"'Unsupported Rust proxy name'"'"' >&2; exit 2 ;;
esac'
for n in cargo rustc rustup rustfmt cargo-fmt cargo-clippy clippy-driver; do
  ensure_file "$WH/.local/bin/$n" root root 0755 "$PROXY"
done
ensure_dir "$WH/.state/rustup"            "$WU" "$WU" 0700
ensure_dir "$WH/.state/rustup/toolchains" "$WU" "$WU" 0755
ensure_file "$WH/.state/rustup/settings.toml" "$WU" "$WU" 0644 'version = "12"
default_toolchain = "worker-stable"

[overrides]'
TC=$WH/toolchains/stable-x86_64-unknown-linux-gnu
if [[ ! -L $WH/.state/rustup/toolchains/worker-stable ]]; then
  run ln -s "$TC" "$WH/.state/rustup/toolchains/worker-stable"
  run chown -h "$WU:$WU" "$WH/.state/rustup/toolchains/worker-stable"
fi
# Red Acre's Rust rebuild ships a browser demo, so workers build wasm and run wasm-opt.
[[ -d $TC/lib/rustlib/wasm32-unknown-unknown ]] || todo "add the wasm target to the worker toolchain: rustup target add wasm32-unknown-unknown (as hermes), then sudo cp -r ~hermes/.rustup/toolchains/stable-x86_64-unknown-linux-gnu/lib/rustlib/wasm32-unknown-unknown $TC/lib/rustlib/ and chown -R root:root it (same rustc version on both sides)"
command -v wasm-opt >/dev/null || todo "install binaryen (wasm-opt): sudo pacman -S --needed binaryen"
[[ -x $TC/bin/rustc ]] || todo "copy the worker Rust toolchain root-owned from the iMac: sudo -n tar -C $WH/toolchains -cf - stable-x86_64-unknown-linux-gnu | ssh sim 'sudo -n tar -C $WH/toolchains --same-owner -xpf -' (iMac has Rust 1.98.0 there; android/ (iMac only, not on the Air) is optional)"

# --------------------------------------------------------- 3. worker git identity
step "3. worker .gitconfig (root:root 0644)"
# The broker refuses a .gitconfig that is not root-owned and appends
# safe.directory per workspace [E:SRC:agent-worker-broker provision_safe_directory;
# raw-imac-2 "gitconfig keys": 147 safe.directory + user.name + user.email].
GC=$WH/.gitconfig
if [[ ! -e $GC ]]; then run install -o root -g root -m 0644 /dev/null "$GC"; fi
if ((!DRY)); then
  git config --file "$GC" --get-all safe.directory 2>/dev/null | grep -qx "$WH/coding-agent-system" \
    || git config --file "$GC" --add safe.directory "$WH/coding-agent-system"
  if [[ -n $WORKER_GIT_NAME && -n $WORKER_GIT_EMAIL ]]; then
    git config --file "$GC" user.name "$WORKER_GIT_NAME"
    git config --file "$GC" user.email "$WORKER_GIT_EMAIL"
  fi
  chown root:root "$GC"; chmod 0644 "$GC"
fi
if [[ -z "$(git config --file "$GC" user.name 2>/dev/null || true)" || -z "$(git config --file "$GC" user.email 2>/dev/null || true)" ]] \
   && [[ -z $WORKER_GIT_NAME || -z $WORKER_GIT_EMAIL ]]; then
  todo "worker git identity: rerun as sudo WORKER_GIT_NAME=... WORKER_GIT_EMAIL=... bash worker-host/bootstrap.sh (both, the iMac's global values), or worker commits come out as agent-worker@localhost"
fi

# --------------------------------------------------------- 4. runtime dirs (tmpfiles)
step "4. /etc/tmpfiles.d/agent-worker.conf"
# Not installed by install.sh and owned by no package [E:raw-imac-4 "tmpfiles
# conf"]; same file on the Air [E:raw-air]. The broker checks /run/agent-worker
# is root:hermes 0750 and prompts root:root 0700 [E:SRC:agent-worker-broker
# ensure_runtime_directories].
ensure_file /etc/tmpfiles.d/agent-worker.conf root root 0644 "d /run/agent-worker 0750 root $CALLER -
d /run/agent-worker/prompts 0700 root root -
d /var/lib/agent-worker-scratch 0711 root root -"
run systemd-tmpfiles --create /etc/tmpfiles.d/agent-worker.conf

# --------------------------------------------------------- 5. trusted runtime parents
step "5. /opt/agent-worker-hermes parents"
# The adapter refuses any file under the release or the interpreter not owned
# root:root, and checks the python alias symlink [E:SRC:agent-hermes-worker
# lines ~800-920; raw-imac-3 "opt non-root" = 0].
ensure_dir /opt/agent-worker-hermes          root root 0755
ensure_dir /opt/agent-worker-hermes/releases root root 0755
ensure_dir /opt/agent-worker-hermes/python   root root 0755
if [[ ! -x /opt/agent-worker-hermes/releases/$RELEASE/source/.venv/bin/hermes || ! -x /opt/agent-worker-hermes/python/$PY_DIR/bin/python$PY_MINOR ]]; then
  todo "copy the trusted Hermes runtime root-owned from the iMac, then prove 0 non-root files: sudo -n tar -C /opt/agent-worker-hermes -cf - python/$PY_DIR python/cpython-$PY_MINOR-linux-x86_64-gnu releases/$RELEASE | ssh <host> 'sudo -n tar -C /opt/agent-worker-hermes --same-owner -xpf - && sudo -n find /opt/agent-worker-hermes ! -user root | wc -l' (or build it there: worker-host/build-hermes-release.sh <hermes-agent checkout> $RELEASE)"
fi

# --------------------------------------------------------- 6. system files via install.sh
step "6. worker-host/install.sh --apply (as $CALLER)"
if [[ ! -f $REPO/worker-host/install.sh ]]; then
  todo "clone coding-agent-system to $REPO from git@git.imhermes.dev:hermes/coding-agent-system.git (as $CALLER, needs sim's forge key), then rerun this script"
  echo "skipped: $REPO is missing"
else
  owner=$(stat -c %U "$REPO")
  [[ $owner == "$CALLER" ]] || { echo "refusing: $REPO is owned by $owner" >&2; exit 1; }
  # install.sh --apply refuses unless `repo-worker --list --active` prints a
  # JSON list; with no launcher it counts runs as "unknown" and refuses
  # [E:SRC:install.sh active_runs/require_idle]. Pre-make the exact link it
  # wants, so it is not drift [E:SRC:install.sh CLIENT_LINKS first entry].
  if [[ -e $LAUNCHER && ! -L $LAUNCHER ]]; then
    echo "refusing: $LAUNCHER exists and is not a link" >&2; exit 1
  fi
  if [[ ! -L $LAUNCHER ]]; then
    run sudo -u "$CALLER" -H install -d -m 0700 "$CAL"
    run sudo -u "$CALLER" -H mkdir -p "$(dirname "$LAUNCHER")"
    run sudo -u "$CALLER" -H ln -s "$REPO/worker-host/libexec/agent-worker-runner" "$LAUNCHER"
  fi
  # install.sh writes client paths as the caller and system paths through
  # `sudo -n`; run it as root and the client copies end up root-owned.
  # It needs the caller's NOPASSWD sudo (sim: /etc/sudoers.d/99-omarchy-nopasswd-hermes [E:raw-sim]).
  # --apply only on a fresh host (an installed system file is missing). On a
  # host already set up, drift is a deploy decision: list it, never apply it.
  set +e
  check_out=$(sudo -u "$CALLER" -H bash "$REPO/worker-host/install.sh" --check 2>&1)
  set -e
  printf '%s\n' "$check_out"
  # Fresh host = the broker was never installed. A file added to install.sh
  # later shows as missing on set-up hosts too; that is drift, not fresh.
  if [[ ! -e /usr/local/libexec/agent-worker-broker ]]; then
    if ((DRY)); then
      echo "would run: install.sh --apply (fresh host: broker not installed)"
    else
      set +e
      sudo -u "$CALLER" -H bash "$REPO/worker-host/install.sh" --apply
      rc=$?
      set -e
      case $rc in
        0) ;;
        3) todo "install.sh left a systemd step pending; run its printed command, then install.sh --check" ;;
        *) todo "install.sh --apply refused or failed ($rc): read its output above, fix, rerun this script" ;;
      esac
    fi
  elif grep -q '^DRIFT' <<<"$check_out"; then
    todo "install.sh --check reports drift on an installed host; run install.sh --apply yourself when no run is active"
  fi

  # ------------------------------------------------------- 7. units
  step "7. enable mount and broker socket"
  # iMac: mount enabled+mounted, socket enabled, broker.service disabled
  # (socket-activated), codex-auth-sync.timer enabled on the iMac but disabled
  # on the Air [E:raw-imac-3 "is-enabled/active"; raw-air]. install.sh enables
  # none of them.
  run systemctl daemon-reload
  run systemctl enable --now "$MOUNT_UNIT"
  run systemctl enable --now agent-worker-broker.socket
  if [[ ${ENABLE_CODEX_SYNC:-0} == 1 ]]; then
    run systemctl enable --now agent-worker-codex-auth-sync.timer
  elif ! systemctl is-enabled -q agent-worker-codex-auth-sync.timer 2>/dev/null; then
    todo "decide on agent-worker-codex-auth-sync.timer (iMac on, Air off). It shares $CALLER's openai-codex grant from $CALLER_HOME/.hermes/auth.json into the worker stores; enable with ENABLE_CODEX_SYNC=1 only after $CALLER on sim has that login."
  fi
  if ((!DRY)) && ! findmnt -n "$WH/coding-agent-system" >/dev/null; then
    echo "WARNING: $WH/coding-agent-system is not mounted" >&2
  fi

  # ------------------------------------------------------- 8. worker agent homes
  step "8. agent homes from coding-agent-system/install.sh (HOME=$WH)"
  # The iMac's .agents/config.json and managed-install.json show the canonical
  # installer was run with HOME=$WH, system root = the bind mount, coordination
  # repo $WH/.state/coordination; the files it wrote are root-owned
  # [E:raw-imac-2 ".agents/.kimi/.cursor"; configure-hosts.py main()]. It
  # exits unless the coordination repo is a git checkout. Run it once only
  # (no managed-install.json yet): it writes as root and keeps old modes, so a
  # rerun would turn the worker's own config files root-owned. Root's git needs
  # an env-scope safe.directory for the agent-worker-owned clone, and
  # GIT_CONFIG_GLOBAL keeps it off the worker-writable $WH/.config/git/config.
  if [[ -f $WH/.agents/managed-install.json ]]; then
    note "agent homes already installed (managed-install.json present); skipped"
  elif sudo -u "$WU" -H git -C "$WH/.state/coordination" rev-parse --show-toplevel >/dev/null 2>&1; then
    run env HOME="$WH" GIT_CONFIG_GLOBAL="$WH/.gitconfig" GIT_CONFIG_COUNT=1 \
      GIT_CONFIG_KEY_0=safe.directory GIT_CONFIG_VALUE_0="$WH/.state/coordination" \
      bash "$WH/coding-agent-system/install.sh" --coordination-repo "$WH/.state/coordination"
    for f in "$WH/.codex/config.toml" "$WH/.kimi/config.toml"; do
      [[ -f $f ]] && { run chown "$WU:$WU" "$f"; run chmod 0600 "$f"; }
    done
  else
    todo "coordination repo: as $WU make an ed25519 key $WH/.ssh/coordination_ed25519, an .ssh/config for git.imhermes.dev (User git, that IdentityFile), register the public key on Forgejo, then clone git@git.imhermes.dev:hermes/coding-agent-system.git to $WH/.state/coordination as $WU and rerun this script (it then runs the canonical installer for $WH)"
  fi
fi

# --------------------------------------------------------- 9. checks only
step "9. provider binaries and logins (checked, never written)"
# The broker probe wants claude, codex and kimi on the worker PATH
# [E:SRC:agent-worker-broker probe() binaries]; iMac versions [E:raw-imac-4].
declare -A BIN_HOW=(
  [claude]="root:root 0755 copy of the Claude Code binary (iMac: 2.1.258), e.g. sudo -n tar -C $WH/.local/bin -cf - claude | ssh sim 'sudo -n tar -C $WH/.local/bin --same-owner -xpf -'"
  [codex]="root:root 0755 copy of codex-cli (iMac: 0.150.1), same tar route"
  [kimi]="symlink to $WH/.local/share/uv/tools/kimi-cli/bin/kimi from a uv tool install run as $WU (needs uv; iMac has an unpackaged /usr/local/bin/uv)"
)
for b in claude codex kimi; do
  [[ -x $WH/.local/bin/$b ]] || todo "$WH/.local/bin/$b missing: ${BIN_HOW[$b]}"
done
# Existence, owner and mode only, as the broker probe checks them
# [E:SRC:agent-worker-broker path_auth_ok]. Never copy one host's OAuth file to
# another: refresh tokens are single-use.
declare -A AUTH_HOW=(
  [.claude/.credentials.json]="owner runs: ssh -t $(uname -n) sudo -u $WU -H $WH/.local/bin/claude auth login"
  [.codex/auth.json]="codex sign-in as $WU, or ENABLE_CODEX_SYNC=1 once $CALLER on this host holds the openai-codex grant (whether the sync creates a missing store is unverified)"
  [.hermes/auth.json]="API-key rows: sudo -u $WU -H env HERMES_HOME=$WH/.hermes /opt/agent-worker-hermes/releases/$RELEASE/source/.venv/bin/hermes auth add anthropic --type api-key --label <l> (iMac pool: anthropic 2, openrouter 1, openai-codex 1)"
  [.kimi/config.toml]="Kimi sign-in or key as $WU (method not recorded on the iMac)"
)
# Without a system tirith the worker Hermes prints a scanner warning ahead of
# its OUTCOME line, and the runner then marks every run blocked.
[[ -x /usr/local/bin/tirith ]] || todo "/usr/local/bin/tirith missing: sudo -n $REPO/bin/tirith-install, or copy the iMac's root 0755 binary"
for f in .claude/.credentials.json .codex/auth.json .hermes/auth.json .kimi/config.toml; do
  # The broker accepts the owner with no group/other bits [E:SRC:agent-worker-broker path_auth_ok].
  if [[ -s $WH/$f && "$(stat -c %U "$WH/$f")" == "$WU" ]] && (( (8#$(stat -c %a "$WH/$f") & 8#077) == 0 )); then :; else
    todo "$WH/$f absent, not owned by $WU, or readable by others: ${AUTH_HOW[$f]}"
  fi
done

# Packets live here, 0644, launched by full path [E:raw-imac-3 "acl home paths"; repo-worker skill].
[[ -d $CALLER_HOME/Projects/cal-task-packets ]] || run sudo -u "$CALLER" -H install -d -m 0755 "$CALLER_HOME/Projects/cal-task-packets"
clones_missing=()
for r in ashwren ashwren-legacy hearth inkwell kestrel marquee marvin-legal-management nomad rpo-wellness tape-machine; do
  [[ -d $CALLER_HOME/Projects/hermes-os/$r/.git ]] || clones_missing+=("$r")
done
((${#clones_missing[@]} == 0)) || todo "portfolio clones under $CALLER_HOME/Projects/hermes-os as $CALLER, fresh from the forge (never synced from another host): ${clones_missing[*]}; set user.name/user.email in each. The broker sets the agent-worker ACLs on a repo at its first launch."
todo "verify: ~/.hermes/profiles/cal/workspace/scripts/repo-worker --self-test must print ok:true, then a read-only 3-line smoke run reaching completed with modelSource=request"
