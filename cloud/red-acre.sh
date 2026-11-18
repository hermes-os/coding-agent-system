#!/bin/bash
# The setup script of the "Red Acre" cloud environment in the Claude app; the
# app runs it through the loader `cloud/app-script red-acre` prints.
#
# It adds what the cloud image lacks for Red Acre's gate and art: Rust's
# rustfmt, clippy and wasm32 target, wasm-opt, photocraft-cli where the art
# scripts look for it, a chromium command, Pillow, ImageMagick, and Xvfb with
# Mesa for CI's native pixel check (the packages its workflow installs).
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

apt_packages=(imagemagick xvfb xauth mesa-utils libgl1-mesa-dri libegl-mesa0 libegl1 libgl1 libx11-6 libxi6
    libxkbcommon0 libxcursor1)

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

pillow() {
    python3 -m pip install -q pillow || python3 -m pip install -q --break-system-packages pillow
}

wasm() { rust wasm32-unknown-unknown; }

notes() {
    cat <<'NOTES'
## Red Acre here

- Installed for you: Rust stable with rustfmt, clippy and the wasm32-unknown-unknown target; Node 22; wasm-opt 130; photocraft-cli 0.10.0 in /opt/photocraft/bin, where the art scripts look for it; Chrome for Testing as `chromium`; Python 3 with Pillow; ImageMagick 6 (`convert`); Xvfb and Mesa for CI's native pixel check.
- Red Acre's art is drawn in PhotoCraft by committed build scripts (README, "The art and the content pack"; `scripts/art/`, `scripts/lib/photocraft.mjs`). Look at what you draw before you call it done: scale the PNG up without smoothing (`convert in.png -filter point -resize 800% big.png`) and read the picture.
NOTES
}

report() {
    echo "$(cargo --version 2>&1); wasm32: $(rustup target list --installed 2>/dev/null | grep -c wasm32)"
    echo "$(wasm-opt --version 2>&1); $(photocraft-cli --version 2>&1)"
    echo "$(command chromium --version 2>&1); $(convert -version 2>&1 | head -n 1); $(command -v xvfb-run)"
}

setup wasm wasm_opt photocraft pillow chromium instructions
