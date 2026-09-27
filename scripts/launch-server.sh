#!/bin/bash -p
# Pixi task wrapper for start-server / stop-server / restart-server.
# Prefers the root-owned installed controller; inference never runs in the sandbox.
# Works the same on plain Linux and in WSL; only the runtime location differs.
set -euo pipefail
action="${1:?Usage: launch-server.sh start|stop|restart}"
shift
case $action in
    start | stop | restart) ;;
    *) echo "Unknown action: $action" >&2; exit 2 ;;
esac
trusted=/usr/local/bin/${action}-server
if [[ -x $trusted ]]; then
    exec "$trusted" "$@"
fi
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
exec /usr/bin/python3 -I "$here/server.py" "$action" "$@"
