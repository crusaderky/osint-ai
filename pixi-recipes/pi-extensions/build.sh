#!/usr/bin/env bash
set -euo pipefail

export HOME="${PREFIX}/home"
rm -rf "${PREFIX}/home/.pi/agent/npm"
rm -f "${PREFIX}/home/.pi/agent/settings.json"

# PLUGINS is set in recipe.yaml
for plugin in ${PLUGINS}; do
    pi install "npm:${plugin}"
done

npm approve-scripts --allow-scripts-pending
# npm's build-time cache/logs are not part of the installed application.
rm -rf "${PREFIX}/home/.npm"

# No shell-command rewriting or developer-only extensions in the user product.
