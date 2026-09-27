#!/bin/bash
# Trusted, first-install provisioning only. windows/Install.ps1 executes this as
# root from the freshly cloned Windows checkout
# (/mnt/osint-ai/windows/provision-wsl.sh), before the agent has ever run.
#
# It creates the second (Linux) checkout that owns Git, Pixi and the runtime.
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Provisioning requires WSL root.' >&2; exit 1; }
[[ $# == 4 ]] || { echo 'Usage: provision-wsl.sh <windows checkout> <repository> <ref> <linux project>' >&2; exit 1; }
[[ ! -e /etc/osint-ai-installed ]] || { echo 'Already provisioned; refusing to overwrite trusted runtime.'; exit 1; }
[[ -f /etc/osint-ai-installing ]] || { echo 'Not an installer-owned distribution.' >&2; exit 1; }

WINDOWS_CHECKOUT=$1
REPOSITORY=$2
REF=$3
LINUX_PROJECT=$4
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)   # windows/
REPO=$(cd "$HERE/.." && pwd)                         # the checkout being installed
[[ -f $REPO/pixi.toml && -f $REPO/scripts/sandbox.py ]] || {
    echo 'Unexpected checkout layout: need scripts/sandbox.py next to windows/.' >&2; exit 1; }
[[ $LINUX_PROJECT =~ ^/[A-Za-z0-9._/-]+$ && $LINUX_PROJECT != */ ]] || { echo 'Bad Linux project path.' >&2; exit 1; }
[[ -d $WINDOWS_CHECKOUT ]] || { echo 'Windows checkout is not mounted.' >&2; exit 1; }

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends bash bubblewrap apparmor ca-certificates curl git \
    python3 tar xz-utils util-linux passwd locales nano libatomic1
if ! id osint >/dev/null 2>&1; then
    useradd --create-home --uid 1000 --shell /bin/bash osint
fi
[[ $(id -u osint) == 1000 ]] || { echo 'Unexpected osint UID.' >&2; exit 1; }

install -d -m 755 /usr/local/lib/osint-ai /var/lib/osint-ai /opt/osint-ai
# The launcher, entry script and server controller are the same files the Linux
# deployment runs from scripts/. mount-workspace.py is the one part here that
# only makes sense in WSL.
for file in bwrap-pi.sh install-check.sh launch-server.sh pi-entry.sh sandbox.py server.py \
    update-project.sh; do
    install -m 755 "$REPO/scripts/$file" "/usr/local/lib/osint-ai/$file"
done
install -m 755 "$HERE/mount-workspace.py" /usr/local/lib/osint-ai/mount-workspace.py
for command in osint-pi osint-pi-wsl osint-terminal start-server stop-server restart-server update-project; do
    install -m 755 "$HERE/launchers/$command" "/usr/local/bin/$command"
done
for dir in agent-home server-state models; do
    install -d -m 700 -o osint -g osint "/var/lib/osint-ai/$dir"
done

# The Linux checkout owns Git, the manifest and every Linux environment.
if [[ -d $LINUX_PROJECT/.git && ! -L $LINUX_PROJECT/.git ]]; then
    origin=$(runuser -u osint -- git -C "$LINUX_PROJECT" remote get-url origin)
    [[ $origin == "$REPOSITORY" ]] || { echo 'Existing Linux checkout has a different origin.' >&2; exit 1; }
    echo 'Using the existing Linux checkout without updating it.'
elif [[ -e $LINUX_PROJECT && ! -L $LINUX_PROJECT ]]; then
    [[ -z $(find "$LINUX_PROJECT" -mindepth 1 -maxdepth 1 -print -quit) ]] || {
        echo "$LINUX_PROJECT exists and is not the expected checkout." >&2; exit 1; }
    rmdir "$LINUX_PROJECT"
fi
if [[ ! -d $LINUX_PROJECT ]]; then
    install -d -o osint -g osint "$(dirname "$LINUX_PROJECT")"
    GIT_TERMINAL_PROMPT=0 runuser -u osint -- env -i HOME=/home/osint \
        GIT_TERMINAL_PROMPT=0 PATH=/usr/local/bin:/usr/bin:/bin \
        git clone --config core.autocrlf=false --config core.filemode=false \
        --branch "$REF" -- "$REPOSITORY" "$LINUX_PROJECT"
fi

python3 -I - "$WINDOWS_CHECKOUT" "$LINUX_PROJECT" <<'PY'
import json
from pathlib import Path
import sys
Path('/etc/osint-ai.json').write_text(json.dumps({
    'windows_project': sys.argv[1],
    'linux_project': sys.argv[2],
}) + '\n')
PY
chmod 644 /etc/osint-ai.json
cat > /etc/wsl.conf <<'EOF'
[automount]
enabled=false
mountFsTab=false
[interop]
enabled=false
appendWindowsPath=false
[user]
default=osint
[boot]
command=/usr/local/lib/osint-ai/mount-workspace.py
EOF
# Disable interop for this initial boot too; wsl.conf applies on next boot.
if [[ -e /proc/sys/fs/binfmt_misc/WSLInterop ]]; then
    echo -1 > /proc/sys/fs/binfmt_misc/WSLInterop
fi
cat > /etc/apparmor.d/bwrap <<'EOF'
abi <abi/4.0>,
include <tunables/global>
profile bwrap /usr/bin/bwrap flags=(unconfined) {
  userns,
  include if exists <local/bwrap>
}
EOF
/usr/local/lib/osint-ai/mount-workspace.py

# Pin and verify executable bootstrap, rather than piping a mutable installer to sh.
PIXI_VERSION=0.79.0
PIXI_SHA256=b9b6dd2bdf4e0043c2c0cd6d15334a26c6851121bf5ae16c39b69add598bafdc
TEMP=$(mktemp -d)
trap 'rm -rf "$TEMP"' EXIT
curl --fail --location --retry 3 \
    "https://github.com/prefix-dev/pixi/releases/download/v${PIXI_VERSION}/pixi-x86_64-unknown-linux-musl.tar.gz" \
    -o "$TEMP/pixi.tar.gz"
printf '%s  %s\n' "$PIXI_SHA256" "$TEMP/pixi.tar.gz" | sha256sum --check
tar -xzf "$TEMP/pixi.tar.gz" -C "$TEMP"
install -m 755 "$TEMP/pixi" /usr/local/bin/pixi

# Agent tools and Pi itself live in the Linux checkout's own environment. The
# launcher later exposes that environment read-only inside the sandbox.
runuser -u osint -- env -i HOME=/home/osint PATH=/usr/local/bin:/usr/bin:/bin \
    pixi install --locked -e default --manifest-path "$LINUX_PROJECT/pixi.toml"

# Protected installed inference artifact, not a third checkout. Never run the
# user-editable project's activation hooks outside bubblewrap on startup.
SERVER=/opt/osint-ai/server
if [[ ! -f "$SERVER/.installed" ]]; then
    install -d -o osint -g osint "$SERVER" "$SERVER/pixi-recipes" /var/cache/osint-ai/server-build
    # Reuse the reviewed release lockfile, rather than solving a second manifest.
    cp -a "$LINUX_PROJECT/pixi-recipes/." "$SERVER/pixi-recipes/"
    cp "$LINUX_PROJECT/pixi.toml" "$LINUX_PROJECT/pixi.lock" "$LINUX_PROJECT/models.ini" "$SERVER/"
    chown -R osint:osint "$SERVER"
    # Install libraries even on cloud-only PCs with no NVIDIA GPU; the server
    # falls back to CPU inference when no CUDA device answers.
    runuser -u osint -- env -i HOME=/home/osint PATH=/usr/local/bin:/usr/bin:/bin \
        PIXI_CACHE_DIR=/var/cache/osint-ai/server-build \
        RATTLER_CACHE_DIR=/var/cache/osint-ai/server-build CONDA_OVERRIDE_CUDA=13.3 \
        pixi install --locked -e llamacpp-binary-cuda --manifest-path "$SERVER/pixi.toml"
    # This cache is deliberately separate: no writable hardlinks into server runtime.
    chown -R root:root "$SERVER" /var/cache/osint-ai/server-build
    chmod -R go-w "$SERVER" /var/cache/osint-ai/server-build
    touch "$SERVER/.installed"
fi

# Final acceptance check: the real launcher must reach Pi inside containment.
runuser -u osint -- /usr/local/bin/osint-pi-wsl --version
runuser -u osint -- /usr/local/lib/osint-ai/install-check.sh
touch /etc/osint-ai-installed
printf '\nOSINT AI installed. Use the OSINT AI Terminal desktop icon to start.\n'
