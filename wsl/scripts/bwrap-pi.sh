#!/bin/bash -p
# WSL adaptation of pixi-llm-recipes/scripts/bwrap-pi.sh.
# Installed copy is authoritative; no manifest/build code runs before containment.
set -euo pipefail
exec /usr/bin/python3 -I /usr/local/lib/osint-ai/sandbox.py "$@"
