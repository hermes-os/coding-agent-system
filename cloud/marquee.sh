#!/bin/bash
# The setup script of the "Marquee" cloud environment in the Claude app; the
# app runs it through the loader `cloud/app-script marquee` prints.
#
# Marquee needs Qt 6.8 or later and libmpv; Ubuntu 24.04 has Qt 6.4. So Qt,
# mpv, a GCC with C++23, CMake, Ninja and pkg-config come from conda-forge into
# /opt/qt, which Claude's shell activates. Mesa gives Qt Quick a software
# OpenGL for the offscreen tests.
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

apt_packages=(libgl1 libegl1 libgl1-mesa-dri libegl-mesa0 libxkbcommon0 fontconfig fonts-dejavu-core locales)
after_packages() { en_us_locale; }

qt() {
    conda /opt/qt 'qt6-main>=6.8' mpv cmake ninja pkg-config 'gxx_linux-64>=15' libgl-devel libegl-devel &&
        conda_shell /opt/qt
}

notes() {
    cat <<'NOTES'
## Marquee here

- This repository is public on GitHub, and so is every branch you push: no real names, email addresses, home folders, host names, drive or library names, and nothing from Hermes's own library. Commit as `Hermes <267720388+hermes-os@users.noreply.github.com>`; git is set to that.
- Build only the Linux app (CMake, Qt/QML). The Swift app (`Marquee/`, `Marquee.xcodeproj`, `Package.swift`) is a frozen reference: leave it alone.
- Qt 6, libmpv, GCC, CMake, Ninja and pkg-config come from conda-forge in `/opt/qt`, which your shell activates, so the gate in AGENTS.md runs as written. Mesa draws for the offscreen tests.
- Offscreen runs cannot render libmpv, and the VM has no display, GPU, remote or sound. Claims about playback, display, remote, audio or hardware decoding need the theater host: name them in your report for Foreman.
- Some tests fail here and pass on Hermes's hosts. Leave them as they are, and name each one in your report with its reason:
  - You run as root, so files made unreadable or read-only stay open to you: `tst_settings_store` (reportsWriteFailuresWhenSettingsAreReadOnly), `tst_catalog_bootstrap` (the unreadable-entries and unwritable-catalog cases), `tst_library_scanner` (the cannot-enumerate and partially-readable cases) and `tst_tv_scanner` (aTvRootWithUnreadableEntries...).
  - conda-forge's Qt calls the C library's `__xstat64`, which `tests/support/GuiThreadIoProbe.hpp` does not catch, so `tst_unavailable_root` sees no calls and fails its three cases.
  - Timing cases can fail when the VM is busy, for example `tst_media_details` aRowScrolledOutMidFadeComesBackAtRest. Run one again by itself before you call it a fault.
NOTES
}

report() {
    set +u; . "$home/.bashrc"
    echo "$(qmake6 -query QT_VERSION 2>&1 || qmake -query QT_VERSION 2>&1); mpv $(pkg-config --modversion mpv 2>&1)"
    echo "$(${CXX:-c++} --version 2>&1 | head -n 1); $(cmake --version 2>&1 | head -n 1); git as $(git config --global user.email)"
}

setup qt public_identity instructions
