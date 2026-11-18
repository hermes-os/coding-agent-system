#!/bin/bash
# The setup script of the "Red Acre" cloud environment in the Claude app. The
# app keeps its own copy: after a change to this file or to
# working-agreement.md, load it again (Code, environment selector, the
# environment's settings icon, Setup script, Choose file, Save changes).
#
# It runs as root on the session's VM (Ubuntu 24.04, x86_64) before Claude Code
# starts. When it ends within about five minutes the VM's disk is saved, and
# later sessions start from that copy without running it again.
#
# It adds what the cloud image lacks for Red Acre's gate and art: Rust's
# rustfmt, clippy and wasm32 target, wasm-opt, photocraft-cli where the art
# scripts look for it, a chromium command, Pillow, ImageMagick, and Xvfb with
# Mesa. Then it writes the working agreement, with what is different in the
# cloud, as Claude's user instructions. A step that fails is reported and
# skipped: a session without one tool is better than a session that does not
# start.
set -u
home=${HOME:-/root}
work=$(mktemp -d)

fetch() { # fetch <url> <sha256> <file>: download and verify
    curl -fsSL --retry 3 -o "$3" "$1" && echo "$2  $3" | sha256sum -c --quiet -
}

# The image's Rust comes with rustup. Without it, rustup-init comes from
# static.rust-lang.org: sh.rustup.rs is not on the default network allowlist.
rust() {
    if ! command -v rustup > /dev/null; then
        curl -fsSL --retry 3 -o "$work/rustup-init" \
            https://static.rust-lang.org/rustup/dist/x86_64-unknown-linux-gnu/rustup-init &&
            chmod 755 "$work/rustup-init" &&
            "$work/rustup-init" -y --profile minimal --no-modify-path &&
            ln -sf "$home"/.cargo/bin/* /usr/local/bin/
    fi
    rustup toolchain install stable --profile minimal --component rustfmt,clippy &&
        rustup default stable &&
        rustup target add wasm32-unknown-unknown
}

# The version Red Acre's own hosts use, so wasm sizes compare.
wasm_opt() {
    fetch https://github.com/WebAssembly/binaryen/releases/download/version_130/binaryen-version_130-x86_64-linux.tar.gz \
        0a18362361ad05465118cd8eeb72edaeec89de6894bc283576ef4e07aa3babcc "$work/binaryen.tgz" &&
        tar -xzf "$work/binaryen.tgz" -C "$work" binaryen-version_130/bin/wasm-opt &&
        install -m 755 "$work/binaryen-version_130/bin/wasm-opt" /usr/local/bin/wasm-opt
}

# 0.10.0 drew the committed art, and the art scripts' --check compares bytes.
photocraft() {
    fetch https://github.com/storytold/photocraft/releases/download/v0.10.0/photocraft-0.10.0-linux-x86_64.tar.gz \
        c5d455785d9c2eaf695bf8e6327c4d6d23a39ddb956a6114f0c5b64326f984e1 "$work/photocraft.tgz" &&
        mkdir -p /opt/photocraft &&
        tar -xzf "$work/photocraft.tgz" -C /opt/photocraft --strip-components=1 &&
        ln -sf /opt/photocraft/bin/photocraft-cli /usr/local/bin/photocraft-cli
}

# ImageMagick and Pillow to read and check art; Xvfb and Mesa for CI's native
# pixel check (the packages its workflow installs).
packages() {
    DEBIAN_FRONTEND=noninteractive apt-get update -qq &&
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends imagemagick \
            xvfb xauth mesa-utils libgl1-mesa-dri libegl-mesa0 libegl1 libgl1 libx11-6 libxi6 \
            libxkbcommon0 libxcursor1 &&
        { python3 -m pip install -q pillow || python3 -m pip install -q --break-system-packages pillow; }
}

# The scripts start /usr/bin/chromium; the image has Chrome for Testing, and
# everything here runs as root, where Chrome needs --no-sandbox.
chromium() {
    [ -e /usr/bin/chromium ] && return 0
    printf '#!/bin/sh\nexec /usr/bin/google-chrome --no-sandbox "$@"\n' > /usr/bin/chromium &&
        chmod 755 /usr/bin/chromium
}

instructions() {
    mkdir -p "$home/.claude" && {
        cat <<'CLOUD'
# In a cloud session

You work in a cloud VM of the Claude app, not on Hermes's computer. The working agreement below holds, except where this part says otherwise.

- Work on the branch this session gave you. Commit there, run the gate, and push it; push again after each later change. Never push to main or any other branch, never rewrite a pushed commit, and never merge a pull request.
- `origin` is the repository's GitHub copy, not the primary. Foreman takes your pushed branch from GitHub, has it reviewed and lands it on Hermes's Git server; GitHub's main follows by itself.
- GitHub Actions does not run on these repositories, so you are the CI: run every step of `.github/workflows/ci.yml` as written before you push, and say in your report which steps passed.
- `committer` is not installed here: commit with plain `git commit`.
- The VM has 4 cores and 16 GB of memory. Run one cargo build or test suite at a time.
- Installed for you: Rust stable with rustfmt, clippy and the wasm32-unknown-unknown target; Node 22; wasm-opt 130; photocraft-cli 0.10.0 in /opt/photocraft/bin, where the art scripts look for it; Chrome for Testing as `chromium`; Python 3 with Pillow; ImageMagick 6 (`convert`); Xvfb and Mesa for CI's native pixel check.
- Red Acre's art is drawn in PhotoCraft by committed build scripts (README, "The art and the content pack"; `scripts/art/`, `scripts/lib/photocraft.mjs`). Look at what you draw before you call it done: scale the PNG up without smoothing (`convert in.png -filter point -resize 800% big.png`) and read the picture.
- No keys reach this VM, and it cannot reach Hermes's Git server, his accounts or his tailnet. A step that needs one of them is Foreman's: name it in your report.
- Name the branch and its last commit in your report.

CLOUD
        cat <<'AGREEMENT'
# Working agreement

This codebase is yours. Hermes, the owner, decides what it is for. How it is built is your call, and you will keep building on it. Read the code, form your own view, and do the work the way you think is best.

## How to work
- Understand before you change. Read the code the task touches, what calls it, and its tests.
- Get the architecture right. If the structure fights the task, fix the structure: merge duplicate code, rename, refactor, delete what no longer earns its place. Fix the problems you find on the way; you are the one who will live with them.
- Prefer the simplest design that works. Less code, fewer moving parts, plain names. Creative solutions are welcome when they make the code simpler.
- Your environment is yours too. Install tools, run servers, write throwaway scripts, rebuild from scratch. Add a project dependency when it clearly beats writing the code yourself, and say why in the commit.
- Prove it works. Test behavior at the boundaries. A bug fix comes with a test that failed before the fix. Run the repository's gate before you call it done.
- Finish the job. Errors, timeouts, flaky builds and missing tools are ordinary obstacles: diagnose them and work through them. Stop only for a decision that only Hermes can make.

## Records
- Commit each finished change with a message that says what changed and why: `committer "<message>" <paths>` (plain `git commit` where `committer` is missing). Work on the repository's main line unless the task names a branch.
- Push finished work to `origin` once its gate passes, when the task came to you directly. If another agent dispatched you, leave your commits in the repository: that agent reads the diff and pushes. `origin` is Hermes's own Git server and the primary copy. It mirrors each push to GitHub by itself, and some of those mirrors are public.
- A user-visible change gets a line in `CHANGELOG.md` under `## Unreleased`, in the same commit.
- `issues.md` at the repository root lists real problems you found but could not fix in this task, usually because they need Hermes's decision or are much bigger than the task. The commit that fixes one removes its entry.
- The code, the commit log, `CHANGELOG.md` and `issues.md` are the record. Do not leave notes, plans or hand-off files for later agents; they go stale and mislead the next one.

## Ask Hermes first
These reach real people or cannot be undone from the repository:
- Releasing, deploying, or publishing outside Git (a package, a post, a store listing).
- Making a private repository or private data public.
- Anything that touches production data or live user state.
- Decisions a repository's own `AGENTS.md` reserves for him.

Never put secrets, keys or tokens in code, logs, tests or commits.

## On a shared machine
When you work in a folder on Hermes's own computer instead of your own environment, other agents may be working there too:
- Changes you did not make belong to someone else. Leave them alone, so avoid `git stash`, `git reset --hard`, `git clean`, force pushes and branch switches.
- Remove files outside Git with `agent-trash`, not `rm`, so they can be recovered.
- Run one heavy build or test suite at a time. Exit 137 means the machine ran out of memory.

## Report
Write for a reader who has not seen your work. Lead with what changed and whether it works. Then the checks you ran, the bigger changes you made on your own judgment, and anything left. Plain words, short sentences. If Hermes must choose, give at most two options, with your pick and why.
AGREEMENT
    } > "$home/.claude/CLAUDE.md"
}

for step in rust wasm_opt photocraft packages; do
    ("$step" > "$work/$step.log" 2>&1 || { echo "setup: $step failed:"; tail -n 5 "$work/$step.log"; }) &
done
chromium || echo "setup: chromium failed"
instructions || echo "setup: instructions failed"
wait

echo "setup: $(cargo --version 2>&1); wasm32: $(rustup target list --installed 2>/dev/null | grep -c wasm32)"
echo "setup: $(wasm-opt --version 2>&1); $(photocraft-cli --version 2>&1)"
echo "setup: $(chromium --version 2>&1); $(convert -version 2>&1 | head -n 1); $(command -v xvfb-run)"
rm -rf "$work"
exit 0
