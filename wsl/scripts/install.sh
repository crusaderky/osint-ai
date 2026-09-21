#!/bin/bash
# `pixi r install` is a user-level installation check, never a root hook.
set -euo pipefail
if [[ "${OSINT_SANDBOX:-}" == 1 ]]; then
    echo 'Installation changes require the Windows installer, outside Pi.' >&2
    exit 1
fi
if [[ ! -x /usr/local/lib/osint-ai/bwrap-pi.sh || ! -x /usr/local/bin/osint-pi-wsl ]]; then
    echo 'First run wsl\Install.cmd on Windows. It installs the trusted WSL launchers.' >&2
    exit 1
fi
if [[ -d /mnt/osint-ai ]]; then
    python3 -I /usr/local/lib/osint-ai/mount-workspace.py --check
    printf '\nInstallation ready. Start the chatbot with the "OSINT AI Terminal" desktop icon, or:\n'
    printf '  osint-terminal   Start local inference, then open the chatbot.\n'
    printf '  osint-pi-wsl     Open the chatbot only.\n'
else
    printf '\nPlain Linux checkout. From the project root:\n'
    printf '  pixi r osint-pi        Start the chatbot in workspace/\n'
    printf '  pixi r restart-server  Start local inference first if you want it\n'
fi
printf '\nSkills live in workspace/.agents/skills; the chatbot edits them for you.\n'
