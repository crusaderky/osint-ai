#!/bin/bash
# Trusted, first-install provisioning only. Windows bootstrap executes this
# from the freshly cloned release, before the agent has ever run.
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Provisioning requires WSL root.' >&2; exit 1; }
[[ $# == 1 ]] || { echo 'Expected Windows checkout path.' >&2; exit 1; }
[[ ! -e /etc/osint-ai-installed ]] || { echo 'Already provisioned; refusing to overwrite trusted runtime.'; exit 1; }
[[ -f /etc/osint-ai-installing ]] || { echo 'Not an installer-owned distribution.' >&2; exit 1; }

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends bash bubblewrap apparmor ca-certificates curl git \
    python3 tar xz-utils util-linux passwd locales nano libatomic1
if ! id osint >/dev/null 2>&1; then
    useradd --create-home --uid 1000 --shell /bin/bash osint
fi
[[ $(id -u osint) == 1000 ]] || { echo 'Unexpected osint UID.' >&2; exit 1; }

install -d -m 755 /usr/local/lib/osint-ai /var/lib/osint-ai /opt/osint-ai
for file in sandbox.py bwrap-pi.sh pi-entry.sh mount-workspace.py server.py install.sh; do
    install -m 755 "/workspace/scripts/$file" "/usr/local/lib/osint-ai/$file"
done
for command in osint-pi start-server stop-server; do
    install -m 755 "/workspace/scripts/install/$command" "/usr/local/bin/$command"
done
for dir in pixi agent-home server-state models; do
    install -d -m 700 -o osint -g osint "/var/lib/osint-ai/$dir"
done

python3 -I - "$1" <<'PY'
import json
from pathlib import Path
import sys
Path('/etc/osint-ai.json').write_text(json.dumps({'windows_project': sys.argv[1]}) + '\n')
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

# Protected installed inference artifact, not a second Git checkout. Never run
# the user-editable project's activation hooks outside bubblewrap on startup.
SERVER=/opt/osint-ai/server
if [[ ! -f "$SERVER/.installed" ]]; then
    install -d -o osint -g osint "$SERVER" "$SERVER/pixi-recipes" /var/cache/osint-ai/server-build
    # Reuse the reviewed release lockfile, rather than solving a second manifest.
    cp -a /workspace/pixi-recipes/. "$SERVER/pixi-recipes/"
    cp /workspace/pixi.toml /workspace/pixi.lock /workspace/models.ini "$SERVER/"
    chown -R osint:osint "$SERVER"
    # Install libraries even on cloud-only PCs with no NVIDIA GPU. Actual hardware
    # compatibility is checked by start-server; this override does not enable CUDA.
    runuser -u osint -- env -i HOME=/home/osint PATH=/usr/local/bin:/usr/bin:/bin \
        PIXI_CACHE_DIR=/var/cache/osint-ai/server-build \
        RATTLER_CACHE_DIR=/var/cache/osint-ai/server-build CONDA_OVERRIDE_CUDA=13.3 \
        pixi install --locked -e llamacpp-binary-cuda --manifest-path "$SERVER/pixi.toml"
    # This cache is deliberately separate: no writable hardlinks into server runtime.
    chown -R root:root "$SERVER" /var/cache/osint-ai/server-build
    chmod -R go-w "$SERVER" /var/cache/osint-ai/server-build
    touch "$SERVER/.installed"
fi

# Install and build the mutable agent environment *inside* containment.
runuser -u osint -- /usr/local/bin/osint-pi --version
runuser -u osint -- /usr/local/lib/osint-ai/install.sh
touch /etc/osint-ai-installed
printf '\nOSINT AI installed. Open its WSL terminal and run osint-pi.\n'
