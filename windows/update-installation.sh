#!/bin/bash
# Trusted, human-started update of the Windows deployment, run as root inside the
# private distribution by the **Update OSINT AI** desktop icon.
#
# In order:
#   1. mounts the Windows checkout at /mnt/osint-ai (the same boot-hook helper)
#   2. updates the Linux program checkout as the osint user: fast-forwards main,
#      or does the main/staging dance when that checkout has a staging branch,
#      then reinstalls its Pixi environments
#   3. reinstalls the root-owned runtime in /usr/local from that checkout, so a
#      change to scripts/ reaches an installed PC without a reinstall
#   4. updates the Windows checkout as the osint user, with the same branch dance
#      and its origin pinned to the Linux checkout's
#
# The Windows side then reinstalls the native llama.cpp environment from the
# Windows checkout. That happens on Windows, in the wrapper the desktop icon runs,
# not here: llama.cpp is not inside the distribution.
#
# Everything that writes to a checkout or an environment runs as osint, the user
# that owns both checkouts and the environments - never as root, because the
# Windows checkout's `.git` is writable by the assistant and Git runs whatever
# hooks it finds there. Only /usr/local and the mount point of the Windows drive
# need root.
#
# Exit status: 0 finished, 1 stopped with that checkout left as it was, 2 finished
# but something above needs a human.
set -euo pipefail
if [[ ${OSINT_SANDBOX:-} == 1 ]]; then
    echo 'Update the installation from the desktop icon, never inside the assistant.' >&2
    exit 1
fi
if [[ $EUID != 0 ]]; then
    echo 'This update runs as root inside the private distribution. Start it from Windows:' >&2
    echo '  wsl -d osint-ai -u root -e /bin/bash /usr/local/lib/osint-ai/update-installation.sh' >&2
    exit 1
fi
if [[ ! -f /etc/osint-ai-installed ]]; then
    echo 'This WSL distribution was not installed by OSINT AI. Run windows\Install.cmd from Windows.' >&2
    exit 1
fi
mapfile -t projects < <(/usr/bin/python3 -I -c 'import json;c=json.load(open("/etc/osint-ai.json"));print(c["linux_project"]);print(c["windows_project"])')
linux=${projects[0]:-}
windows=${projects[1]:-}
for path in "$linux" "$windows"; do
    [[ $path == /* && $path != */ && -d $path ]] || {
        echo "The installation names a checkout that is not there: $path" >&2
        exit 1
    }
done
# The one place a checkout or an environment is touched, so every caller below is
# the checkout's own user with a cleared environment: no inherited PATH, no
# inherited Git identity, and nothing that could reach the assistant's session.
as_osint() {
    runuser -u osint -- env -i HOME=/home/osint PATH=/usr/local/bin:/usr/bin:/bin "$@"
}

# 1. The Windows checkout has to be mounted before anything can be said about it.
mount_helper=/usr/local/lib/osint-ai/mount-workspace.py
[[ -f $mount_helper ]] || mount_helper=$linux/windows/mount-workspace.py
[[ -f $mount_helper ]] || {
    echo 'This installation has no mount helper. Run windows\Install.cmd from Windows.' >&2
    exit 1
}
/usr/bin/python3 -I "$mount_helper"

# 2. The Linux program checkout. It refuses an uncommitted tree and leaves itself
# untouched when it does; that is a refusal for the whole update, because every
# later step installs from it.
if [[ ! -f /usr/local/lib/osint-ai/update-project.sh ]]; then
    echo 'This installation has no update-project.sh. Run windows\Install.cmd from Windows.' >&2
    exit 1
fi
attention=0
status=0
as_osint /bin/bash -p /usr/local/lib/osint-ai/update-project.sh || status=$?
if ((status == 1)); then
    echo 'The Windows checkout and the installed runtime were left as they were.' >&2
    exit 1
fi
if ((status == 2)); then
    attention=1
fi

# 3. The runtime in /usr/local, from the checkout that was just updated. Prefer
# the checkout's copy: the refresh installs the newest list of files, and the
# installed copy is only a fallback for a checkout too old to carry one.
runtime_installer=$linux/windows/install-runtime.sh
[[ -f $runtime_installer ]] || runtime_installer=/usr/local/lib/osint-ai/install-runtime.sh
[[ -f $runtime_installer ]] || {
    echo "The program checkout at $linux has no windows/install-runtime.sh," >&2
    echo 'so the installed runtime cannot be refreshed. Ask your maintainer to publish the update.' >&2
    exit 1
}
/bin/bash "$runtime_installer" "$linux"

# 4. The Windows checkout, exactly as the Linux one: main fast-forwarded, staging
# fast-forwarded and then given main. Its origin is pinned to the Linux
# checkout's, which the installer verified and the assistant cannot write: the
# Windows checkout is writable by the assistant, so a repointed remote must not be
# followed by a human-clicked update.
if [[ ! -f /usr/local/lib/osint-ai/git-branches.sh ]]; then
    echo 'This installation has no branch helper. Run windows\Install.cmd from Windows.' >&2
    exit 1
fi
expected_origin=$(as_osint git -C "$linux" remote get-url origin) || {
    echo "The program checkout at $linux has no origin." >&2
    exit 1
}
status=0
as_osint /bin/bash -p /usr/local/lib/osint-ai/git-branches.sh "$windows" "$expected_origin" || status=$?
if ((status == 1)); then
    echo 'The WSL program and its runtime were updated; the Windows checkout was left as it was.' >&2
    exit 1
fi
if ((status == 2)); then
    attention=1
fi

printf '\n'
if ((attention)); then
    printf 'Updated, but something above needs your attention.\n' >&2
    exit 2
fi
printf 'Updated. Start llama.cpp again when you want local models.\n'
