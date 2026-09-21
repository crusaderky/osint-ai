#!/bin/bash -p
# Pixi task wrapper for `pixi r osint-pi` and `pixi r osint-pi-wsl`.
# It only locates the real launcher: Pi always starts inside bubblewrap.
set -euo pipefail
mode="${1:?Usage: launch-pi.sh native|wsl [pi arguments...]}"
shift
case $mode in
    native) trusted=/usr/local/bin/osint-pi ;;
    wsl) trusted=/usr/local/bin/osint-pi-wsl ;;
    *) echo "Unknown mode: $mode (expected native or wsl)" >&2; exit 2 ;;
esac
if [[ -x $trusted ]]; then
    exec "$trusted" "$@"
fi
# Plain Linux development checkout without the root-owned installation.
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
exec /usr/bin/python3 -I "$here/sandbox.py" "--$mode" "$@"
