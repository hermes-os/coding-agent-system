#!/bin/bash
# The setup script of the "Ashwren" cloud environment in the Claude app; the
# app runs it through the loader `cloud/app-script ashwren` prints.
#
# It adds what the cloud image lacks for Ashwren's gate: the .NET 9 SDK (from
# conda-forge into /opt/dotnet, which Claude's shell activates; Ubuntu 24.04
# has only .NET 8 and 10), Deno at the gates' pinned version, a chromium
# command, and a password on the image's PostgreSQL 16 for the live tests.
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

apt_packages=(libicu74)

dotnet_sdk() {
    conda /opt/dotnet 'dotnet=9.0' &&
        conda_shell /opt/dotnet &&
        shell_env 'export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1'
}

deno_pinned() {
    fetch https://github.com/denoland/deno/releases/download/v2.9.8/deno-x86_64-unknown-linux-gnu.zip \
        e890975bc2549807bbcc0b584ffafda72cc7c93349dd99c80483dd784f6c4609 "$work/deno.zip" &&
        python3 -m zipfile -e "$work/deno.zip" "$work/deno" &&
        install -m 755 "$work/deno/deno" /usr/local/bin/deno
}

# The live tests make and drop their own databases on one local server.
live_db() {
    local cluster
    cluster=$(pg_lsclusters -h 2>/dev/null | awk 'NR == 1 {print $1 " " $2}')
    [ -n "$cluster" ] || return 1
    pg_ctlcluster $cluster start &&
        su postgres -c "psql -q -c \"ALTER ROLE postgres PASSWORD 'postgres'\"" &&
        pg_ctlcluster $cluster stop &&
        shell_env "export ASHWREN_BLOGSTORE_TESTS='Host=127.0.0.1;Port=5432;Username=postgres;Password=postgres;Database=postgres'" \
            "export ASHWREN_COMMUNITY_TESTS='Host=127.0.0.1;Port=5432;Username=postgres;Password=postgres;Database=postgres'"
}

notes() {
    cat <<'NOTES'
## Ashwren here

- The .NET 9 SDK comes from conda-forge in `/opt/dotnet`, which your shell activates. Deno 2.9.8 is installed, Chrome for Testing is `chromium`, and Python 3 has pytest.
- For `Ashwren.Web.LiveTests` and the community gates, start PostgreSQL with `service postgresql start`. `ASHWREN_BLOGSTORE_TESTS` and `ASHWREN_COMMUNITY_TESTS` already point at it; the tests make and drop their own databases there.
- The community gates pin the Chromium build of Hermes's own host (`.agents/gates/gate_pins.py`). Chrome for Testing is a different build, so those gates stop at the pin check here: say so in your report, and Foreman runs them. Never change a pin to make a gate pass.
- No production database, guide file or live site is reachable from here. `validate`, `ingest` and `replace` run only against the local PostgreSQL; production runs are Foreman's.
NOTES
}

report() {
    set +u; . "$home/.bashrc"
    echo "dotnet $(dotnet --version 2>&1); $(deno --version 2>&1 | head -n 1)"
    echo "$(command chromium --version 2>&1); $(psql --version 2>&1)"
}

setup dotnet_sdk deno_pinned live_db chromium instructions
