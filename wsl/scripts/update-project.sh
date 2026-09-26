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
[[ -d $root/.git ]] || { echo "No Linux checkout at $root. Run the Windows installer first." >&2; exit 1; }
git -C "$root" pull --ff-only
env -i HOME="$HOME" PATH=/usr/local/bin:/usr/bin:/bin \
    pixi install --locked -e default --manifest-path "$root/pixi.toml"
printf '\nLinux deployment updated. Close and reopen the chatbot to use the new tools.\n'
printf 'Inference changes (pixi-recipes, models.ini) still need a maintainer to reinstall /opt/osint-ai/server.\n'
