# Validation checklist

This layout is incompatible with pre-refactor installations. Existing private
WSL distributions must be reinstalled (`wsl --unregister osint-ai`, then run
`wsl\Install.cmd` again); the Windows checkout and its `workspace/` content are
not touched by the installer.

## Automated Linux tests

Run `python3 -m unittest discover -s tests -v` (or `pixi r test`). These cover
manifest and recipe configuration, launcher argv construction for both the plain
Linux and the Windows workspace, environment scrubbing, read-only project mount,
actual bubblewrap filesystem isolation, the Git status summary, CPU-versus-GPU
backend selection and server process ownership/lifecycle with a fake local
server. Integration tests explicitly skip when namespaces are blocked.

```powershell
pwsh -NoProfile -File tests/Test-Installer.ps1     # parse wsl/Install.ps1, check escaping
```

Optional full Linux smoke test (installs the real environment, downloads
packages into temporary Linux storage):

```bash
python3 tests/smoke_pixi_sandbox.py
```

It installs the locked `agents` environment, launches real Pi inside bubblewrap
with the Windows-workspace layout, and verifies `/models` registration plus
discovery of a skill under `workspace/.agents/skills/`, without any model API
calls. Also run Bash syntax checks and ShellCheck over `wsl/scripts`, and install
both Pixi environments to validate the local build recipes. Never claim Windows
support based on the Python tests alone.

The Linux suite checks that the extension pins and the Pi version are what the
repository claims. It cannot show that delegation works: no test starts a child
session, and none of them calls a model. See the checklist items on delegation.

## Required Windows 11 x64 acceptance matrix

Test on clean Home and Pro machines/VMs with virtualization enabled:

- [ ] No WSL: Install.cmd elevates only feature setup; reboot/rerun works under
      the original Windows account. No unwanted default Ubuntu distro is created.
- [ ] Existing WSL and unrelated distros remain unchanged. An unrelated
      `osint-ai` distro is rejected; no distro is unregistered.
- [ ] First install, interrupted install retry, and completed-install rerun
      preserve both checkouts and user state. Paths with spaces, apostrophes and
      non-ASCII work.
- [ ] NTFS selected; OneDrive/junction/UNC paths fail clearly. A private GitHub
      clone prepared by a Windows GUI is reused without importing credentials
      into WSL.
- [ ] Linux checkout is created at `/home/osint/osint-ai` with the right origin;
      the Windows checkout is mounted at `/mnt/osint-ai` on every distro start.
- [ ] Desktop shortcuts work: **OSINT AI Terminal** opens MobaXterm, runs
      `pixi r restart-server && pixi r osint-pi-wsl`, and reaches the chat
      prompt. **OSINT AI Terminal (basic)** works when MobaXterm is absent or
      refuses the command. **OSINT AI Files** opens the checkout.
- [ ] MobaXterm: an existing installation is reused, not duplicated. The download
      is checksum verified, `-SkipMobaXterm` skips it, and a tampered download is
      refused.
- [ ] WSL termination/restart remounts `/mnt/osint-ai` before any Pixi
      invocation. A failed mount fails closed instead of writing to NTFS.
- [ ] Chatbot starts with `workspace/` of the Windows checkout as its directory.
      `/opt/osint-ai/project` is present and read-only; `pixi add` and writes to
      root files fail inside the session.
- [ ] No `.git`, `C:\`, other drives, `\\wsl$`, `/dev/dxg`, WSL interop sockets
      or host home directories are reachable from inside the session.
- [ ] `/run/git-status` matches GitHub Desktop: clean, modified, untracked and
      ahead-of-remote cases each produce the expected reminder wording.
- [ ] New skill lands in `workspace\.agents\skills\<name>\SKILL.md`; Notepad
      sees it immediately and
      `/reload` + `/skill:<name>` find it. `workspace\AGENTS.md` is loaded and
      editable. Nothing is written to `~/.pi` or `~/.agents`.
- [ ] `spreadsheet-reader` reads `.xls`, `.xlsx`, `.xlsb`, `.csv`, warns on a
      mislabelled file, and never modifies the source.
- [ ] `compliance-report` produces a report with the agreed section order, a
      confidence label on every fact, a populated `Sources` list, and nothing
      invented; the Markdown is left in `workspace\reports\` next to the PDF.
- [ ] `markdown-pdf` produces a PDF whose title is printed **once**, with the
      date and the optional contents list after it, that `pdfinfo`/`pdftotext`
      confirm and whose rendered page image is readable; `.notdef glyph`
      warnings are reported to the user instead of shipping empty boxes;
      scanned PDFs are reported as unreadable.
- [ ] Windows junctions, symlinks, hardlinks and rename races across the shared
      directory boundary are tested. These require Windows tests, not Linux mocks.
- [ ] OpenRouter OAuth URL/callback paste and API-key login work. Login,
      sessions, settings and extension state persist after a restart.
- [ ] Delegation: the assistant hands a wide research job to a sub-agent, the
      child finishes, and the answer arrives with links and dates. The child
      creates no file outside `workspace\`; it cannot read the Linux checkout,
      `C:\`, or a `.git`; a child that asks for a Git worktree fails cleanly
      instead of hanging. Note the extra time on a local model.
- [ ] No NVIDIA GPU: `restart-server` reports the CPU fallback, exits 0, the
      desktop chain continues, and a small model answers (slowly). Accept only a
      real answer, not `nvidia-smi` output.
- [ ] Supported NVIDIA GPU + driver: `restart-server` selects CUDA and the model
      really offloads. `stop-server` and `restart-server` are idempotent;
      occupied port, timeout and crash are reported; cached weights survive.
- [ ] Server listens on WSL loopback only, not the LAN. The agent cannot edit its
      executable, libraries or presets.
- [ ] `pixi r update-project` updates a WSL installation and the next chatbot
      start uses the new tools; a diverged Linux checkout is refused.
- [ ] README uninstall steps work in order on a used installation: unregistered
      distro, `%LOCALAPPDATA\osint-ai` gone, icons gone, no other distro touched,
      `wsl --uninstall` not required. Reinstall + **Pull** restores skills and
      `workspace/AGENTS.md`, and a deleted OpenRouter key stops working.

## Release gates still outside skeleton

Signed Windows installer, published immutable release, full supply-chain lock and
update process, download/disk-space UX, installer rollback/uninstall, automated
Windows VM tests, supported GPU/driver matrix, security review, resource quotas,
and model presets appropriate for supported consumer hardware.
