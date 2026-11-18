#!/bin/bash
# The setup script of the "Kestrel" cloud environment in the Claude app; the
# app runs it through the loader `cloud/app-script kestrel` prints.
#
# It adds what the cloud image lacks for Kestrel's gate and CI: Python 3.13
# and 3.10 environments with CI's pytest, and a chromium command for the
# report's browser test.
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

# Plain sans fonts, so the browser test measures text as a stock Ubuntu does.
apt_packages=(fontconfig fonts-dejavu-core fonts-liberation)

# CI runs pytest 9.1.1 on Python 3.10 and 3.13. uv fetches each Python from
# its GitHub release.
pythons() {
    local version
    for version in 3.13 3.10; do
        uv venv -q --python "$version" "/opt/kestrel/py$version" &&
            uv pip install -q --python "/opt/kestrel/py$version/bin/python" pytest==9.1.1 || return 1
    done
}

notes() {
    cat <<'NOTES'
## Kestrel here

- The gate's `.venv` is ready at `/opt/kestrel/py3.13`, with CI's pytest 9.1.1: link it with `ln -sfn /opt/kestrel/py3.13 .venv` (git ignores `.venv/`), then run `.venv/bin/python -m pytest`. CI also runs the tests on Python 3.10: `/opt/kestrel/py3.10/bin/python -m pytest`.
- Chrome for Testing is installed as `chromium` and `google-chrome`, for the report's browser test.
- The district data in `data/` is what the repository holds. Live district sites can be out of reach: the network allows package registries only.
NOTES
}

report() {
    echo "$(/opt/kestrel/py3.13/bin/python -m pytest --version 2>&1) on $(/opt/kestrel/py3.13/bin/python --version 2>&1)"
    echo "$(/opt/kestrel/py3.10/bin/python --version 2>&1); $(command chromium --version 2>&1)"
}

setup pythons chromium instructions
