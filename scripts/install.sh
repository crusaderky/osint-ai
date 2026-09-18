#!/bin/bash
# `pixi r install` is a user-level registration/check step, never a root hook.
set -euo pipefail
if [[ "${OSINT_SANDBOX:-}" == 1 ]]; then
    echo 'Installation changes require the Windows installer, outside Pi.' >&2
    exit 1
fi
if [[ ! -x /usr/local/lib/osint-ai/bwrap-pi.sh || ! -x /usr/local/bin/osint-pi ]]; then
    echo 'First run Install.cmd on Windows. It installs the trusted WSL launchers.' >&2
    exit 1
fi
python3 -I /usr/local/lib/osint-ai/mount-workspace.py --check
printf '\nInstallation ready. From any directory in the OSINT AI terminal:\n'
printf '  osint-pi       Start sandboxed chatbot; use /login for hosted providers.\n'
printf '  start-server   Start local CUDA inference, then use /models inside Pi.\n'
printf '  stop-server    Stop local inference.\n'
printf '\nSkills are stored in /workspace/agents on your Windows drive.\n'
