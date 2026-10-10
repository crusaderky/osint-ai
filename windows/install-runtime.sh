#!/bin/bash -p
# Install the root-owned runtime of the Windows deployment into /usr/local.
#
# The sandbox launcher, the pi entry script, the server controller, the boot
# mount helper, the updater and the terminal commands are installed outside both
# checkouts, so an installed PC runs the code it installed rather than whatever a
# checkout happens to contain. This is the one list of those files. It is used by
#
#   windows/provision-wsl.sh        first installation, from the checkout being
#                                   installed, before the agent has ever run
#   windows/Install.ps1             every later run of Install.cmd, same source -
#                                   which is also how a PC installed before the
#                                   updater existed gets it at all
#   windows/update-installation.sh  every click of the Update OSINT AI icon, from
#                                   the Linux program checkout, after
#                                   `update-project` pulled it
#
# The Windows checkout is writable by the assistant, so an install runs this from
# the checkout the human just installed; the update runs it from the Linux
# checkout, which the sandbox mounts read-only. Both are deliberate, human-started
# operations. This script only copies files: it executes nothing from the checkout
# it is given.
set -euo pipefail
if [[ $EUID != 0 ]]; then
    echo 'Installing the runtime needs root. Run windows\Install.cmd, or the Update OSINT AI icon.' >&2
    exit 1
fi
if [[ $# != 1 ]]; then
    echo 'Usage: install-runtime.sh <checkout>' >&2
    exit 2
fi
source_checkout=$1
[[ $source_checkout == /* && $source_checkout != */ ]] || { echo "Give an absolute checkout path, not $source_checkout." >&2; exit 1; }
[[ -f $source_checkout/scripts/sandbox.py && -f $source_checkout/windows/provision-wsl.sh ]] || {
    echo "Not a checkout of this project: $source_checkout" >&2
    exit 1
}

install -d -m 755 /usr/local/lib/osint-ai
count=0
# Every file in scripts/ belongs to the runtime: the launchers, the sandbox, the
# server, the branch helper and the maintenance scripts. A new file there is
# installed without touching this script.
for file in "$source_checkout"/scripts/*; do
    [[ -f $file ]] || continue
    install -m 755 "$file" "/usr/local/lib/osint-ai/$(basename -- "$file")"
    count=$((count + 1))
done
# The Windows-deployment half of the runtime, by name: the boot mount helper, the
# updater itself and this script, so a later update can run even when the checkout
# it came from no longer has them.
for file in mount-workspace.py update-installation.sh install-runtime.sh; do
    [[ -f $source_checkout/windows/$file ]] || {
        echo "The checkout at $source_checkout has no windows/$file. Pull the newest version in your Git app and try again." >&2
        exit 1
    }
    install -m 755 "$source_checkout/windows/$file" "/usr/local/lib/osint-ai/$file"
    count=$((count + 1))
done
# The commands an installed PC runs by name, whether from a terminal or from a
# desktop shortcut.
for command in "$source_checkout"/windows/launchers/*; do
    [[ -f $command ]] || continue
    install -m 755 "$command" "/usr/local/bin/$(basename -- "$command")"
    count=$((count + 1))
done
printf 'Installed the runtime from %s (%s files) into /usr/local.\n' "$source_checkout" "$count"
