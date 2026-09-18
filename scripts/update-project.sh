#!/bin/bash -p
# Trusted maintenance action for the Linux deployment: update code, then tools.
# This executes code from the repository, so a human runs it deliberately; the
# agent inside Pi cannot reach it. Inference runtime updates are separate.
set -euo pipefail
[[ "${OSINT_SANDBOX:-}" == 1 ]] && { echo 'Update the project outside Pi, in a WSL or Linux terminal.' >&2; exit 1; }
root=${OSINT_LINUX_PROJECT:-}
if [[ -z $root && -r /etc/osint-ai.json ]]; then
    root=$(/usr/bin/python3 -I -c 'import json;print(json.load(open("/etc/osint-ai.json"))["linux_project"])')
fi
root=${root:-$PWD}
[[ -d $root/.git ]] || { echo "No Git checkout at $root. Run this from the project root (plain Linux) or inside the WSL terminal created by the Windows installer." >&2; exit 1; }
git -C "$root" pull --ff-only
env -i HOME="$HOME" PATH=/usr/local/bin:/usr/bin:/bin \
    pixi install --locked -e default --manifest-path "$root/pixi.toml"
# Local inference is optional. When it is installed it is a second environment in
# the same checkout, so it is updated here too rather than left behind: models.ini
# and the inference recipes come from this repository. On the Windows deployment
# llama.cpp runs natively on Windows instead and has no environment here.
if [[ -d $root/.pixi/envs/llamacpp-binary-vulkan ]]; then
    env -i HOME="$HOME" PATH=/usr/local/bin:/usr/bin:/bin \
        pixi install --locked -e llamacpp-binary-vulkan --manifest-path "$root/pixi.toml"
fi
printf '\nLinux deployment updated. Close and reopen the chatbot to use the new tools.\n'
if [[ ! -d $root/.pixi/envs/llamacpp-binary-vulkan ]]; then
    printf 'Local inference is not installed here. pixi r start-server installs it when you first need it.\n'
fi
