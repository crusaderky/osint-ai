#!/bin/bash -p
# Start the OSINT AI assistant. One launcher for both deployments; only the
# first argument differs:
#
#   --native   use workspace/ of this checkout (plain Linux)
#   --wsl      use workspace/ of the Windows checkout mounted at /mnt/osint-ai
#
# Everything after that argument is passed to Pi.
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
if [[ $1 == --native && -f "$here/pixi.toml" ]]; then
    # Started from a checkout: that checkout is the project root. From the
    # installed location the launcher sets OSINT_PROJECT_ROOT itself.
    export OSINT_PROJECT_ROOT="${OSINT_PROJECT_ROOT:-$here}"
fi
trusted=/usr/local/lib/osint-ai/sandbox.py
if [[ -x $trusted ]]; then
    exec /usr/bin/python3 -I "$trusted" "$@"
fi
exec /usr/bin/python3 -I "$here/sandbox.py" "$@"
