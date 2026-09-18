#!/usr/bin/env bash
set -euo pipefail

# rattler-build downloads, verifies and extracts the pinned release archive, so
# BACKEND, FORK and VERSION (build.script.env) are only used for logging here.
# Windows is handled by build.bat.
echo "Installing the ${BACKEND:-unknown} build of ${FORK:-unknown} ${VERSION:-unknown} into ${PREFIX}"

# Depending on archive extraction, its single top-level directory may remain.
# Upstream names it after the release tag, e.g. `llama-b11514`, so the directory
# of the requested version is preferred over whatever an earlier build left in
# the reused work directory.
for extracted in "llama-${VERSION:-}" llama-b* llama; do
    if [[ -n $extracted && -d $extracted ]]; then
        cd -- "$extracted"
        break
    fi
done
# The build prefix is reused between builds, so clear the two directories this
# recipe owns: last time's shared objects must not be packaged alongside this
# time's. Nothing else in the prefix is touched.
rm -rf "$PREFIX/opt/llama" "$PREFIX/bin"
mkdir -p "$PREFIX/opt/llama" "$PREFIX/bin"
# Executables and their shared libraries live side by side: the ggml Vulkan
# backend is a shared object loaded from the executable's own directory, and a
# machine without a Vulkan loader fails to load that one file, not the server.
for file in *.so *.so.* llama llama-* ggml-rpc-server; do
    [[ -f "$file" ]] || continue
    cp -a "$file" "$PREFIX/opt/llama/"
    if [[ -x "$file" && "$file" != *.so* ]]; then
        ln -sf "../opt/llama/$file" "$PREFIX/bin/$file"
    fi
done
test -x "$PREFIX/bin/llama-server"
