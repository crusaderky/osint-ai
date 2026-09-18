# Copied components

Adapted from the adjacent `pixi-llm-recipes` checkout supplied for this task:

- `models.ini`: copied unchanged, including large/experimental presets. Runtime
  capacity is not guaranteed; weights load only on explicit model selection.
- `llamacpp-binary-cuda`: retained Anbeeld/beellama.cpp v0.4.6 and CUDA 13.3.
  Reduced binary recipe to linux-64 CUDA; download moved to checksum-verified
  rattler-build source. No CPU/Vulkan/ROCm or Windows-native binary paths.
- `pi`: conda-forge pi-coding-agent 0.85.1; Linux only.
- `pi-extensions`: retained pinned pi-llama-cpp, pi-web-access, pi-token-speed,
  and ask-user-question. Dropped developer-only btw/caveman/usage extensions and
  rtk command rewriting. Shell and Windows-specific build variants removed.
- `pi-home`: retained package structure, keybindings and web-search config;
  replaced global guidance with project-local skill instructions and added local
  llama server defaults. Removed use-gh-cli skill because Git belongs to Windows.
- `bwrap-pi.sh`: replaced blanket root bind with explicit allowlist, added ext4
  storage validation, removed Git credential sharing and skill rsync-back. Moved
  containment before Pixi activation so writable manifests remain safe to use.
- `pixi r install`: simplified to installed-launcher checks and usage guidance;
  first-time privileged setup lives in Windows bootstrap/WSL provisioning.

Third-party package licenses continue to apply. Release packaging must include
required notices for Ubuntu, Pixi, bubblewrap, Pi, extensions and llama.cpp.
