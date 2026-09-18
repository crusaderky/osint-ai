#!/bin/bash
# Let the bubblewrap installed by Pixi create a user namespace.
#
# The sandbox runs `<project root>/.pixi/envs/default/bin/bwrap`, not the
# distribution's `/usr/bin/bwrap`, so the pinned binary in the lockfile is what
# has to be allowed. Ubuntu 23.10+ and its WSL images refuse unprivileged user
# namespaces unless the program that asks for one has an AppArmor profile
# granting `userns`, and AppArmor attaches a profile to the canonical path of the
# executable. A profile that names only `/usr/bin/bwrap` therefore does not cover
# this project's sandbox.
#
# This is the only step in a Linux installation that needs root, and it asks for
# your own password: nothing here is passwordless and nothing runs as root from
# inside the assistant. `pixi r install` runs this script and then
# scripts/install-check.sh proves that the sandbox really starts. On Windows the
# installer's provisioning runs it as root once, so the everyday `pixi r install`
# finds the profile already correct and changes nothing.
#
# Ubuntu ships a stock /etc/apparmor.d/bwrap covering /usr/bin/bwrap only. This
# writes that same profile - kept so a maintainer's own bubblewrap still works -
# plus one for every environment in this checkout. dpkg reports the file as
# locally modified when the apparmor package upgrades; that is expected.
set -euo pipefail
if [[ "${OSINT_SANDBOX:-}" == 1 ]]; then
    echo 'Install the AppArmor profile in a terminal, not inside the assistant.' >&2
    exit 1
fi
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
root=$(cd -- "$here/.." && pwd)
wsl_deployment=0
if [[ -n ${OSINT_PROJECT_ROOT:-} ]]; then
    # The same override scripts/sandbox.py accepts.
    root=$OSINT_PROJECT_ROOT
elif [[ -r /etc/osint-ai.json ]]; then
    # Installed inside the private WSL distribution: the checkout whose bwrap
    # runs is the one named in the config, not the copy under /usr/local.
    wsl_deployment=1
    root=$(/usr/bin/python3 -I -c 'import json;print(json.load(open("/etc/osint-ai.json"))["linux_project"])')
fi
PROFILE=/etc/apparmor.d/bwrap
ENABLED=/sys/module/apparmor/parameters/enabled
say() { printf '  %-9s %s\n' "$1" "$2"; }
if [[ ! -r $ENABLED ]] || [[ $(cat "$ENABLED") != Y ]]; then
    say none "AppArmor is not in this kernel: no profile is needed for bubblewrap."
    exit 0
fi
# AppArmor reads the executable path as a single word, so a checkout directory
# with a space in it cannot be covered by a profile. Say that instead of writing
# a profile that silently never matches.
if [[ $root =~ [[:space:]] ]]; then
    echo "OSINT AI: cannot write an AppArmor profile for $root: the path contains a space." >&2
    echo "Move the checkout to a path without spaces, or add the profile by hand." >&2
    exit 1
fi

CONTENT="abi <abi/4.0>,
include <tunables/global>

profile bwrap /usr/bin/bwrap flags=(unconfined) {
  userns,
  include if exists <local/bwrap>
}
profile bwrap-pixi $root/.pixi/envs/*/bin/bwrap flags=(unconfined) {
  userns,
  include if exists <local/bwrap>
}"

if [[ -e $PROFILE ]] && [[ $(cat "$PROFILE") == "$CONTENT" ]]; then
    say ok "AppArmor profile for bubblewrap already correct ($PROFILE)"
    exit 0
fi

elevate=()
if ((EUID != 0)); then
    if command -v sudo >/dev/null; then
        elevate=(sudo)
    else
        echo "OSINT AI: $PROFILE has to be written, and neither root nor sudo is available." >&2
        if ((wsl_deployment)); then
            echo "This is the Windows installation: run windows\\Install.cmd again, or from Windows:" >&2
            echo "  wsl -d osint-ai -u root bash $root/scripts/install-apparmor.sh" >&2
        fi
        exit 1
    fi
fi
printf 'Installing AppArmor profile to %s\n' "$PROFILE"
printf '%s\n' "$CONTENT" | ${elevate[@]+"${elevate[@]}"} tee "$PROFILE" >/dev/null
if command -v systemctl >/dev/null && systemctl is-active --quiet apparmor; then
    ${elevate[@]+"${elevate[@]}"} systemctl reload apparmor
else
    ${elevate[@]+"${elevate[@]}"} apparmor_parser -r "$PROFILE"
fi
say ok "AppArmor profile for bubblewrap loaded ($PROFILE)"
