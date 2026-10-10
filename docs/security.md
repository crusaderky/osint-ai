# Security design and limits

This is a first implementation, not an audited security product. Do not
distribute it as protection from hostile malware until Windows acceptance and
security tests have passed. Bubblewrap is the enforcement mechanism; AGENTS.md
is guidance only.

## Trust boundaries

1. Windows installer and first cloned release are trusted. Pin a reviewed
   release tag when packaging; a mutable `main` default is for skeleton
   development only. Ubuntu rootfs, Pixi binary (both the Linux and the Windows
   one), every llama.cpp release asset the recipe installs on either platform, and
   the optional MobaXterm download are SHA-256 verified. Apt/Conda/npm retain their
   upstream trust and supply-chain risks. A writable `.git` inside the sandbox
   (item 5) means a compromised or misled agent can alter this repository's
   history; the release pipeline must therefore pin by tag and verify the
   signature of what it downloads, not trust the working tree. On the Windows
   deployment that history is also the checkout local inference runs from: see
   item 6 and the maintenance section.
2. WSL root provisions the boot mount helper (`windows/mount-workspace.py`) and
   the launchers once. Every Linux Pixi environment - the assistant's and, where it
   is installed, the optional inference one - belongs to the unprivileged `osint`
   user inside the Linux checkout, so root never executes a manifest the user can
   edit. The Windows deployment's inference environment is the exception, and only
   because it cannot be any other way: the Windows installer installs it as the
   ordinary Windows user, out of the Windows checkout as it was cloned at install
   time. Its own trust story is item 6. The root helper
   reads only `/etc/osint-ai.json`; no project shell code
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
   functional agent can use tools but cannot install or replace them. The
   bubblewrap that builds the namespace comes from that same environment
   (`<project root>/.pixi/envs/default/bin/bwrap`) and not from `/usr/bin/bwrap`,
   so the containment itself is pinned by `pixi.lock` and replaced by
   `update-project` together with the tools, instead of being whatever the
   distribution happens to ship. Ubuntu 23.10 and later grant a user namespace per
   executable path, so that binary needs an AppArmor profile naming it:
   `scripts/install-apparmor.sh` writes and loads it, and it is the only root step
   a Linux installation has.
