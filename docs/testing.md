# Validation checklist

## Automated Linux tests

Run `python3 -m unittest discover -s tests -v` (or `pixi r test`). These cover
manifest/recipe configuration, argv construction, environment scrubbing, actual
bubblewrap filesystem isolation, and server process ownership/lifecycle with a
fake local server. Integration tests explicitly skip when namespaces are blocked.

Optional full Linux smoke test (downloads packages into temporary storage):

```bash
python3 tests/smoke_pixi_sandbox.py
```

This installs real Pi inside bubblewrap, uses RPC only for testing, and verifies
`/models` registration and discovery of a skill under `agents/`, without any
model API calls. PowerShell syntax/quoting checks:

```powershell
pwsh -NoProfile -File tests/Test-Installer.ps1
```

Also run Bash syntax checks and ShellCheck, and install both Pixi environments
to validate the local build recipes. Never claim Windows support based on the
Python tests alone.

## Required Windows 11 x64 acceptance matrix

Test on clean Home and Pro machines/VMs with virtualization enabled:

- [ ] No WSL: Install.cmd elevates only feature setup; reboot/rerun works under
      original Windows account. No unwanted default Ubuntu distro is created.
- [ ] Existing WSL and unrelated distros remain unchanged.
- [ ] Existing unrelated `osint-ai` distro is rejected; no distro is unregistered.
- [ ] First install, interrupted install retry, and completed-install rerun preserve
      checkout and user state. Path with spaces, apostrophe and non-ASCII works.
- [ ] NTFS selected; OneDrive/junction/UNC paths fail clearly. Private GitHub clone
      prepared by Windows GUI is reused without importing credentials into WSL.
- [ ] Desktop terminal opens correct distro and ordinary user. `osint-pi` works
      from `$HOME`, `/workspace` and another cwd.
- [ ] WSL termination/restart restores /workspace and ext4 .pixi before any Pixi
      invocation. Failed mount fails closed instead of installing onto NTFS.
- [ ] OpenRouter OAuth URL/callback paste and OpenCode API key login work. Login,
      sessions, settings and local extension state persist after restart.
- [ ] New skill lands in Windows `agents/name/SKILL.md`; Notepad sees it immediately.
      `/reload` discovers it. Root `AGENTS.md` is loaded and editable.
- [ ] Windows Git GUI opens same checkout, shows diffs, commits and pushes. Agent
      cannot see `.git` contents or access Windows GitHub credential storage.
- [ ] `pixi add` / `pixi add --pypi` and tool execution work inside sandbox; lockfile
      edits remain reviewable. No symlink-loop/case-folding package extraction.
- [ ] Malicious activation hook/task cannot access other Windows files, host home,
      interop, or boot helper. Changes never execute outside containment on relaunch.
- [ ] Test Windows junctions, symlinks, hardlinks and rename races across the shared
      directory boundary. These require Windows tests, not just Linux mocks.
- [ ] No NVIDIA GPU: hosted providers work; start-server gives actionable error.
- [ ] Supported NVIDIA GPU + driver: actual CUDA model load and generation work.
      Do not accept only nvidia-smi or device enumeration as inference validation.
- [ ] start-server downloads no weights; `/models` triggers selected model download
      and shows progress. Test small preset, OOM, bad network and interrupted load.
- [ ] start-server is idempotent; occupied port, timeout and crash are reported.
      stop-server cleans up router/model subprocesses and retains cached weights.
- [ ] Server listens on WSL loopback only; not LAN. `/models` works while server is
      outside bubblewrap. Agent cannot edit its executable, libraries or presets.

## Release gates still outside skeleton

Signed Windows installer, published immutable release, full supply-chain lock and
update process, download/disk-space UX, installer rollback/uninstall, automated
Windows VM tests, supported GPU/driver matrix, security review, resource quotas,
and model presets appropriate for supported consumer hardware.
