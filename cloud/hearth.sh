#!/bin/bash
# The setup script of the "Hearth" cloud environment in the Claude app; the
# app runs it through the loader `cloud/app-script hearth` prints.
#
# Hearth's CI runs on Ubuntu 24.04, like the session's VM: this installs what
# its workflow installs (Rust's rustfmt and clippy, Qt 6 with WebEngine and the
# QML modules) and the en_US.UTF-8 locale the gate sets.
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

apt_packages=(cmake libgl-dev qt6-base-dev qt6-webengine-dev qt6-declarative-dev qt6-declarative-dev-tools
    qt6-qpa-plugins qml6-module-qt-labs-folderlistmodel qml6-module-qtqml qml6-module-qtqml-models
    qml6-module-qtqml-workerscript qml6-module-qtquick qml6-module-qtquick-controls qml6-module-qtquick-dialogs
    qml6-module-qtquick-layouts qml6-module-qtquick-templates qml6-module-qtquick-window qml6-module-qttest
    qml6-module-qtwebengine locales)

after_packages() {
    sed -i 's/^# *en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen && locale-gen en_US.UTF-8
}

notes() {
    cat <<'NOTES'
## Hearth here

- The gate in AGENTS.md runs here as written. Its cargo steps are `--offline`: fetch the crates first with `cargo fetch --manifest-path rebuild/core/Cargo.toml` and `cargo fetch --manifest-path rebuild/ffi/Cargo.toml`.
- This VM is Ubuntu 24.04 with its Qt 6.4.2, the same as CI. Hermes's own hosts run a newer Qt; a QML change that relies on Qt after 6.4 fails CI.
- The VM has no display, GPU or sound, and no ZIM library or Kiwix server of Hermes's. Claims that need them are Foreman's to check: name them in your report.
NOTES
}

report() {
    echo "$(cargo --version 2>&1); $(cargo clippy --version 2>&1)"
    echo "$(/usr/lib/qt6/bin/qmllint --version 2>&1); $(locale -a 2>/dev/null | grep -c -i 'en_US.utf8') en_US.UTF-8 locale"
}

setup rust instructions
