# Copied components

Adapted from the adjacent `pixi-llm-recipes` checkout supplied for this task:

- `models.ini`: copied unchanged, including large/experimental presets. Runtime
  capacity is not guaranteed; weights load only on explicit model selection.
- `models.ini`: copied, with `dedup-cache-models = true` added to the global
  section so the cached Hugging Face blob of a preset is not listed a second time.
  Large/experimental presets are kept; runtime capacity is not guaranteed, and
  weights load only when a model is chosen.
- `llamacpp-binary-vulkan`: upstream ggml-org/llama.cpp, release `b11514`, on the
  Vulkan build on both platforms this project supports: linux-64 (the plain
  Linux install, and WSL if somebody really wants a server there) and win-64,
  where llama.cpp now runs natively, outside WSL, so it reaches the GPU directly.
  Kept the checksum-verified rattler-build `source` (each hash is the SHA-256
  GitHub publishes for that asset) and the `backend` variant matrix, dropped
  CUDA, ROCm, SYCL and arm64, and took the reference recipe's `build.bat` so the
  zip assets install on Windows too. The CPU variant stays available for a PC
  whose Vulkan device never answers; the shipped Vulkan build starts on the CPU
  by itself when nothing answers.
  Replaced Anbeeld/beellama.cpp v0.4.7. The fork was kept for `kv-tail-tokens`
  (an exact BF16 KV tail) and `cache-type-v = q3_0`, and neither survives on the
  Vulkan asset this project ships: the exact tail is not implemented there, so
  the fork routes it through the path it warns is "catastrophic generic
  attention" - `graph splits = 338 (with bs=512), 86 (with bs=1)` and an 8.4 GB
  host compute buffer at `ctx-size 131072`, measured at 106 tokens/s of prompt
  evaluation against 2643 tokens/s with the option off, and 22 tokens/s of
  decode against 190 - and upstream's router treats an unknown preset key as
  fatal, so a fork-only key is a server that does not start rather than one that
  is slower. `models.ini` now quantizes both K and V to `q4_0`, which upstream
  documents for both halves.
- `pi`: conda-forge pi-coding-agent, floating in the manifest and locked at
  1.0.2; Linux only. Raised from 0.85.1 for `pi-subagents`, whose peer
  requirement is `@earendil-works/pi-ai >=0.86.1`; that floor is also the host
  baseline for its dynamic tool activation. A future re-lock below it breaks
  delegation, which a test in `tests/test_skeleton.py` now checks.
  Pi 1.0.2 loads a context file from the working directory and from every parent
  directory, and offers no setting to limit that walk: `--no-context-files` is
  all-or-nothing and `AGENTS.override.md` replaces a file only in its own
  directory. That is why `scripts/pi-entry.sh` disables discovery and names
  `workspace/AGENTS.md` explicitly with `--append-system-prompt`, rather than
  relying on the mount layout. Re-check this on the next Pi upgrade: if Pi ever
  learns a ceiling for the walk, the flags can go.
- `pi-extensions`: retained pinned pi-web-access, pi-token-speed, and
  ask-user-question, and added pinned pi-intercom 0.16.1 and pi-subagents
  0.76.0 for delegation. Dropped developer-only btw/caveman/usage extensions and
  rtk command rewriting. Removed shell and Windows-specific build variants, and
  removed pi-llama-cpp: Pi's own llama.cpp provider and `/llama` command do the
  same job, and the launcher points it at the server by generating
  `~/.pi/agent/models.json` (`LLAMA_BASE_URL` supplies the same address to the
  provider).
  pi-subagents costs about 3.5k of system prompt. It reads sub-agent
  definitions from the project's legacy `.agents/**/*.md` tree, where this
  project's skills live, but it skips `.agents/skills/**` itself, so no
  exclusion setting is needed; verified with the extension's own discovery,
  which reported only its bundled agents and none of the project's skills.
  pi-intercom ships a TypeScript entry point and its own `tsx` dependency, so its
  broker starts from the packaged tree with no network fetch; unlike the source
  recipe, the intercom runtime directory is a per-launch tmpfs rather than a path
  in the read-only environment.
- `pi-home`: retained the package structure, keybindings and web-search config, and
  added local llama server defaults. It ships no guidance of its own: the functional
  workspace's `workspace/AGENTS.md` is the assistant's only instructions, so there is
  no second copy to keep in step. Skills are discovered at
  `/osint-ai/workspace/.agents/skills`. Removed the `use-gh-cli` skill because Git
  belongs to Windows. Upstream copied these files into the agent home on first
  start; here the launcher binds the keybindings and the web-search config read-only
  out of the environment instead, so an existing home cannot keep an outdated copy.
- `scripts/bwrap-pi.sh` and `scripts/sandbox.py`: replaced the blanket root bind
  with an explicit allowlist, added Linux-filesystem validation, removed skill
  rsync-back, and moved containment before Pi starts. Upstream had a launcher per
  deployment; here one script takes `--native` or `--wsl`, for the workspace of
  the current checkout or of the Windows checkout mounted at `/mnt/osint-ai`.
  Upstream mounted the workspace on its own, as a mount of its own, which is what
  made Git unusable: Git walks up from the working directory and found no `.git`
  above it. Here the whole checkout is mounted at `/osint-ai` in both
  deployments and Pi starts in `/osint-ai/workspace`.
  Not copied from upstream: the agent's own checkout
  is bound read-write with its `.git` (upstream masks `.git` and hands over a
  launcher-written summary instead), and the launcher-written summary and the
  per-launch intercom tmpfs that upstream needed to keep `$CONDA_PREFIX` clean
  are both unnecessary here, where the environment is read-only and the agent
  home is already a separate persistent directory.
- `pixi r install` (`scripts/install-apparmor.sh` and `scripts/install-check.sh`):
  the check is simplified to installation checks and usage guidance, and the
  privileged part is one script that loads the AppArmor profile for the bubblewrap
  this project pins - upstream's `install-apparmor.sh` idea, extended to cover
  `<checkout>/.pixi/envs/*/bin/bwrap` instead of only `/usr/bin/bwrap`. First-time
  privileged setup on Windows lives in the bootstrap and WSL provisioning, which
  run that same script as root. There is no Linux installer script.
- The sandbox runs the bubblewrap the locked `default` environment installs, not
  the distribution's `/usr/bin/bwrap` (upstream does the same). Containment is
  therefore part of what `pixi.lock` pins and `update-project` replaces.

## Third-party licences

Third-party package licences continue to apply and must be listed in release
packaging: Ubuntu base (Ubuntu licences), Pixi (MIT), bubblewrap
(LGPL-2.1-or-later), Pi and extensions (MIT), llama.cpp (MIT), Python
(Python-2.0), pandas (BSD-3), openpyxl (MIT), xlrd (BSD-3/BSD-4), pyxlsb
(LGPL-3.0-or-later), pandoc (GPL-2.0-or-later), poppler (GPL-2.0-or-later),
WeasyPrint (BSD-3), DejaVu/Source/Ubuntu fonts (BSD-3 and Ubuntu Font Licence).

Bundled report and spreadsheet tooling is invoked as separate commands from the
project environment; releasing the installer keeps those components under their
own licences, which requires shipping or offering their source as each licence
requires.

**MobaXterm is not bundled.** The installer reuses an existing installation or
downloads the pinned portable build from mobaxterm.mobatek.net on the user's own
machine; MobaXterm's own licence (free for personal use, paid for commercial
use) applies and must be checked before a commercial rollout. It is outside the
sandbox trust boundary.
