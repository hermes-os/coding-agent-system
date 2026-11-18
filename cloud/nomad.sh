#!/bin/bash
# The setup script of the "Nomad" cloud environment in the Claude app; the
# app runs it through the loader `cloud/app-script nomad` prints.
#
# Nomad's gate runs on Node 24; the cloud image has Node 22. This installs
# Node 24 ahead of it on Claude's PATH. nodejs.org is not on the cloud's
# network allowlist, so Node and the npm it ships with come from the npm
# registry, checked by hash.
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

node24() {
    fetch https://registry.npmjs.org/node-linux-x64/-/node-linux-x64-24.22.3.tgz \
        6d747cda21df616c78e9ed4f8a816cbacd25f24c1abb4d9aa26773d000e24bd9 "$work/node.tgz" &&
        fetch https://registry.npmjs.org/npm/-/npm-11.19.1.tgz \
            9f58bff01604cb1b14008fef14dceb14d836a49225e45c6c2e37de3be3e707f0 "$work/npm.tgz" &&
        mkdir -p /opt/node24/lib/node_modules/npm &&
        tar -xzf "$work/node.tgz" -C /opt/node24 --strip-components=1 &&
        tar -xzf "$work/npm.tgz" -C /opt/node24/lib/node_modules/npm --strip-components=1 &&
        ln -sf ../lib/node_modules/npm/bin/npm-cli.js /opt/node24/bin/npm &&
        ln -sf ../lib/node_modules/npm/bin/npx-cli.js /opt/node24/bin/npx &&
        shell_env 'export PATH=/opt/node24/bin:$PATH'
}

notes() {
    cat <<'NOTES'
## Nomad here

- This repository is public on GitHub, and so is every branch you push: no real names, email addresses, home folders, host names or private paths. Commit as `Hermes <267720388+hermes-os@users.noreply.github.com>`; git is set to that.
- Node 24 is at `/opt/node24` and first on your PATH. The `.mise.toml` that AGENTS.md names is not in the repository.
- Run the admin tests with `admin/.env.example`'s values exported: `set -a; . admin/.env.example; set +a`. Redis 7 and PostgreSQL 16 are installed but stopped; MySQL is not installed.
- `issues.md` lists the gate steps that fail on main (the admin lint, and admin tests that run no test). Check it before you take a failure as yours.
- Docker runs here, but the images Nomad installs and the content it downloads may be out of reach: the network allows package registries only.
NOTES
}

report() {
    echo "node $(/opt/node24/bin/node --version 2>&1), npm $(/opt/node24/bin/npm --version 2>&1); git as $(git config --global user.email)"
}

setup node24 public_identity instructions
