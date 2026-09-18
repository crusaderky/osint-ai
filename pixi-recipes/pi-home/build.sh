#!/usr/bin/env bash
set -euo pipefail

# This will be populated on first start with downloaded tools
mkdir -p "${PREFIX}/home/.pi/agent/bin"
touch "${PREFIX}/home/.pi/agent/bin/.keep"

# Copy bundled skills into the pi agent skills directory (flat copy)
cp -a skills "${PREFIX}/home/.pi/agent/"
cp -a keybindings.json "${PREFIX}/home/.pi/agent/"
# Separate filename: pi-extensions supplies the package-manager settings.json.
cp -a settings.json "${PREFIX}/home/.pi/agent/osint-defaults.json"
# The model list the launcher rewrites into the agent's home on every start: it
# names the local llama.cpp server, and its address differs per deployment.
cp -a models.json "${PREFIX}/home/.pi/agent/models.json"
cp -a web-search.json "${PREFIX}/home/.pi/"  # Not a typo
