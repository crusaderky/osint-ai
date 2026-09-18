#!/bin/bash
# `pixi r install` reports what is set up, what is missing, and how to start.
# It changes nothing. On Windows the installer does the installing; on Linux the
# README lists the commands, because you do not need a script to run them. The
# one root step a Linux install has - the AppArmor profile for the bubblewrap this
# project pins - is scripts/install-apparmor.sh, run by the same task.
set -euo pipefail
if [[ "${OSINT_SANDBOX:-}" == 1 ]]; then
    echo 'Run the installation check in a terminal, not inside the assistant.' >&2
    exit 1
fi
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
root=$(cd -- "$here/.." && pwd)
wsl_deployment=0
if [[ -n ${OSINT_PROJECT_ROOT:-} ]]; then
    # The same override scripts/sandbox.py accepts.
    root=$OSINT_PROJECT_ROOT
elif [[ -r /etc/osint-ai.json ]]; then
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

# The sandbox runs the bubblewrap this project's lockfile pins, not whatever the
# distribution happens to ship, so this is the binary that has to be there and be
# allowed to create a user namespace.
bwrap=$root/.pixi/envs/default/bin/bwrap

printf 'Runtime\n'
if [[ ! -x $bwrap ]]; then
    need "bubblewrap in the assistant environment ($bwrap). Run: pixi install --locked -e default --manifest-path $root/pixi.toml. The sandbox runs that binary, not /usr/bin/bwrap."
elif out=$("$bwrap" --ro-bind / / --dev /dev --proc /proc --tmpfs /tmp --unshare-all --share-net /bin/true 2>&1); then
    say ok "bubblewrap $("$bwrap" --version 2>/dev/null || true) ($bwrap, pinned by pixi.lock)"
else
    # Two different failures look the same here, and the fix is not the same.
    if [[ -r /proc/sys/kernel/apparmor_restrict_unprivileged_userns ]] &&
        [[ $(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns) == 1 ]]; then
        need "bubblewrap cannot start a sandbox: ${out:-$bwrap exited nonzero}. This Ubuntu only grants a user namespace to a program with an AppArmor profile, and the profile has to name $bwrap: run pixi r install-apparmor."
    else
        need "bubblewrap cannot start a sandbox: ${out:-$bwrap exited nonzero}. This machine refuses unprivileged user namespaces outright (kernel setting, container, or another security module); an AppArmor profile would not change that."
    fi
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
if [[ -d $root/.git && ! -L $root/.git ]]; then
    say ok "Git checkout ($root)"
else
    need "$root is not a Git checkout: the assistant cannot run 'git status'. Clone the project with 'git clone'."
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
    say ok "plain Linux checkout ($root)"
fi

# Local inference is optional and separate from the assistant. Plain Linux runs it
# in this checkout's own Pixi environment, which `pixi r start-server` installs the
# first time it is needed. The Windows deployment runs llama.cpp natively on
# Windows instead, outside WSL, so there the question is whether that server
# answers - the assistant talks to the Windows host, never to a server here.
printf '\nLocal inference (optional)\n'
health() {
    # No proxy: a corporate proxy must not answer for the local server.
    /usr/bin/python3 -I - "$1" <<'PY'
import json, sys, urllib.request
try:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    ok = json.load(opener.open(f"{sys.argv[1]}/health", timeout=2)).get("status") == "ok"
except Exception:
    ok = False
sys.exit(0 if ok else 1)
PY
}
if ((wsl_deployment)); then
    # The launcher owns this address, so the check asks it instead of keeping a
    # second copy of the rule that resolves the Windows host.
    launcher=/usr/local/lib/osint-ai/sandbox.py
    [[ -f $launcher ]] || launcher=$root/scripts/sandbox.py
    url=$(/usr/bin/python3 -I "$launcher" --wsl --inference-url 2>/dev/null || true)
    url=${url:-http://127.0.0.1:8080}
    if health "$url"; then
        say running "$url (llama.cpp runs on Windows; the desktop icons control it)"
    else
        say stopped "nothing answers on $url. Use the 'Start llama.cpp' desktop icon."
        printf '           If it still fails, the Windows firewall rule that admits the WSL network is\n           missing: rerun the Windows installer and approve the permission prompt.\n'
    fi
else
    server=$root/.pixi/envs/llamacpp-binary-vulkan/bin/llama-server
    if [[ -x $server ]]; then
        say ok "llama.cpp ($server; Vulkan when a GPU answers, CPU otherwise)"
        if health http://127.0.0.1:8080; then
            say running "127.0.0.1:8080. The assistant lists its models with /model."
        else
            say stopped "start it with: pixi r start-server"
        fi
    else
        say optional "llama.cpp is not installed here yet. pixi r start-server installs it."
        printf '           Until then the assistant uses a hosted model: run it and type /login.\n'
    fi
fi

printf '\nAssistant state\n'
say ok "credentials, sessions and settings: ${OSINT_STATE_DIR:-$HOME/.local/state/osint-ai}/agent-home"

printf '\nStart it\n'
if ((wsl_deployment)); then
    printf '  OSINT AI Terminal         desktop icon: the assistant, and whether local inference answers\n'
    printf '  Start/Stop llama.cpp      desktop icons: local inference on the Windows side\n'
    printf '  osint-pi-wsl              the assistant on its own\n'
else
    printf '  pixi r osint-pi        assistant, working in %s/workspace (mounted at /osint-ai/workspace)\n' "$root"
    printf '  pixi r start-server    local inference on 127.0.0.1:8080, which /model then lists\n'
fi
printf '\nSkills live in workspace/.agents/skills, that is /osint-ai/workspace/.agents/skills inside the assistant. The assistant edits them for you.\n'
if ((missing)); then
    printf '\nFix the lines marked MISSING before starting.\n'
    exit 1
fi
