#!/bin/bash
# Executed by pixi ONLY after bubblewrap has established isolation.
set -euo pipefail
[[ "${OSINT_SANDBOX:-}" == 1 ]] || { echo 'Pi must run inside the OSINT sandbox.' >&2; exit 1; }
: "${CONDA_PREFIX:?Pixi environment is missing}"

/usr/bin/python3 -I - "$CONDA_PREFIX" <<'PY'
import json
import os
from pathlib import Path
import sys

bundled = Path(sys.argv[1]) / 'home/.pi'
live = Path.home() / '.pi'
agent = live / 'agent'
agent.mkdir(parents=True, exist_ok=True)
for source, target in [
    (bundled / 'agent/AGENTS.md', agent / 'AGENTS.md'),
    (bundled / 'agent/keybindings.json', agent / 'keybindings.json'),
    (bundled / 'web-search.json', live / 'web-search.json'),
]:
    if not target.exists():
        target.write_bytes(source.read_bytes())
# Link, not bind-mount: replacing environment files must not fail with EBUSY.
packages = agent / 'npm'
if not packages.exists() and not packages.is_symlink():
    packages.symlink_to(bundled / 'agent/npm', target_is_directory=True)
defaults = json.loads((bundled / 'agent/osint-defaults.json').read_text())
settings_file = agent / 'settings.json'
settings = defaults | (json.loads(settings_file.read_text()) if settings_file.exists() else {})
settings['packages'] = json.loads((bundled / 'agent/settings.json').read_text()).get('packages', [])
settings_file.write_text(json.dumps(settings, indent=2) + '\n')
os.chmod(settings_file, 0o600)
PY

# Decode argv without passing quotes, spaces, or shell metacharacters to Pixi's
# task shell. Keep Pi's original terminal stdin, not the Python heredoc above.
mapfile -d '' -t PI_ARGS < <(/usr/bin/python3 -I -c '
import base64, json, os, sys
args = json.loads(base64.b64decode(os.environ.get("OSINT_PI_ARGS", "W10=")))
sys.stdout.buffer.write(b"".join(arg.encode() + b"\0" for arg in args))
')
# agents/ is intentionally not Pi's conventional .agents/skills location.
exec pi --skill /workspace/agents "${PI_ARGS[@]}"