4. `scripts/sandbox.py` builds an allowlisted root filesystem with a cleared
   environment: `/usr` etc. read-only, the persistent agent home at
   `/home/osint`, and the checkout the agent works in mounted **whole** and
   read-write at `/osint-ai` — the Windows checkout in WSL, the single checkout
   in plain Linux — with its `.git`. Pi starts in `/osint-ai/workspace`, a
   directory inside that mount, because Git finds its repository by walking up
   from the working directory; a workspace mounted on its own would leave no
   `.git` above it. In WSL the Linux checkout stays read-only at
   `/opt/osint-ai/project` with its own `.git` masked by a tmpfs, so the code
   that starts the next session and its history stay out of reach, and the host
   path `/mnt/osint-ai` is not mirrored inside. In plain Linux, where the
   writable checkout also holds the Pixi environment, `.pixi` is re-bound
   read-only on top of it, so the tools the assistant runs on still cannot be
   replaced from inside. No blanket `/` bind, Windows drive other than the
   selected checkout, WSL interop socket, host `/run` or host home enters the
   sandbox. `/etc` is a fresh directory holding only allowlisted files, and
   `/etc/alternatives` is one of them: without it `/usr/bin/which`, `/usr/bin/awk`
   and the other Debian alternatives symlinks dangle, which looks like
   "`which`: command not found". Networking stays enabled.

   The agent home is persistent on purpose: it is `HOME`, and Pi's sign-in,
   sessions and settings live in `~/.pi` inside it. The program-owned files there
   - `~/.pi/agent/keybindings.json` and `~/.pi/web-search.json` - are **not copied
   in**: the launcher binds the environment's copies read-only over whatever the
   home holds at those paths, so they always match the installed program, the agent
   cannot rewrite them, and a stale copy left by an older version is shadowed
   instead of quietly kept. The assistant's instructions are not program files at
   all: they are `workspace/AGENTS.md` in the checkout the agent works in, named
   on Pi's command line with `--append-system-prompt`. Pi's own context-file
   discovery is switched off with `--no-context-files`, because Pi loads a context
   file from its working directory **and from every parent directory** and nothing
   in Pi limits that walk: the checkout root's `AGENTS.md` - the maintainer's file
   about the manifest, the tests and the sandbox itself - is a parent of the
   workspace, and the assistant must not follow it. Hiding that file with a
   read-only bind mount would work against Pi but not against Git: `git status`
   in the agent's own checkout would report `AGENTS.md` as modified, and `git add
   -A` plus `git commit`, both allowed by item 5, would write an empty file over
   the maintainer's instructions in the checkout the user pushes from. Because Pi
   also reads `~/.pi/agent/AGENTS.md` when discovery is on, `scripts/pi-entry.sh`
   renames a leftover copy from an older
   version to `AGENTS.md.stale`, so an outdated guide cannot steer the assistant;
   nothing in the home is deleted. `~/.pi/agent/settings.json` is the opposite
   case: Pi writes it, so
   it stays a real file in the home, and `scripts/pi-entry.sh` rewrites the two
   keys that name sandbox mount paths (`packages` and `skills`) on every launch.
   Its `enabledModels` key is merged rather than rewritten: the launcher adds the
   patterns from `model-shortlist.json` in the **program** checkout - read-only in
   WSL, so the assistant cannot widen its own model list from its own checkout -
   and keeps every model the user saved, so a shortlist update cannot remove a
   sign-in's model.
   `~/.pi/agent/models.json` is generated the same way, for the same reason: it
   names the local model server, whose address is loopback on plain Linux and the
   Windows host inside WSL, and WSL hands a different address out after a restart.
   A shipped copy would go stale silently, and the assistant would list models it
   cannot reach.
   `~/.pi/agent/npm` is a symlink into the read-only environment, re-pointed when
   it does not match the current one: a link left by an older layout dangles, and
   Node follows it and fails with `ENOENT` rather than reporting the real cause.

   Where the credentials physically are: `~/.pi/agent/auth.json` (provider API
   keys and OAuth tokens) and `~/.pi/agent/mcp-auth.json` are in the agent home,
   which is `~/.local/state/osint-ai/agent-home` in **both** deployments - in WSL
   that means `/home/osint/.local/state/osint-ai/agent-home`, inside the private
   distro. There is no separate WSL state directory: the only thing a deployment
   changes is which checkout the workspace comes from, and `OSINT_STATE_DIR` is the
   one override for the rest. They are never in a checkout, never on a Windows
   drive, and therefore never committable. That directory is private:
   `scripts/sandbox.py` creates it and re-applies `0700` on every launch, because
   `mkdir` inherits the umask and a shared PC would otherwise leave a credential
   store group-readable; a home created by an older version is repaired rather than
   left open, and the Windows installer no longer pre-creates one.
   `scripts/pi-entry.sh` does the same for `~/.pi` and `~/.pi/agent`.
5. The agent runs Git itself, in a real and writable repository, by deliberate
   maintainer decision. `workspace/AGENTS.md` lets it run `git status`, `git add`
   and `git commit`, puts it on the one development branch `staging` (it may
   switch `main` -> `staging` and merge `main` into `staging`) and forbids it to
   push, switch to any other branch, rebase, reset or discard work, so the user
   still publishes in the Windows GUI. That is
   guidance, not enforcement: the sandbox permits a `reset --hard` of the user's
   uncommitted work, a history rewrite, or a push if WSL ever held a credential.
   The installer never imports GitHub Desktop's credentials, so a push is
   expected to fail; committing and destroying local work need no credential at
   all. `tests/test_skeleton.py` asserts that a commit from inside the sandbox
   succeeds and that `git status` works from Pi's own working directory, so
   neither fact can quietly change. The launcher no longer runs any Git itself.
   It does supply the commit identity, as `GIT_AUTHOR_*` and `GIT_COMMITTER_*`
   in the sandbox environment: the agent home has no `~/.gitconfig` and the
   Windows user's own identity is not mounted, so Git would otherwise refuse
   every commit with "Author identity unknown". Assistant commits are therefore
   attributed to `OSINT AI assistant <assistant@osint-ai.invalid>`, which also
   lets the reviewer tell them apart in GitHub Desktop.
6. Inference runs outside bubblewrap, and the two deployments put it in different
   places:

   * Plain Linux and WSL: the ordinary Linux user runs it out of the project root
     checkout's `llamacpp-binary-vulkan` environment. That environment is installed
     by Pixi from the reviewed manifest and is **read-only** inside the sandbox, so
     nothing the agent writes can change the binary, the libraries or `models.ini`.
     The server binds loopback only and the agent talks to it over HTTP.
   * Windows: llama.cpp runs natively on Windows, in the **Windows checkout's** own
     environment, because that is where the GPU driver is. That checkout is the one
     the agent may write to and commit in (item 5), so this is the one place where
     agent-writable content is executed outside the sandbox - by a human clicking
     **Start llama.cpp**. The installer uses `--locked` everywhere so a manifest
     that does not match `pixi.lock` fails instead of cooking up a new environment,
     and the human reviews that checkout before clicking, exactly as they review
     what they push. Do not weaken this by pointing the icons at some other path, and
     do not move the Windows environment somewhere the reviewer cannot see it.
     The server binds `0.0.0.0` there, because the assistant inside WSL is a
     different network namespace and loopback would find nothing; the boundary is
     the inbound firewall rule the installer adds, which admits TCP 8080 from the
     WSL virtual adapter and the local subnet only. That server is unauthenticated,
     like any llama.cpp server: it is reachable from inside WSL, which the agent
     also reaches, and from nothing else on the network unless the rule is
     tampered with.

   In both cases, with no working Vulkan device the same build starts on the CPU with
   GPU offloading disabled, which changes performance, not the boundary. The
   backend is recorded in the state directory's `server.json`, and the weights
   llama.cpp downloads stay in the standard Hugging Face cache, outside every
   sandbox.
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
   directory. The pinned pi-subagents excludes `.agents/skills/**` from that
   scan, so a skill file is never loaded as an agent.
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
- In plain Linux the agent's checkout is also the program, and it is writable
  there because `git commit` needs `../.git`. Only `.pixi` is read-only. The
  assistant is told not to edit `scripts/`, `windows/`, `tests/`, `docs/`,
  `pixi.toml` or `models.ini`; that is guidance, and the human reviews the diff.
  In WSL the program is a separate read-only checkout and this does not apply.
- Any user who runs edited project content outside the sandbox grants it normal
  WSL-user privileges, or normal Windows-user privileges for the natively running
  model server. `pixi r install` - including its AppArmor step, one of the few
  places the project asks for a password - `pixi r update-project`, the Windows
  installer and the **Start llama.cpp** / **Stop llama.cpp** desktop icons are
  trusted human operations, not startup paths and never agent
  tools. Both install scripts refuse to run when `OSINT_SANDBOX=1`, and the icons
  run `pixi run --locked` so a manifest that drifted from `pixi.lock` fails instead
  of installing something else.
  `update-project` runs the newly pulled manifest's environment install.
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
  Global device access is absent from the agent; on the Windows deployment the GPU
  is reached by llama.cpp running natively on Windows, outside WSL and outside the
  sandbox, which is why the agent never needs a device node at all. On plain Linux
  and in WSL the optional local server still reaches the GPU outside bubblewrap as
  explicitly required.
- MobaXterm is third-party software started by a desktop shortcut with a fixed
  command. It is not part of the trust boundary, and its licence must be
  reviewed before redistribution.

## Maintenance

Local inference is the `llamacpp-binary-vulkan` Pixi environment, not a root-owned
copy under `/opt`. On plain Linux and in WSL it belongs to the project root
checkout, which is read-only inside the sandbox in WSL and writable in plain Linux
because that checkout is also the program there - the human reviews the diff before
running `pixi r update-project` or `pixi r start-server`. On the Windows deployment
it belongs to the **Windows** checkout, together with the natively installed Pixi,
and rerunning `windows/Install.cmd` is what refreshes it; `scripts/server.py`
resolves that checkout from `PIXI_PROJECT_ROOT`, which the desktop icon's `pixi run`
sets, so a stale or edited manifest is a reviewed change rather than a surprise.
Downloaded weights are outside all of it: llama.cpp writes them to the standard
Hugging Face cache under the user's home, which the sandbox does not mount.
Inference state - pid file and log - is in `/var/lib/osint-ai` (WSL, pre-created),
`~/.local/state/osint-ai` (plain Linux) or `%LOCALAPPDATA%\osint-ai` (Windows).
Never "fix" this by running an agent-editable `pixi run start-server` inside
containment: `scripts/server.py` refuses when `OSINT_SANDBOX=1` and must keep
refusing. Do not add passwordless
sudo of a project script, do not load commands from the writable Windows checkout
into `/etc/wsl.conf`, and do not point the boot helper at anything but
`/etc/osint-ai.json`. Existing installations are not silently upgraded.
