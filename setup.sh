#!/usr/bin/env bash
# setup.sh — set up the workbench on this host.
#
#   ./setup.sh <profile>     build the image and set up a run profile from profiles/<profile>/
#   ./setup.sh repo <name>   make, or bring up to date, the workers' clean clone ~/workbench/<name>
#   ./setup.sh links         link the working agreement as ~/AGENTS.md and ~/.claude/CLAUDE.md
#
# A profile is described by profiles/<name>/: intro.md opens its SOUL.md and
# profile.json holds its description, skills and config. With "agreement": true
# the SOUL.md is the intro followed by working-agreement.md. Running setup again
# brings a profile back to exactly what this repository says.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
forge=${WORKBENCH_FORGE:-git@git.imhermes.dev:hermes}

usage() {
    echo "usage: $0 <profile> | repo <name> | links" >&2
    echo "profiles: $(ls "$here/profiles" | tr '\n' ' ')" >&2
    exit 2
}

# One value out of a profile.json: field <file> <python expression over d>
field() {
    python3 -c 'import json, sys; d = json.load(open(sys.argv[1])); print(eval(sys.argv[2]))' "$1" "$2"
}

link_rules() {
    mkdir -p "$HOME/.claude"
    ln -sfn "$here/working-agreement.md" "$HOME/AGENTS.md"
    ln -sfn "$here/working-agreement.md" "$HOME/.claude/CLAUDE.md"
    echo "linked ~/AGENTS.md and ~/.claude/CLAUDE.md to $here/working-agreement.md"
}

# Workers never see Hermes's own working copies. They get a clean clone from
# the Git server, and kanban puts each task's worktree under its .worktrees/.
workbench_repo() {
    local name=$1 dir="$HOME/workbench/$1"
    if [ ! -d "$dir/.git" ]; then
        mkdir -p "$HOME/workbench"
        git clone -q "$forge/$name.git" "$dir"
        echo ".worktrees/" >> "$dir/.git/info/exclude"
    fi
    git -C "$dir" pull -q --ff-only
    echo "$dir is at $(git -C "$dir" log -1 --format='%h %s')"
}

build_image() {
    podman build -q -t localhost/workbench:latest -f "$here/workbench/Containerfile" "$here/workbench" > /dev/null
    echo "built localhost/workbench:latest ($(podman images localhost/workbench:latest --format '{{.Size}}'))"
}

setup_profile() {
    local name=$1 spec="$here/profiles/$1/profile.json" intro="$here/profiles/$1/intro.md"
    [ -f "$spec" ] || usage
    command -v hermes > /dev/null || { echo "setup: hermes is not installed on this host" >&2; exit 1; }
    mkdir -p "$HOME/.cache/workbench" "$HOME/workbench"
    build_image

    local home="$HOME/.hermes/profiles/$name"
    if [ ! -d "$home" ]; then
        hermes profile create "$name" --no-alias --no-skills --description "$(field "$spec" 'd["description"]')" > /dev/null
        echo "created profile $name"
    fi

    # hermes config set keeps string settings verbatim; anything else goes as JSON.
    python3 - "$spec" <<'PY' | while IFS=$'\t' read -r key value; do
import json, sys
for key, value in json.load(open(sys.argv[1]))["config"].items():
    print(f"{key}\t{value if isinstance(value, str) else json.dumps(value)}")
PY
        hermes -p "$name" config set "$key" "$value" > /dev/null
    done
    echo "applied $(field "$spec" 'len(d["config"])') settings"

    # Hermes takes the docker CLI before podman when both are installed. The workbench runs on podman.
    hermes -p "$name" config set HERMES_DOCKER_BINARY "$(command -v podman)" > /dev/null

    if [ "$(field "$spec" 'd.get("agreement", False)')" = True ]; then
        cat "$intro" "$here/working-agreement.md" > "$home/SOUL.md"
    else
        cp "$intro" "$home/SOUL.md"
    fi
    echo "wrote $home/SOUL.md"

    local bundled="$HOME/.hermes/hermes-agent/skills" skill src
    rm -rf "$home/skills" && mkdir -p "$home/skills"
    for skill in $(field "$spec" '" ".join(d.get("skills", []))'); do
        src=$(find "$bundled" -mindepth 2 -maxdepth 2 -type d -name "$skill" | head -n 1)
        [ -n "$src" ] || { echo "setup: no bundled skill named $skill" >&2; exit 1; }
        cp -r "$src" "$home/skills/$skill"
    done
    echo "skills: $(ls "$home/skills" | tr '\n' ' ')"
}

case "${1:-}" in
    "" | -h | --help) usage ;;
    links) link_rules ;;
    repo) [ -n "${2:-}" ] || usage; workbench_repo "$2" ;;
    *) setup_profile "$1" ;;
esac
