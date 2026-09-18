#!/bin/bash -p
# Start the OSINT AI assistant. One launcher for both deployments; only the
# first argument differs:
#
#   --native   use the workspace/ of this checkout (plain Linux)
#   --wsl      use the workspace/ of the Windows checkout mounted at /mnt/osint-ai
#
# Both mount the whole checkout at /osint-ai inside the sandbox and start Pi in
# /osint-ai/workspace, so `git status` works from the assistant's own directory.
# Everything after that first argument is passed to Pi.
#
# The root-owned copy in /usr/local/lib/osint-ai wins when it is there, so an
# installed PC runs the code it installed rather than a checkout somebody
# edited. Nothing runs before containment except this lookup.
set -euo pipefail
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
case "${1:-}" in
    --native | --wsl) ;;
    *)
        echo "Usage: bwrap-pi.sh --native|--wsl [pi arguments...]" >&2
        exit 2
        ;;
esac
# Started from a checkout: this script sits in <checkout>/scripts, so the
# checkout that holds pixi.toml is one level up. From the installed location
# there is no pixi.toml above the launcher and the launcher sets the root itself.
if [[ $1 == --native && -f "$here/../pixi.toml" ]]; then
    export OSINT_PROJECT_ROOT="${OSINT_PROJECT_ROOT:-$(cd -- "$here/.." && pwd)}"
fi
trusted=/usr/local/lib/osint-ai/sandbox.py
if [[ -x $trusted ]]; then
    exec /usr/bin/python3 -I "$trusted" "$@"
fi
exec /usr/bin/python3 -I "$here/sandbox.py" "$@"
