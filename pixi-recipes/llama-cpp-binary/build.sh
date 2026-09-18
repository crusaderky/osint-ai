#!/usr/bin/env bash
set -euo pipefail

# rattler-build downloads, verifies and extracts the pinned release archive.
# Depending on archive extraction, its single top-level directory may remain.
if [[ -d beellama-v0.4.6 ]]; then
    cd beellama-v0.4.6
fi
mkdir -p "$PREFIX/opt/llama" "$PREFIX/bin"
for file in *.so *.so.* llama-* rpc-server; do
    [[ -f "$file" ]] || continue
    cp -a "$file" "$PREFIX/opt/llama/"
    if [[ -x "$file" && "$file" != *.so* ]]; then
        ln -sf "../opt/llama/$file" "$PREFIX/bin/$file"
    fi
done
test -x "$PREFIX/bin/llama-server"
