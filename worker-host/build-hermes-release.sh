#!/usr/bin/env bash
# Build one trusted Hermes runtime for the worker adapter (libexec/.../agent-hermes-worker):
#   /opt/agent-worker-hermes/releases/<commit>/source        git archive of the commit
#   /opt/agent-worker-hermes/releases/<commit>/source/.venv  its own packages (uv.lock, frozen)
#   /opt/agent-worker-hermes/python/cpython-<PY>-linux-x86_64-gnu  the interpreter
# Everything ends root:root and not group/other writable, because the adapter refuses anything
# else. A release is built beside the live one, so running workers keep theirs; the adapter's
# TRUSTED_HERMES_SOURCE and bootstrap.sh RELEASE decide which one new runs use.
# Upstream Hermes runs on Python 3.14 (its dependencies are gated on python_version >= '3.14'),
# so a release of a 2026-10 or later commit needs PY=3.14.x.
#
# Usage: build-hermes-release.sh <hermes-agent checkout> <commit>
# Env:   PY (default 3.14.7), EXTRAS (default "anthropic doc-extract uvloop")
set -euo pipefail

die() { printf 'build-hermes-release: %s\n' "$*" >&2; exit 1; }
[[ $# -eq 2 ]] || die "usage: build-hermes-release.sh <hermes-agent checkout> <commit>"
CHECKOUT=$1
REL=$(git -C "$CHECKOUT" rev-parse --verify "$2^{commit}") || die "unknown commit $2"
PY=${PY:-3.14.7}
EXTRAS=${EXTRAS:-anthropic doc-extract uvloop}
MINOR=${PY%.*}
ROOT=/opt/agent-worker-hermes
PYDIR=$ROOT/python/cpython-$PY-linux-x86_64-gnu
ALIAS=$ROOT/python/cpython-$MINOR-linux-x86_64-gnu
D=$ROOT/releases/$REL
UV=$(command -v uv) || die "uv is not on PATH"

[[ -e $D ]] && die "$D exists; a release is never rebuilt in place"

if [[ ! -x $PYDIR/bin/python$MINOR ]]; then
  # The worker interpreter is a root-owned copy of uv's managed CPython, like the 3.11 one.
  src=$("$UV" python find --managed-python --no-config "$PY") || die "uv has no managed CPython $PY (uv python install $PY)"
  src=$(dirname "$(dirname "$(readlink -f "$src")")")
  [[ $(basename "$src") == cpython-$PY-linux-x86_64-gnu ]] || die "unexpected interpreter dir $src"
  sudo -n cp -a --no-preserve=ownership "$src" "$PYDIR.partial"
  sudo -n chown -R root:root "$PYDIR.partial"
  sudo -n chmod -R go-w,go+rX "$PYDIR.partial"
  sudo -n mv -T "$PYDIR.partial" "$PYDIR"
fi
if [[ ! -L $ALIAS ]]; then
  sudo -n ln -sT "$PYDIR" "$ALIAS"
fi
[[ $(readlink -f "$ALIAS") == "$PYDIR" ]] || die "$ALIAS does not point at $PYDIR"

# Built as the caller (uv uses the caller's cache), then handed to root. Editable installs record
# absolute paths, so the build happens at the final path; nothing points at it until the adapter does.
sudo -n install -d -o "$(id -u)" -g "$(id -g)" -m 755 "$D" "$D/source"
git -C "$CHECKOUT" archive "$REL" | tar -x -C "$D/source"
extra_args=()
for extra in $EXTRAS; do extra_args+=(--extra "$extra"); done
(
  cd "$D/source"
  # copy, never hardlink: the chown below would otherwise change the caller's cache files too.
  env UV_NO_CONFIG=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT="$D/source/.venv" \
    "$UV" sync --frozen --no-dev --compile-bytecode --python "$ALIAS/bin/python$MINOR" "${extra_args[@]}"
  # Workers cannot write the root-owned tree, so compile the source bytecode now.
  "$D/source/.venv/bin/python" -m compileall -q -j 0 -x '/(\.venv|tests|web|node_modules)/' . >/dev/null
)
sudo -n chown -R root:root "$D"
# Readable by everyone (workers run as agent-worker); wheels and uv can leave owner-only files.
sudo -n chmod -R u+w,go-w,go+rX "$D"
left=$(sudo -n find "$D" "$PYDIR" \( -not -user root -o -not -group root -o -perm /022 -o -not -perm -o+r \) -not -type l -print -quit)
[[ -z $left ]] || die "not root-owned, not readable, or writable by others: $left"
printf 'built %s\n' "$D"
