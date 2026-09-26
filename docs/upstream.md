# Copied components

Adapted from the adjacent `pixi-llm-recipes` checkout supplied for this task:

- `models.ini`: copied unchanged, including large/experimental presets. Runtime
  capacity is not guaranteed; weights load only on explicit model selection.
- `llamacpp-binary-cuda`: retained Anbeeld/beellama.cpp v0.4.6 and CUDA 13.3.
  Reduced the binary recipe to linux-64 CUDA and moved the download to a
  checksum-verified rattler-build source. No CPU/Vulkan/ROCm or Windows-native
  binary paths. The server starts this build on the CPU when no CUDA device is
  present.
- `pi`: conda-forge pi-coding-agent 0.86.1; Linux only. Bumped from 0.85.1 for
  `pi-subagents`, whose peer requirement is `@earendil-works/pi-ai >=0.86.1`;
  0.86.1 is also the host baseline for its dynamic tool activation.
- `pi-extensions`: retained pinned pi-llama-cpp, pi-web-access, pi-token-speed,
  and ask-user-question, and added pinned pi-subagents 0.71.0 for delegation.
  Dropped developer-only btw/caveman/usage extensions, intercom and rtk command
  rewriting. Removed shell and Windows-specific build variants. pi-subagents
  costs about 3.5k of system prompt. It reads sub-agent definitions from the
  project's legacy `.agents/**/*.md` tree, where this project's skills live, but
  0.71.0 skips `.agents/skills/**` itself, so no exclusion setting is needed;
  verified with the extension's own discovery, which reported only its 14
  bundled agents.
- `pi-home`: retained the package structure, keybindings and web-search config;
  replaced global guidance with the functional workspace's instructions and added
  local llama server defaults. Skills are discovered at
  `/workspace/.agents/skills`. Removed the `use-gh-cli` skill because Git belongs
  to Windows.
- `bwrap-pi.sh` / `sandbox.py`: replaced the blanket root bind with an explicit
  allowlist, added Linux-filesystem validation, removed Git credential sharing
  and skill rsync-back, and moved containment before Pi starts. Supports the two
  deployment modes: the workspace of the current checkout, or the workspace of
  the Windows checkout mounted at `/mnt/osint-ai`.
- `pixi r install`: simplified to installation checks and usage guidance;
  first-time privileged setup lives in the Windows bootstrap/WSL provisioning.

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
