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
   upstream trust and supply-chain risks. A writable `.git` inside the sandbox
   (item 5) means a compromised or misled agent can alter this repository's
   history; the release pipeline must therefore pin by tag and verify the
   signature of what it downloads, not trust the working tree.
2. WSL root provisions the boot mount helper (`windows/mount-workspace.py`),
   launchers and inference snapshot once. The root helper reads only
   `/etc/osint-ai.json`; no project shell code
   or config is sourced at boot. It mounts the Windows drive under a root-only
   directory, binds the selected checkout to `/mnt/osint-ai`, then removes the
   whole-drive mount. Directory file descriptors pin bind-mount sources and
   targets; mount canonicalization is disabled so those handles are not converted
   back to mutable pathnames.
3. The Linux checkout (`/home/osint/osint-ai`) owns Git, the manifest and every
   Linux environment. The sandboxed agent gets it **read-only**, so nothing the
   agent writes can change what runs next. `pixi r osint-pi-wsl` is a thin
   wrapper around `scripts/bwrap-pi.sh --wsl`: the outer Pixi reads only that
   unmodifiable manifest, then execs the root-owned launcher, which enters
   bubblewrap before Pi starts. The
   `default` environment is also mounted read-only inside the sandbox, so a
   functional agent can use tools but cannot install or replace them.
4. `scripts/sandbox.py` builds an allowlisted root filesystem with a cleared
   environment: `/usr` etc. read-only, the persistent agent home at
   `/home/osint`, the functional workspace read-write at `/workspace`, and the
   checkout the agent works in read-write **with its `.git`** — the Windows
   checkout at `/mnt/osint-ai` in WSL, the project root itself in plain Linux.
   In WSL the Linux checkout stays read-only at `/opt/osint-ai/project` with its
   own `.git` masked by a tmpfs, so the code that starts the next session and
   its history stay out of reach. In plain Linux, where the writable project root
   also holds the Pixi environment, `.pixi` is re-bound read-only on top of it,
   so the tools the assistant runs on still cannot be replaced from inside. No
   blanket `/` bind, Windows drive other than the selected checkout, WSL interop
   socket, host `/run` or host home enters the sandbox. Networking stays
   enabled.
5. The agent runs Git itself, in a real and writable repository, by deliberate
   maintainer decision. `workspace/AGENTS.md` tells it to run `git status` and
   forbids it to commit, push, switch branches or discard work, so the user
   still reviews and publishes in the Windows GUI. That is guidance, not
   enforcement: the sandbox would permit a commit, a `reset --hard` of the
   user's uncommitted work, a history rewrite, or a push if WSL ever held a
   credential. The installer never imports GitHub Desktop's credentials, so a
   push is expected to fail; committing and destroying local work need no
   credential at all. `tests/test_skeleton.py` asserts that a commit from inside
   the sandbox succeeds, so this cannot quietly change. The launcher no longer
   runs any Git itself.
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
   namespace, the same cleared environment and the same mounts: the read-only
   program checkout, the read-only environment, and the writable agent checkout
   with its `.git` (item 5). Nothing in pi-subagents re-enters the launcher or
   rebinds a mount. The gaps are resource and discovery, not isolation: several
   children can run at once against a local server configured with
   `parallel = 1`, and the extension reads sub-agent definitions from the
   project's legacy `.agents/**/*.md` tree, which here is the user's skill
   directory. pi-subagents 0.71.0 excludes `.agents/skills/**` from that scan,
   so a skill file is never loaded as an agent.
9. Session messaging (pi-intercom) is a per-launch local broker on a Unix
   socket in a fresh tmpfs at `~/.pi/agent/intercom`, created by the launcher
   after the agent home is bound. The socket is created 0600 inside a 0700
   directory, so it is reachable only from inside this sandbox, and a parent
   session and its sub-agent children share it. A persistent home would let a
   second terminal window unlink the running broker's socket at startup and
   would redeliver mail queued for a closed session to a later one; the tmpfs
   removes both. Nothing outside bubblewrap, including the host's own unsandboxed
   Pi and the inference server, can reach the socket. Only the Unix transport is
   used: the loopback-TCP escape hatch is not enabled, and it would be
   reachable from any process on WSL loopback anyway.

## Explicit limitations

- The sandbox can send any readable data over the network. Pi provider
  credentials must be available to Pi and are not isolated from its shell
  tools/extensions.
- Network isolation is not attempted. Local/LAN services can be reached,
  including inference and browser OAuth callback listeners. Network-mounted
  files/services are not covered by filesystem hiding.
- The agent can delete or poison writable workspace content, skills, reports and
  its own state, and it can rewrite the history of the checkout it works in.
  Human review, backups and Git history remain necessary. Generated skills and
  scripts are code, not inert documents.
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
- Delegation can create a Git worktree of the checkout the agent works in,
  because that repository is writable. The branch and history it produces are
  the user's to review; the same rule applies as for any other change. The Linux
  checkout's repository stays masked in WSL, so no worktree of the program can be
  made.
- Each sandbox gets its own intercom broker, so two separate assistant windows
  cannot message each other, and no message survives a restart. Both are
  deliberate. Session messaging inside one window, including between a parent
  and its sub-agents, is unaffected.
- The intercom `config.json` lives in that tmpfs, so options such as
  `inboundTrigger` and `confirmSend` cannot be set by the user and reset at
  every launch. Inbound messages can start a turn in the receiving session, so a
  sub-agent can prompt the parent. The user is told what happened; the user
  cannot be addressed from inside the sandbox, because that would mean a
  project-side bridge to the host, which this design does not have.
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
