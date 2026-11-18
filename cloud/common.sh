# What every cloud environment's setup script shares. A setup script
# (cloud/<repo>.sh) sources this file, lists its steps, and ends with
# `setup <step>...`.
#
# The Claude app keeps a short loader per environment, which `cloud/app-script
# <repo>` prints. The loader downloads this file, the repository's script and
# working-agreement.md from coding-agent-system's GitHub copy and runs the
# script, so a change pushed here reaches each environment when the app next
# builds its cache: about once a week, or at once when the loader's text is
# saved changed.
#
# It runs as root on the session's VM (Ubuntu 24.04, x86_64) before Claude Code
# starts. When it ends within about five minutes, the app saves the VM's disk
# and later sessions start from that copy without running it again. A step
# that fails is reported and skipped: a session without one tool is better
# than a session that does not start.
set -u
home=${HOME:-/root}
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
work=$(mktemp -d)
export DEBIAN_FRONTEND=noninteractive

fetch() { # fetch <url> <sha256> <file>: download and verify
    curl -fsSL --retry 3 -o "$3" "$1" && echo "$2  $3" | sha256sum -c --quiet -
}

# The apt packages a script lists in apt_packages, installed by one step,
# because dpkg takes one install at a time. A script's after_packages() runs
# when they are in.
apt_packages=()
packages() {
    apt-get update -qq && apt-get install -y -qq --no-install-recommends "${apt_packages[@]}" &&
        { ! declare -F after_packages > /dev/null || after_packages; }
}

# rust [target...]: stable Rust with rustfmt and clippy. The image's Rust can
# come without rustup; then rustup-init comes from static.rust-lang.org (the
# rustup.rs installer script is not on the default network allowlist).
rust() {
    if ! command -v rustup > /dev/null; then
        curl -fsSL --retry 3 -o "$work/rustup-init" \
            https://static.rust-lang.org/rustup/dist/x86_64-unknown-linux-gnu/rustup-init &&
            chmod 755 "$work/rustup-init" &&
            "$work/rustup-init" -y --profile minimal --no-modify-path &&
            ln -sf "$home"/.cargo/bin/* /usr/local/bin/ || return 1
    fi
    rustup toolchain install stable --profile minimal --component rustfmt,clippy &&
        rustup default stable &&
        { [ $# -eq 0 ] || rustup target add "$@"; }
}

# conda <prefix> <package>...: a conda-forge environment at <prefix>, for
# toolchains Ubuntu 24.04 lacks or has too old (Qt 6.8, .NET 9). conda-forge
# is on the default network allowlist; micromamba comes from its GitHub
# release.
conda() {
    local prefix=$1
    shift
    if [ ! -x /usr/local/bin/micromamba ]; then
        fetch https://github.com/mamba-org/micromamba-releases/releases/download/2.10.0-0/micromamba-linux-64 \
            701f39c06f8e6a670a0e186c8479b9e5c0502a2f0cda6cef65d83bdd2875e8bd "$work/micromamba.$$" &&
            install -m 755 "$work/micromamba.$$" /usr/local/bin/micromamba || return 1
    fi
    MAMBA_ROOT_PREFIX=/opt/mamba micromamba create -y -q -p "$prefix" -c conda-forge --override-channels "$@" &&
        MAMBA_ROOT_PREFIX=/opt/mamba micromamba clean -y -q --all
}

# A chromium command for scripts that start one. The image has Chrome for
# Testing, and everything here runs as root, where Chrome needs --no-sandbox.
chromium() {
    [ -e /usr/bin/chromium ] && return 0
    printf '#!/bin/sh\nexec /usr/bin/google-chrome --no-sandbox "$@"\n' > /usr/bin/chromium &&
        chmod 755 /usr/bin/chromium
}

# shell_env <line>...: lines for the shell Claude's commands run in. They go at
# the top of ~/.bashrc, above its early return for non-interactive shells, and
# into ~/.profile, in the order given. Steps run side by side, so a lock keeps
# one step's lines from overwriting another's.
shell_env() {
    local file lock
    exec {lock}> "$work/shell_env.lock" && flock "$lock" || return 1
    for file in "$home/.bashrc" "$home/.profile"; do
        touch "$file" &&
            { printf '%s\n' "$@"; grep -vxF -f <(printf '%s\n' "$@") "$file" || true; } > "$file.new" &&
            mv "$file.new" "$file" || { exec {lock}>&-; return 1; }
    done
    exec {lock}>&-
}

# The commit identity of the public repositories: the one Hermes's own clones
# of them use, so no real email reaches public history.
public_identity() {
    git config --global user.name Hermes &&
        git config --global user.email 267720388+hermes-os@users.noreply.github.com
}

# conda_shell <prefix>: activate a conda environment in Claude's shell, so its
# tools come first on PATH and its own settings (compilers, DOTNET_ROOT) hold.
conda_shell() {
    shell_env 'export MAMBA_ROOT_PREFIX=/opt/mamba' \
        'eval "$(/usr/local/bin/micromamba shell hook -s bash)"' \
        "micromamba activate $1"
}

# instructions: write the cloud rules, the repository's notes (what the
# script's notes() prints) and the working agreement as ~/.claude/CLAUDE.md,
# the session's user instructions.
instructions() {
    local agreement=$here/working-agreement.md
    [ -f "$agreement" ] || agreement=$here/../working-agreement.md
    [ -f "$agreement" ] || return 1
    mkdir -p "$home/.claude" && {
        cat <<'CLOUD'
# In a cloud session

You work in a cloud VM of the Claude app, not on Hermes's computer. The working agreement below holds, except where this part says otherwise.

- Work on the branch this session gave you. Commit there, run the gate, and push it; push again after each later change. Never push to main or any other branch, never rewrite a pushed commit, and never merge a pull request.
- `origin` is the repository's GitHub copy, not the primary. Foreman takes your pushed branch from GitHub, has it reviewed and lands it on Hermes's Git server; GitHub's main follows by itself.
- GitHub Actions does not run on these repositories, so you are the CI: run the gate in the repository's AGENTS.md, and every Linux step of its CI workflow if it has one, before you push. Say in your report which steps passed and which could not run here.
- `committer` is not installed here: commit with plain `git commit`.
- The VM has 4 cores and 16 GB of memory. Run one heavy build or test suite at a time.
- No keys reach this VM, and it cannot reach Hermes's Git server, his accounts, his data or his tailnet. A step that needs one of them is Foreman's: name it in your report.
- Name the branch and its last commit in your report.

CLOUD
        notes
        echo
        cat "$agreement"
    } > "$home/.claude/CLAUDE.md"
}

# setup <step>...: the apt packages and the steps side by side, then the lines
# a script's report() prints.
setup() {
    local step started=$SECONDS
    if [ ${#apt_packages[@]} -gt 0 ]; then set -- packages "$@"; fi
    for step in "$@"; do
        ("$step" > "$work/$step.log" 2>&1 || { echo "setup: $step failed:"; tail -n 8 "$work/$step.log"; }) &
    done
    wait
    if declare -F report > /dev/null; then report 2>&1 | sed 's/^/setup: /'; fi
    echo "setup: done in $((SECONDS - started)) s"
    rm -rf "$work"
    exit 0
}
