#!/usr/bin/env bash
# setup.sh — build the workbench image and set up a run profile on this host.
#
#   ./setup.sh worker     the repository worker (the host with the kanban board)
#   ./setup.sh author     the study-guide author (the guide host)
#   ./setup.sh links      link Hermes's working agreement as ~/AGENTS.md and ~/.claude/CLAUDE.md
#
# A profile is described by profiles/<name>/: intro.md opens its SOUL.md,
# profile.json holds its description, skills and config. The worker's SOUL.md is
# its intro followed by working-agreement.md. Running setup again brings a
# profile back to exactly what this repository says.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
cmd=${1:-}

link_rules() {
    mkdir -p "$HOME/.claude"
    ln -sfn "$here/working-agreement.md" "$HOME/AGENTS.md"
    ln -sfn "$here/working-agreement.md" "$HOME/.claude/CLAUDE.md"
    echo "linked ~/AGENTS.md and ~/.claude/CLAUDE.md to $here/working-agreement.md"
}

build_image() {
    podman build -q -t localhost/workbench:latest -f "$here/workbench/Containerfile" "$here/workbench" > /dev/null
    echo "built localhost/workbench:latest ($(podman images localhost/workbench:latest --format '{{.Size}}'))"
}

setup_profile() {
    local name=$1 dir="$here/profiles/$1"
    [ -f "$dir/profile.json" ] || { echo "setup: no profile named '$name' in $here/profiles" >&2; exit 1; }
    command -v hermes > /dev/null || { echo "setup: hermes is not installed on this host" >&2; exit 1; }
    mkdir -p "$HOME/.cache/workbench" "$HOME/workbench"
    build_image

    local home="$HOME/.hermes/profiles/$name"
    if [ ! -d "$home" ]; then
        hermes profile create "$name" --no-alias --no-skills \
            --description "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["description"])' "$dir/profile.json")" > /dev/null
        echo "created profile $name"
    fi

    python3 - "$dir/profile.json" <<'PY' | while IFS=$'\t' read -r key value; do
import json, sys
for key, value in json.load(open(sys.argv[1]))["config"].items():
    # hermes config set keeps string settings verbatim; anything else goes as JSON.
    print(f"{key}\t{value if isinstance(value, str) else json.dumps(value)}")
PY
        hermes -p "$name" config set "$key" "$value" > /dev/null
    done
    echo "applied $(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["config"]))' "$dir/profile.json") settings"

    # Hermes takes the docker CLI before podman when both are installed. Workers run on podman.
    hermes -p "$name" config set HERMES_DOCKER_BINARY "$(command -v podman)" > /dev/null

    if [ "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("agreement", False))' "$dir/profile.json")" = True ]; then
        cat "$dir/intro.md" "$here/working-agreement.md" > "$home/SOUL.md"
    else
        cp "$dir/intro.md" "$home/SOUL.md"
    fi
    echo "wrote $home/SOUL.md"

    local bundled="$HOME/.hermes/hermes-agent/skills"
    rm -rf "$home/skills" && mkdir -p "$home/skills"
    for skill in $(python3 -c 'import json,sys; print(" ".join(json.load(open(sys.argv[1])).get("skills", [])))' "$dir/profile.json"); do
        src=$(find "$bundled" -mindepth 2 -maxdepth 2 -type d -name "$skill" | head -n 1)
        [ -n "$src" ] || { echo "setup: no bundled skill named $skill" >&2; exit 1; }
        cp -r "$src" "$home/skills/$skill"
    done
    echo "skills: $(ls "$home/skills" | tr '\n' ' ')"
}

case "$cmd" in
    links) link_rules ;;
    worker | author) setup_profile "$cmd" ;;
    *) echo "usage: $0 worker | author | links" >&2; exit 2 ;;
esac
