#!/bin/bash
# `pixi r install` reports what is set up, what is missing, and how to start.
# It changes nothing. On Windows the installer does the installing; on Linux the
# README gives you the two commands, because you do not need a script to run
# them.
set -euo pipefail
if [[ "${OSINT_SANDBOX:-}" == 1 ]]; then
    echo 'Run the installation check in a terminal, not inside the assistant.' >&2
    exit 1
fi
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
root=$(cd -- "$here/.." && pwd)
wsl_deployment=0
if [[ -r /etc/osint-ai.json ]]; then
    # Running from the installed copy inside the private WSL distribution: the
    # checkout that matters is the one named in the config, not /usr/local.
    wsl_deployment=1
    root=$(/usr/bin/python3 -I -c 'import json;print(json.load(open("/etc/osint-ai.json"))["linux_project"])')
fi
missing=0
say() { printf '  %-9s %s\n' "$1" "$2"; }
need() {
    say MISSING "$1"
    missing=1
}

printf 'Runtime\n'
if [[ -x /usr/bin/bwrap ]]; then
    say ok "bubblewrap"
else
    need "bubblewrap. Install the 'bubblewrap' package, and on Ubuntu also load the profile in docs/development.md so an unprivileged user may start a sandbox."
fi
if command -v pixi >/dev/null; then
    say ok "pixi ($(command -v pixi))"
else
    need "pixi. See https://pixi.sh"
fi
if [[ -x $root/.pixi/envs/default/bin/pi ]]; then
    say ok "assistant environment ($root)"
else
    need "assistant environment. Run: pixi install --locked -e default --manifest-path $root/pixi.toml"
fi
if [[ -d $root/workspace/.agents/skills ]]; then
    say ok "workspace ($root/workspace)"
else
    need "$root/workspace/.agents/skills"
fi

printf '\nDeployment\n'
if ((wsl_deployment)); then
    say ok "Windows deployment (private WSL distribution)"
    if out=$(/usr/local/lib/osint-ai/mount-workspace.py --check 2>&1); then
        say ok "Windows checkout mounted at /mnt/osint-ai"
    else
        need "$out"
    fi
else
    say none "plain Linux checkout: no local inference. Use a hosted model with /login, or build /opt/osint-ai/server (docs/development.md)."
fi

printf '\nStart it\n'
if ((wsl_deployment)); then
    printf '  OSINT AI Terminal   desktop icon: local inference, then the assistant\n'
    printf '  osint-pi-wsl        the assistant on its own\n'
else
    printf '  pixi r osint-pi        assistant, working in %s/workspace\n' "$root"
    printf '  pixi r restart-server  local inference, once /opt/osint-ai/server exists\n'
fi
printf '\nSkills live in workspace/.agents/skills. The assistant edits them for you.\n'
if ((missing)); then
    printf '\nFix the lines marked MISSING before starting.\n'
    exit 1
fi
