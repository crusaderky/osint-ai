# Security design and limits

This is a first implementation, not an audited security product. Do not
distribute it as protection from hostile malware until Windows acceptance and
security tests have passed. Bubblewrap is the enforcement mechanism; AGENTS.md
is guidance only.

## Trust boundaries

1. Windows installer and first cloned release are trusted. Pin a reviewed
   release tag when packaging; a mutable `main` default is for skeleton
   development only. Ubuntu rootfs, Pixi binary, llama.cpp release asset and the
   optional MobaXterm download are SHA-256 verified. Apt/Conda/npm retain their
   upstream trust and supply-chain risks.
2. WSL root provisions the boot mount helper, launchers and inference snapshot
   once. The root helper reads only `/etc/osint-ai.json`; no project shell code
   or config is sourced at boot. It mounts the Windows drive under a root-only
   directory, binds the selected checkout to `/mnt/osint-ai`, then removes the
   whole-drive mount. Directory file descriptors pin bind-mount sources and
   targets; mount canonicalization is disabled so those handles are not converted
   back to mutable pathnames.
3. The Linux checkout (`/home/osint/osint-ai`) owns Git, the manifest and every
   Linux environment. The sandboxed agent gets it **read-only**, so nothing the
   agent writes can change what runs next. `pixi r osint-pi-wsl` is a thin
   wrapper: the outer Pixi reads only that unmodifiable manifest, then execs the
   root-owned launcher, which enters bubblewrap before Pi starts. The
   `agents` environment is also mounted read-only inside the sandbox, so a
   functional agent can use tools but cannot install or replace them.
4. `sandbox.py` builds an allowlisted root filesystem with a cleared
   environment: `/usr` etc. read-only, the Linux checkout read-only at
   `/opt/osint-ai/project`, the functional workspace read-write at `/workspace`,
   the persistent agent home at `/home/osint`. No `.git` from either checkout is
   exposed. No blanket `/` bind, Windows drive, WSL interop socket, host `/run`
   or host home enters the sandbox. Networking stays enabled.
5. Git belongs to the human's Windows GUI. To let the assistant remind the user
   about unsaved work, the launcher runs a read-only `git status` **outside** the
   sandbox with hooks, fsmonitor, system config, global config and optional lock
   files disabled, and exposes the summary read-only at `/run/git-status`. The
   agent never gets a Git binary with a reachable repository, and never gets
   credentials.
6. Inference intentionally runs outside bubblewrap under the ordinary WSL user.
   It never executes the project manifest or the project environment: its
   binaries, libraries and model presets are a root-owned snapshot with a
   separate package cache. The server binds WSL loopback only; the agent talks to
   it over HTTP. With no working CUDA device it starts the same build on the CPU
   with GPU offloading disabled, which changes performance, not the boundary.
7. The normal WSL user is not a sudoer. The Windows owner can still enter the
   distro as root; protecting against the machine owner is not a goal.
8. Delegation (pi-subagents) adds processes, not privileges. A child session is
   a fork inside the same bubblewrap namespace, so it inherits the same PID
   namespace, the same cleared environment, the read-only project root and the
   same writable `/workspace` and `/home/osint`. Nothing in pi-subagents
   re-enters the launcher or rebinds a mount. The gaps are resource and
   discovery, not isolation: several children can run at once against a local
   server configured with `parallel = 1`, and the extension reads sub-agent
   definitions from the project's legacy `.agents/**/*.md` tree, which here is
   the user's skill directory. pi-subagents 0.71.0 excludes `.agents/skills/**`
   from that scan, so a skill file is never loaded as an agent. No
   `pi-intercom` extension is installed, so there is no session-messaging
   broker to share or to isolate.

## Explicit limitations

- The sandbox can send any readable data over the network. Pi provider
  credentials must be available to Pi and are not isolated from its shell
  tools/extensions.
- Network isolation is not attempted. Local/LAN services can be reached,
  including inference and browser OAuth callback listeners. Network-mounted
  files/services are not covered by filesystem hiding.
- The agent can delete or poison writable workspace content, skills, reports and
  its own state. Human review, backups and Git history remain necessary.
  Generated skills and scripts are code, not inert documents.
- Any user who runs edited project content outside the sandbox grants it normal
  WSL-user privileges. `pixi r install`, `pixi r update-project` and the Windows
  installer are trusted human operations, not startup paths and never agent
  tools. `update-project` runs the newly pulled manifest's environment install.
- The native inference HTTP/model parser is not sandboxed. Use trusted model
  sources. Its model-management API must not be treated as a hardened untrusted
  file broker. Review server security updates separately.
- Windows NTFS reparse points/junctions, hardlinks, DrvFS semantics and
  concurrent Windows edits need adversarial validation. Linux symlink tests
  alone do not establish that Windows filesystem paths cannot bypass intended
  boundaries.
- No resource quotas yet: malicious code can consume CPU, memory, disk or
  network. CPU-mode inference shares those limits with the assistant. A
  sub-agent run multiplies this: children are additional concurrent clients of
  the one inference server, and `models.ini` serves them one at a time.
- Delegation cannot create a Git worktree. The sandbox exposes no `.git`, so the
  extension's worktree-backed isolation always fails and its Git-dependent
  features are unavailable, by design.
- Browser, clipboard and Windows executable bridging are deliberately omitted.
  OAuth uses displayed URLs and manual copy/paste, not generic host execution.
  Global device access is absent from the agent; CUDA inference retains WSL GPU
  access outside bubblewrap as explicitly required.
- MobaXterm is third-party software started by a desktop shortcut with a fixed
  command. It is not part of the trust boundary, and its licence must be
  reviewed before redistribution.

## Maintenance

`start-server` ignores later edits to checkout `models.ini` and inference
recipes. The maintainer must review and reinstall that trusted snapshot
deliberately; nothing applies it automatically. Never "fix" this by running an
agent-editable `pixi run start-server` inside containment. Do not add
passwordless sudo of a project script, do not load commands from the writable
Windows checkout into `/etc/wsl.conf`, and do not point the boot helper at
anything but `/etc/osint-ai.json`. Existing installations are not silently
upgraded.
