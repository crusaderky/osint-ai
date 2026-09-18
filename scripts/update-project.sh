#!/bin/bash -p
# Trusted maintenance action for the Linux deployment: bring the checkout up to
# date, then its tools.
#
# On plain Linux a human runs this in the project root checkout. On the Windows
# deployment the **Update OSINT AI** desktop icon runs it, as the osint user,
# before it refreshes the root-owned runtime from this checkout and updates the
# Windows one; see windows/update-installation.sh. It executes code from the
# repository, so the agent inside Pi cannot reach it.
#
# The branch rule - main fast-forwarded, staging fast-forwarded and then given
# main to merge - lives in scripts/git-branches.sh, which the Windows updater
# uses for the Windows checkout as well: one implementation, both checkouts.
set -euo pipefail
[[ "${OSINT_SANDBOX:-}" == 1 ]] && { echo 'Update the project outside Pi, in a WSL or Linux terminal.' >&2; exit 1; }
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
root=${OSINT_LINUX_PROJECT:-}
if [[ -z $root && -r /etc/osint-ai.json ]]; then
    root=$(/usr/bin/python3 -I -c 'import json;print(json.load(open("/etc/osint-ai.json"))["linux_project"])')
fi
root=${root:-$PWD}
[[ -d $root/.git ]] || { echo "No Git checkout at $root. Run this from the project root (plain Linux) or inside the WSL terminal created by the Windows installer." >&2; exit 1; }
source "$here/git-branches.sh"
status=0
sync_branches "$root" || status=$?
# A refusal means the checkout is untouched: no branch was switched, nothing was
# merged, so there is nothing to install either.
if ((status == 1)); then
    exit 1
fi
# Pixi is looked up before the environment is cleared: on plain Linux the
# official installer puts it in ~/.pixi/bin, which is not in the PATH the install
# can name in advance, and the cleared PATH is what keeps this run reproducible.
pixi=$(command -v pixi) || { echo 'pixi is not on PATH. See https://pixi.sh' >&2; exit 1; }
pixi_dir=$(dirname -- "$pixi")
install_env() {
    env -i HOME="$HOME" PATH="$pixi_dir:/usr/local/bin:/usr/bin:/bin" \
        "$pixi" install --locked "$@" --manifest-path "$root/pixi.toml"
}
install_env -e default
# Local inference is optional. When it is installed it is a second environment in
# the same checkout, so it is updated here too rather than left behind: models.ini
# and the inference recipes come from this repository. On the Windows deployment
# llama.cpp runs natively on Windows instead and has no environment here.
if [[ -d $root/.pixi/envs/llamacpp-binary-vulkan ]]; then
    install_env -e llamacpp-binary-vulkan
fi
printf '\nLinux deployment updated. Close and reopen the chatbot to use the new tools.\n'
if [[ ! -d $root/.pixi/envs/llamacpp-binary-vulkan ]]; then
    printf 'Local inference is not installed here. pixi r start-server installs it when you first need it.\n'
fi
if ((status == 2)); then
    printf 'The tools were updated, but something in the branch update above needs your attention.\n' >&2
    exit 2
fi
