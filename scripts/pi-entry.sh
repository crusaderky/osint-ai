#!/bin/bash
# Executed by the launcher ONLY after bubblewrap has established isolation.
set -euo pipefail
[[ "${OSINT_SANDBOX:-}" == 1 ]] || { echo 'Pi must run inside the OSINT sandbox.' >&2; exit 1; }
: "${CONDA_PREFIX:?Pi environment is missing}"

# Inject model-shortlist.json into ~/.pi/agent/settings.json
checkout=$(cd -- "$CONDA_PREFIX/../../.." 2>/dev/null && pwd)
export OSINT_MODEL_SHORTLIST="$checkout/model-shortlist.json"

/usr/bin/python3 -I - "$CONDA_PREFIX" <<'PY'
import json
import os
from pathlib import Path
import sys

bundled = Path(sys.argv[1]) / 'home/.pi'
live = Path.home() / '.pi'
agent = live / 'agent'
agent.mkdir(parents=True, exist_ok=True)
# auth.json and settings.json live in here: keep the directories private
# whatever the umask was when they were first created.
for directory in (live, agent):
    os.chmod(directory, 0o700)
# The keybindings and web-search.json are not copied: the launcher mounts the
# environment's copies read-only over whatever the home holds there, so they
# always match the installed program and the agent cannot rewrite them. The
# agent's instructions are not part of the package at all: Pi reads them from
# `workspace/AGENTS.md` in the checkout it starts in.
# Link, not bind-mount: replacing environment files must not fail with EBUSY.
packages = agent / 'npm'
target = bundled / 'agent/npm'
# The agent home outlives the mount layout. A link written by an older launcher
# points at a sandbox path that no longer exists, and Node follows it when it
# makes the npm project, which fails as ENOENT on the link, not on the target.
# Re-point any link that is not the current environment's, and never follow one.
if packages.is_symlink():
    current = packages.exists() and target.is_dir() and os.path.samestat(
        os.stat(packages), os.stat(target)
    )
    if not current:
        packages.unlink()
if not packages.exists() and not packages.is_symlink():
    packages.symlink_to(target, target_is_directory=True)
defaults = json.loads((bundled / 'agent/osint-defaults.json').read_text())
settings_file = agent / 'settings.json'
settings = defaults | (json.loads(settings_file.read_text()) if settings_file.exists() else {})
# These two name sandbox mount paths, so the launcher owns them: a value saved
# by an older layout would point somewhere that no longer exists.
settings['packages'] = json.loads((bundled / 'agent/settings.json').read_text()).get('packages', [])
settings['skills'] = defaults.get('skills', [])

# The model shortlist is a project file - `model-shortlist.json` in the program
# checkout - because it is what the maintainer updates when the models worth
# using change. Merged on every launch, and merged additively: a model the user
# saved with /model stays, an entry already in the list is not added again, and
# nothing here removes a model. `dict.fromkeys` over both lists is what keeps the
# first-seen order and drops the repeats.
wanted = json.loads(Path(os.environ['OSINT_MODEL_SHORTLIST']).read_text())['enabledModels']
settings['enabledModels'] = list(dict.fromkeys([*settings.get('enabledModels', []), *wanted]))

settings_file.write_text(json.dumps(settings, indent=2) + '\n')
os.chmod(settings_file, 0o600)
# The local models Pi may pick from. Not a copy of a shipped file either: the
# address of the llama.cpp server is a deployment detail (loopback on plain
# Linux, the Windows host from inside WSL) and it changes when WSL restarts, so
# the launcher rewrites it on every launch and a stale address cannot survive.
models_file = agent / 'models.json'
models = json.loads((bundled / 'agent/models.json').read_text())
for provider in models.get('providers', {}).values():
    provider['baseUrl'] = os.environ.get('OSINT_INFERENCE_URL', 'http://127.0.0.1:8080') + '/v1'
models_file.write_text(json.dumps(models, indent=2) + '\n')
os.chmod(models_file, 0o600)
# The agent's instructions are not a program file any more: they are
# `workspace/AGENTS.md` in the checkout it starts in, named on the command line
# below. Pi would also read `~/.pi/agent/AGENTS.md` as user instructions if
# context discovery were on, so a copy left in a home that outlives the layout -
# written by the old copy-on-first-start launcher, or the 0-byte placeholder
# bubblewrap left behind - would keep steering the assistant with paths that no
# longer exist. Move it aside once; the home is the user's directory, so nothing
# is thrown away.
instructions = agent / 'AGENTS.md'
if instructions.is_file() or instructions.is_symlink():
    archived = agent / 'AGENTS.md.stale'
    if archived.exists():
        instructions.unlink()  # already archived on an earlier launch
    else:
        instructions.replace(archived)
PY

# Skills are project content, versioned in the user's checkout. Pass their
# location explicitly so discovery does not depend on Pi's project-trust prompt.
# The launcher exports OSINT_SKILLS_DIR; this default is the same path in both
# deployments because the checkout is always mounted at /osint-ai.
skills=${OSINT_SKILLS_DIR:-/osint-ai/workspace/.agents/skills}
mkdir -p "$skills" 2>/dev/null || true  # an incomplete checkout must not block startup

# Pi loads a context file from its working directory *and from every parent
# directory up to /*, and neither its settings nor its command line limits that
# walk: `--no-context-files` is all-or-nothing, and `AGENTS.override.md` replaces
# a file only in its own directory. The checkout root is a parent of the
# workspace, and its `AGENTS.md` is the maintainer's file - `pixi.toml`, tests,
# how to rebuild the sandbox - which the assistant must not follow. So discovery
# is switched off and the one guide is named explicitly.
#
# Shadowing the root file with a bind mount was the other option and is the wrong
# one: the mount is read-only, so the assistant cannot change it, but `git status`
# in its own checkout then reports `AGENTS.md` as modified, and `git add -A` plus
# `git commit` - both allowed by the guidance - would commit an empty file over
# the maintainer's instructions in the checkout the user pushes from.
guide=${OSINT_WORKSPACE:-/osint-ai/workspace}/AGENTS.md
pi_flags=(--skill "$skills" --no-context-files)
if [[ -f $guide ]]; then
    pi_flags+=(--append-system-prompt "$guide")
else
    echo "OSINT AI: $guide is missing, so the assistant starts without its instructions." >&2
fi

# Decode argv without passing quotes, spaces, or shell metacharacters to Pi.
# Keep Pi's original terminal stdin, not the Python heredoc above.
mapfile -d '' -t PI_ARGS < <(/usr/bin/python3 -I -c '
import base64, json, os, sys
args = json.loads(base64.b64decode(os.environ.get("OSINT_PI_ARGS", "W10=")))
sys.stdout.buffer.write(b"".join(arg.encode() + b"\0" for arg in args))
')
exec pi "${pi_flags[@]}" "${PI_ARGS[@]}"
