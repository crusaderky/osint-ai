# Developer guide

The [README](../README.md) is the absolute-beginner guide. Keep implementation,
packaging and troubleshooting details here rather than in that guide.

Related documentation:

- [Security design and limits](security.md)
- [Tests and Windows release checklist](testing.md)
- [Copied components and upstream provenance](upstream.md)

## Two checkouts, two jobs

| Directory | Who works there | What lives there |
| --- | --- | --- |
| Project root (this checkout) | Maintainer. Start Pi here for code work. | Git, `pixi.toml`, `pixi.lock`, `scripts/`, `windows/`, `pixi-recipes/`, `tests/`, `docs/`, `README.md`, `AGENTS.md` |
| `workspace/` | Compliance officer, through the chatbot | `AGENTS.md` (working rules) and `.agents/skills/` (user-authored skills), plus research output |

On Linux that is the whole picture: one checkout, and `workspace/` inside it.

Windows has a second copy of the same repository. The user's checkout is
`C:\Users\<name>\osint-ai`, which WSL mounts at `/mnt/osint-ai`. A second
checkout at `/home/osint/osint-ai`, inside the private WSL distro, owns Git, the
Pixi environments and everything that executes. The Windows checkout is what the
assistant works in and what its Git reports on.

```text
Linux checkout /home/osint/osint-ai        --read-only-->  /opt/osint-ai/project  (sandbox)
Windows checkout /mnt/osint-ai             --read-write--> /osint-ai              (sandbox)
                                                              ^ Pi starts in /osint-ai/workspace
```

In plain Linux the single checkout takes the read-write role, so it is mounted
whole at `/osint-ai` as well and Pi starts in `/osint-ai/workspace`. The agent's
checkout is at the same sandbox path in both deployments; only the read-only
program mount exists in one of them.

The checkout is mounted **whole**, never as a bare `workspace/` bind. Git finds
its repository by walking up from the working directory, so a workspace mounted
on its own has no `.git` above it and every `git status` the guidance promises
fails with "not a git repository".

That separation is the reason `pixi.toml` edited in the Windows checkout changes
nothing that runs. The runtime never rsyncs, symlinks or duplicates anything
between them. Instead, one command per deployment keeps them in step, and both
run the same branch helper, `scripts/git-branches.sh`:

| Deployment | Command | What it does |
| --- | --- | --- |
| Plain Linux | `pixi r update-project` | fast-forwards `main`, fast-forwards `staging`, merges `main` into `staging` |
| Windows | the **Update OSINT AI** desktop shortcut | the same for the Windows checkout, plus the Linux checkout's `main` and its Pixi environments, plus the root-owned runtime in `/usr/local` |

The branch rule is the same everywhere: `main` is the published program and only
ever moves forward; `staging` receives it and keeps whatever the assistant has
committed but not published. A checkout with no `staging` branch - the WSL
program checkout is cloned with `--branch main` on purpose - only fast-forwards
its `main`. Nothing is ever pushed, discarded, rebased or conflict-resolved: a
checkout that cannot be updated is left exactly as it was, and a branch that
moved on in two places is reported for the human to reconcile in their Git app.

## One launcher, two arguments

`scripts/bwrap-pi.sh` starts the assistant on both platforms. The first argument
picks the deployment; the rest goes to Pi.

| Argument | Assistant works in | Used by |
| --- | --- | --- |
| `--native` | `/osint-ai/workspace`, the `workspace/` of the checkout that holds `pixi.toml` | `pixi r osint-pi`, and `/usr/local/bin/osint-pi` inside WSL |
| `--wsl` | `/osint-ai/workspace`, the `workspace/` of `/mnt/osint-ai` | `pixi r osint-pi-wsl`, `/usr/local/bin/osint-pi-wsl`, the desktop shortcut |

`bwrap-pi.sh` sits in `<checkout>/scripts` and names that checkout as the project
root, so the assistant works in the checkout the manifest belongs to rather than
in whatever directory Pixi happened to be invoked from.

That argument is the **only** deployment-specific choice the launcher makes. The
working directory, the skills path, the read-only environment, the agent home at
`~/.local/state/osint-ai/agent-home` and the sandbox's `/etc` allowlist are the
same on both platforms, so a skill, a session or a setting cannot end up somewhere
the other deployment never looks at.

`scripts/sandbox.py` builds the mount namespace and `scripts/pi-entry.sh` runs
after containment, so Pi is never started outside bubblewrap. The bubblewrap it
execs is the one this project's locked environment installs
(`<project root>/.pixi/envs/<env>/bin/bwrap`), never the distribution's
`/usr/bin/bwrap`: `update-project` replaces the containment along with Pi and the
skill tools, and a PC whose distro ships no bubblewrap at all is unaffected.
Ubuntu needs an AppArmor profile for that path; `pixi r install` loads it and then
proves the binary can start a sandbox. When the root-owned
copies in `/usr/local/lib/osint-ai` exist they are used instead of the checkout
copies, so an installed PC runs the code it installed rather than whatever the
checkout happens to contain. Those copies are installed by
`windows/install-runtime.sh`: on the first installation from the checkout being
installed, on a later run of Install.cmd from the Linux program checkout when it
already carries the installer and otherwise from the checkout being installed, and
on every click of the Update OSINT AI icon from the Linux program checkout - which
is why a change to `scripts/` reaches an installed PC at all. In `wsl` mode the
Linux checkout is read-only at
`/opt/osint-ai/project` with its `.git` masked, and the Windows checkout is
mounted read-write at `/osint-ai`. In `native` mode the single checkout is
mounted read-write at `/osint-ai` and `.pixi` is re-mounted read-only on top of
it, so the tools the assistant runs cannot be replaced from inside. See
[security.md](security.md).

## Windows installation and packaging

Supported target: Windows 11 x64 with hardware virtualization and internet
access. WSL installation may require administrator approval and a reboot, and the
local-inference firewall rule adds one more permission prompt. Local inference uses
a Vulkan build of llama.cpp and starts on the CPU when no Vulkan device answers, so
a GPU is an optimisation rather than a requirement - and any vendor's driver will
do, where the CUDA build only ever used NVIDIA's. Hosted providers never need a
GPU. Installation uses several GB for packages; model weights download separately
on first use.

Distribute the `windows/` folder (`Install.cmd` and `Install.ps1` together). The
bootstrap defaults to `https://github.com/crusaderky/osint-ai.git` and `-Ref
main` for the Linux runtime checkout. The Windows checkout is always put on
`staging` instead, because that is the branch the assistant works on, and
provisioning and the native llama.cpp environment are built from it. Merge
`staging` into `main` and distribute the installer from that merge, so a new
installation provisions the reviewed release; pinning `-Ref` to a release tag is
not enough on its own while the two branches differ. Publish the repository and
installer before directing users at them.

Developer overrides, from PowerShell inside the `windows` folder:

```powershell
.\Install.ps1 -RepositoryUrl https://github.com/YOUR-ORG/osint-ai.git -Ref YOUR-TAG `
    -ProjectPath C:\Users\Alice\osint-ai -LinuxProjectPath /home/osint/osint-ai
```

The bootstrap expects a public repository. For a private one, clone it first with
a Windows Git GUI, fetch its `staging` branch there too, then supply the matching
URL and checkout path. GitHub credentials are not copied into the agent sandbox.

The installer:

- Creates a dedicated `osint-ai` WSL distribution, leaving existing
  distributions unchanged, plus the Windows checkout.
- Verifies pinned Ubuntu and Pixi downloads and never resets an existing
  checkout: it puts the Windows checkout on `staging` and fast-forwards only that
  branch, and does not discard or delete user content.
- Clones the Linux checkout and installs the `default` environment inside it.
- Runs `windows/provision-wsl.sh`, which installs the root-owned launchers, the
  boot mount helper, and the AppArmor profile for the bubblewrap the Linux
  checkout installs. It does **not** install a llama.cpp environment inside the
  distribution: the Windows deployment runs llama.cpp on Windows.
- Installs Pixi natively as well (same pinned version, checksum verified), and with
  it the `llamacpp-binary-vulkan` environment of the Windows checkout. That is what
  runs the model server, so `--locked` is used throughout: a manifest that no
  longer matches `pixi.lock` fails loudly instead of installing something else.
- Adds one inbound Windows firewall rule, bound to the WSL virtual adapter and to
  the local subnet, so the assistant inside WSL can reach the server on Windows.
  It is the only reason the installer asks for permission a second time; a rule
  that is already current needs no prompt.
- Proves that path: starts the server, asks its `/health` from inside the
  distribution at the address `scripts/sandbox.py` resolves, then stops it. A
  failure is reported, not fatal - local inference is optional - and online models
  keep working.
- Reuses an existing MobaXterm installation or downloads the pinned, checksum
  verified portable build (`-SkipMobaXterm` disables the download). MobaXterm is
  third-party freeware under its own licence: check it before redistributing the
  installation package.
- Creates desktop shortcuts: **OSINT AI Terminal** (MobaXterm tab, runs
  `osint-terminal` in the Linux checkout: it reports whether local inference
  answers, then starts the assistant),
  **OSINT AI Terminal (basic)** (plain `wsl.exe` console),
  **Start llama.cpp** and **Stop llama.cpp** (the same `_server` task the Linux
  deployment runs, in the Windows checkout's environment),
  **Update OSINT AI** (see below) and
  **OSINT AI Files** (Windows checkout).
- Preserves user state on a completed-install rerun, and reinstalls the
  root-owned runtime (`windows/install-runtime.sh`) - preferring the Linux checkout,
  which the assistant cannot write - so a rerun is also how a PC installed before a
  change to `scripts/` gets it. The Windows checkout is never reset, and nothing is
  discarded.

Uninstalling is manual and documented for users in the README. In short:
`wsl --unregister osint-ai` deletes the private distribution and its disk, which
holds the Pi credentials, sessions and settings, the Linux checkout and the
root-owned launchers under `/usr/local`. Deleting `%LOCALAPPDATA\osint-ai` removes
the native Pixi binary, the Windows inference environment, its state directory, the
download cache and the portable MobaXterm copy. The downloaded weights are a third
place: `%USERPROFILE%\.cache\huggingface` on the Windows side, and
`~/.cache/huggingface` for a plain Linux install. The inbound firewall rule the
installer added is named `OSINT AI local inference`. The Windows checkout,
including `workspace/`, and everything pushed to GitHub survive all of that, and
`wsl.exe` plus the Windows feature stay installed for other software.

### Updating an installed deployment

The **Update OSINT AI** shortcut is the one human-run update path, and it is never
a startup or agent path. Its wrapper lives outside both checkouts
(`%LOCALAPPDATA%\osint-ai\update-osint-ai.cmd`), so it cannot change with the
commit a checkout happens to be on, and it runs three steps:

1. `windows/update-installation.sh` inside WSL, as root, which updates the Linux
   program checkout and its Pixi environments as the `osint` user, then reinstalls
   the root-owned runtime in `/usr/local` from that checkout
   (`windows/install-runtime.sh`), then updates the Windows checkout with the same
   branch dance as the user who owns it.
2. The local model server is stopped, so that its build can be replaced.
3. The native `llamacpp-binary-vulkan` environment of the Windows checkout is
   installed from the updated manifest, with `--locked`.

Everything that writes to a checkout or an environment runs as `osint`, never as
root: the Windows checkout's `.git` is writable by the assistant, and Git runs
whatever hooks it finds there. Root is used for `/usr/local` and for mounting the
Windows drive, and the Windows checkout's origin is pinned to the Linux
checkout's, which the assistant cannot write - see [security.md](security.md). The
update refuses a checkout with uncommitted work, a checkout on any branch other
than `main` or `staging`, and a checkout whose origin does not match, and it stops
rather than leaving a half-applied state. `docs/testing.md` lists what only a real
Windows PC can confirm.

`pixi r install` is two scripts. `scripts/install-apparmor.sh` is the only root
step a Linux installation has: it asks for your own password, changes nothing when
the profile is already correct, and on Windows it is a no-op because provisioning
already ran it as root. `scripts/install-check.sh` never elevates and never runs
root commands from the checkout; it reports what is set up, what is missing, and it
proves that the pinned bubblewrap can actually start a sandbox.

## Installing on Linux

Deliberately a list of commands and not a script; the Windows installer's other
job is registering a WSL distro as root, and a Linux user has nothing like that
to do.

```bash
# Debian, Ubuntu, Arch: Git, then Pixi from https://pixi.sh.
# No bubblewrap package: the sandbox runs the one this project pins.
git clone https://github.com/crusaderky/osint-ai.git
cd osint-ai && pixi install --locked -e default
pixi r install
pixi r osint-pi
```

The assistant keeps its sign-in, sessions and settings in `~/.local/state/osint-ai`;
override the location with `OSINT_STATE_DIR`. Both are kept at mode `0700`,
because that directory holds `~/.pi/agent/auth.json`.

Ubuntu 23.10 and later - Ubuntu 24.04 included - refuse unprivileged user
namespaces unless the program that asks for one has an AppArmor profile granting
`userns`, and AppArmor attaches a profile to the canonical path of the executable.
Ubuntu's stock `/etc/apparmor.d/bwrap` names only `/usr/bin/bwrap`, which this
project no longer runs, so the sandbox would be refused. `pixi r install` runs
`scripts/install-apparmor.sh`: it writes that stock profile plus
`profile bwrap-pixi <project root>/.pixi/envs/*/bin/bwrap`, loads it with
`apparmor_parser` or `systemctl reload apparmor`, and asks for your password only
when the file has to change. If AppArmor is not in your kernel it says so and does
nothing. A profile names a path, so moving the checkout to another directory means
running `pixi r install` again before the assistant will start.

What a Linux install does not get, because it belongs to the Windows deployment:
the root-owned launchers in `/usr/local`, the boot mount helper, the native Windows
inference environment, the firewall rule and the desktop shortcuts. Hosted models
work as they do on Windows.

Local inference is optional and separate from the assistant: it is the
`llamacpp-binary-vulkan` Pixi environment in this checkout, next to the `default`
one Pi runs on. Installing the assistant never pulls the llama.cpp build, and a PC
without it simply uses a hosted model. There is no separate install step:

```bash
pixi r start-server         # deploys llamacpp-binary-vulkan if needed, then serves 127.0.0.1:8080
pixi r osint-pi             # the assistant; /model lists what the server offers
```

`start-server` and `restart-server` depend on `_server`, a task defined **in the
`llamacpp-binary-vulkan` environment itself** (`[feature.llamacpp-binary-vulkan.tasks]`).
Pixi installs an environment it is about to run a task in, so that is the whole
deployment story: no install task, no wrapper script, no "is the binary there
yet" check. `stop-server` needs no inference program and stays in the default
environment; Windows, where the default environment does not resolve, runs
`pixi run --locked -e llamacpp-binary-vulkan _server stop` from the Stop icon
instead. `scripts/server.py` names its checkout through `PIXI_PROJECT_ROOT`
(set by Pixi), then `/etc/osint-ai.json` (the installed WSL copy), then the
checkout above `scripts/`. In WSL that is the **Linux** checkout: the Windows
checkout is the one the assistant edits, and on the Windows deployment it is the
**Windows** checkout that owns local inference, because that is where llama.cpp
runs. Its manifest is as trusted as the human who reviewed it: see
[security.md](security.md).

The state directory is `/var/lib/osint-ai` when it exists (the WSL deployment
pre-creates it), `%LOCALAPPDATA%\osint-ai` on Windows (beside the native Pixi
binary the installer put there) and `~/.local/state/osint-ai` otherwise, so neither
a plain Linux install nor the Windows one needs a root step for inference. Model
weights are in none of them: llama.cpp uses the standard Hugging Face cache,
`~/.cache/huggingface/hub` and `%USERPROFILE%\.cache\huggingface\hub` on Windows,
outside the sandbox.

## Filesystem and process layout

| Location | Purpose |
| --- | --- |
| Windows checkout | Everything the user commits: `workspace/AGENTS.md`, `workspace/.agents/skills/`, reports |
| `/mnt/osint-ai` | That checkout, bind-mounted from DrvFS by the root-owned boot hook (WSL host only) |
| `/home/osint/osint-ai` | Linux checkout: `pixi.toml`, `.pixi`, code that runs |
| `/opt/osint-ai/project` | The Linux checkout inside the sandbox, read-only, with its `.git` masked (WSL only) |
| `/osint-ai` | The checkout the agent works in, read-write with its `.git`: the Windows checkout in WSL, the single checkout in plain Linux |
| `/osint-ai/workspace` | Pi's working directory, inside that checkout, so Git finds `.git` above it |
| `/osint-ai/AGENTS.md` | The maintainer's guide, present in the agent's checkout because it is the same repository. Pi loads a context file from the working directory **and from every parent directory**, and nothing in Pi limits that walk, so `scripts/pi-entry.sh` starts Pi with `--no-context-files` and names `workspace/AGENTS.md` with `--append-system-prompt`: the assistant gets its own guide and no other instructions. Shadowing this file with a bind mount is the wrong fix - `git status` would report a modified `AGENTS.md` in the checkout the assistant is allowed to commit from, and a commit would write an empty file over the maintainer's instructions |
| `/home/osint` | `HOME`, a bind of the persistent agent home (mode `0700`): Pi sign-in (`~/.pi/agent/auth.json`), sessions, settings, caches. Host path in **both** deployments: `~/.local/state/osint-ai/agent-home` of the Linux user that runs the launcher - `/home/osint/.local/state/osint-ai/agent-home` in WSL. Override with `OSINT_STATE_DIR` |
| `/home/osint/.pi/agent/keybindings.json`, `/home/osint/.pi/web-search.json` | The environment's copies, bound read-only over the home: always current, never rewritten by the agent or fossilised by an upgrade |
| `/home/osint/.pi/agent/AGENTS.md` | Not mounted and not shipped. The assistant's instructions are `workspace/AGENTS.md` in its own checkout, named on Pi's command line; Pi's context-file discovery is off, so neither this path nor the checkout root's `AGENTS.md` is loaded. A copy left there by an older version is still renamed to `AGENTS.md.stale` on the next launch, so the persistent home does not keep a stale guide |
| `/home/osint/.pi/agent/settings.json` | Generated each launch in the home, because Pi writes settings there; `packages` and `skills` are rewritten by the launcher, and `enabledModels` is extended with the model shortlist |
| `model-shortlist.json` (project root) | The models the assistant is offered, as `provider/modelId` patterns. `scripts/pi-entry.sh` reads it from the **program** checkout - `/opt/osint-ai/project/model-shortlist.json` in WSL, read-only, and `/osint-ai/model-shortlist.json` on plain Linux - and merges it into `~/.pi/agent/settings.json` additively: entries the user saved are kept, missing ones are added, nothing is duplicated |
| `/home/osint/.pi/agent/models.json` | Generated each launch from `pixi-recipes/pi-home/models.json`, because the address of the local model server differs per deployment: loopback on Linux, the Windows host inside WSL, and WSL hands a new address out whenever it restarts |
| `/home/osint/.pi/agent/intercom` | Per-launch tmpfs: the pi-intercom broker socket, PID file and queued mail |
| `~/.cache/huggingface/hub`, `%USERPROFILE%\.cache\huggingface\hub` | Downloaded model weights: the standard Hugging Face cache, inference only and outside the sandbox, under the `osint` user's home in WSL and the same path on plain Linux, under the Windows user's profile for the native server. Shared with anything else on the PC that downloads from Hugging Face, so weights are not duplicated |
| `/var/lib/osint-ai/server-state/`, `%LOCALAPPDATA%\osint-ai\server-state\` | Inference server log and pid file (the WSL deployment pre-creates the first; the native Windows server owns the second) |

Inside the sandbox the agent works in a real Git checkout: it can read the whole
history and, with `.git` writable, commit or discard work. Guidance puts it on
`staging`, lets it switch `main` -> `staging` and merge `main` into `staging`,
and forbids pushing, other branch switches and discarding; the user reviews the
result. It never sees the Windows drive root, other drives, host homes, WSL
interop sockets or GPU devices, and in WSL it never sees the Linux checkout's own
repository or the host path `/mnt/osint-ai`. Networking stays enabled.

The agent home is persistent, so the program-owned files inside it are mounted
rather than copied. `scripts/pi-entry.sh` used to copy `AGENTS.md`,
`keybindings.json` and `web-search.json` into it once, on first start only; on any
PC that had run the assistant before, the old copy stayed and kept naming paths
that no longer existed. `scripts/sandbox.py` now binds the environment's copies
read-only over those paths, and `pi-entry.sh` re-points `~/.pi/agent/npm` and
rewrites the `packages` and `skills` keys in `~/.pi/agent/settings.json` on every
launch. Bubblewrap creates a 0-byte placeholder in the home when a path is
missing; the home is the user's directory and nothing in it is deleted. The
assistant's instructions left that list: `pixi-recipes/pi-home` no longer ships an
`AGENTS.md`, so there is one guide, `workspace/AGENTS.md`, in the checkout the
agent works in and the user can read and edit. Pi reads
`~/.pi/agent/AGENTS.md` whenever context discovery is on, so `pi-entry.sh` renames
a leftover copy to `AGENTS.md.stale` rather than letting an outdated guide steer
the assistant; `--no-context-files` already stops Pi from reading it, and the
rename keeps the home honest about what is in it.

The installed launchers and the boot helper are root-owned. Their tracked
originals (`scripts/`, `windows/`) sit inside the read-only project mount in the
sandbox. [security.md](security.md) has the enforcement details and the limits
that still need Windows validation.

## Tasks

| Task | Effect |
| --- | --- |
| `pixi r osint-pi` | Assistant in `workspace/` of the current (Linux) checkout |
| `pixi r osint-pi-wsl` | Assistant in `workspace/` of the Windows checkout |
| `pixi r install` | Load the AppArmor profile Ubuntu needs for the pinned bubblewrap, then the installation check and usage summary |
| `pixi r start-server` / `stop-server` / `restart-server` | Local inference outside the sandbox on `127.0.0.1:8080`, GPU with automatic CPU fallback. `start-server` and `restart-server` run in the `llamacpp-binary-vulkan` environment, which Pixi installs when it is missing; `stop-server` runs in the default environment and installs nothing |
| `pixi r update-project` | Trusted maintenance: fast-forwards `main`, fast-forwards `staging` and merges `main` into `staging` (`scripts/git-branches.sh`), then `pixi install --locked -e default` and the inference environment when it is installed |
| `pixi r test` | Python test suite |

The launcher tasks are thin wrappers: they `exec` the root-owned launcher in
`/usr/local/bin` when it is installed, and otherwise the copy next to this
manifest. The outer Pixi process therefore only reads the manifest of the
checkout it runs from, never anything a sandboxed agent could have modified.
`update-project`, the Windows installer and the **Update OSINT AI** icon are
deliberate, human-run operations. Never wire them into startup or into the sandbox.
Inside WSL these commands are also installed as `osint-pi`, `osint-pi-wsl`,
`osint-terminal`, `start-server`, `stop-server`, `restart-server` and
`update-project`. `osint-terminal` is what the desktop shortcut runs; the Start and
Stop llama.cpp icons run the Windows environment's `_server` task directly, because
the server they control is not inside the distribution. The Update OSINT AI icon
runs `update-project` for the Linux checkout, the runtime refresh and the Windows
checkout's dance, then reinstalls the native llama.cpp environment from the
wrapper outside both checkouts.

## Skills and dependency changes

Pi discovers skills from `--skill /osint-ai/workspace/.agents/skills` (passed by
`scripts/pi-entry.sh`, whose value the launcher exports as `OSINT_SKILLS_DIR`) and
from `pixi-recipes/pi-home/settings.json`. Skills are
`<skill-name>/SKILL.md` with `scripts/`, `references/` and `assets/` beneath the
same folder. `/reload` picks up changes. Bundled skills: `spreadsheet-reader`
(`.xls`/`.xlsx`/`.xlsb`/CSV through pandas), `compliance-report` (structure,
confidence labels and evidence rules for the final deliverable) and
`markdown-pdf` (Markdown to PDF with pandoc + WeasyPrint, PDF text back into
Markdown). Report authorship and PDF conversion are separate skills on purpose,
and a test keeps them from merging back.

The environment on the sandbox `PATH` is `.pixi/envs/default/bin` of the Linux
checkout: `/opt/osint-ai/project/.pixi/envs/default/bin` in WSL, and
`/osint-ai/.pixi/envs/default/bin` in plain Linux, where the writable checkout
holds it. Both are mounted read-only. A functional
agent can use tools but cannot install them, which is the point: dependency
changes are maintainer work in a project root checkout. A skill's shell scripts
may only run programs that a base Linux system has, or programs that `pixi.toml`
declares. `tests/test_skeleton.py` enforces that, so a tool that would be missing
at runtime fails the test suite instead of the skill.

```bash
pixi add <conda-package>          # or: pixi add --pypi <package>
pixi lock
pixi install -e default
pixi r test
```

Listing what is installed depends on which side of the sandbox you ask from. In
the project root checkout, `pixi list` prints the whole environment. Inside the
sandbox there is no `pixi` and no `conda`, so the assistant reads the
environment's own records: `ls "$CONDA_PREFIX"/conda-meta/*.json` for every
package with its version and build, `ls "$CONDA_PREFIX/bin"` for the commands it
can run. `pip list` works there too, but it covers only the Python libraries and
omits tools such as pandoc and poppler.

Commit `pixi.toml` and `pixi.lock` together, then have each installation update
itself: the **Update OSINT AI** icon on Windows, `pixi r update-project` on Linux.
Users review and publish with a Windows Git GUI. The chatbot
runs Git in its own checkout: it reads status, and it may `git add` and
`git commit` a finished unit of work, but its guidance keeps it on `staging` - it
may switch `main` -> `staging` and merge `main` into `staging` - and forbids
pushing, other branch switches and discarding work; the user reviews every
change. It has no
access to the Linux checkout's repository. The launcher gives those commits an
author (`OSINT AI assistant <assistant@osint-ai.invalid>`, set as
`GIT_AUTHOR_*` and `GIT_COMMITTER_*`), because the agent home has no
`~/.gitconfig` and Git refuses to commit without an identity. An installed
checkout usually has no identity either, so when the update has to create a merge
commit it sets `OSINT AI update <update@osint-ai.invalid>` for that one command,
and only when the checkout has none of its own.

## Providers and local inference

Pi handles hosted-provider authentication through `/login` and model selection
through `/model`. Browser auto-launch is unavailable inside the sandbox. For
OAuth, users open the displayed URL in a Windows browser and paste the requested
redirect URL or code back into Pi. API-key login is also supported. Credentials
and sessions persist in private Linux application state, never in the checkout.

`pi-web-access` may need separate search-provider credentials. A chat-provider
login does not authorize every web-search service. Provider accounts and billing
are separate from this software.

Local inference is the `llamacpp-binary-vulkan` environment, and it runs in two
places depending on the deployment, with the same controller and the same presets.

On plain Linux (and in WSL, if somebody installs the environment there)
`pixi r start-server` launches it outside bubblewrap as the ordinary Linux user,
listening on `127.0.0.1:8080` in router mode with `models.ini` from the project
root. Nothing in the Windows deployment needs that server - the icons and the
assistant talk to the Windows one - but the same manifest and the same commands
serve a plain Linux install, so they keep working there. The assistant cannot start
any of it: `scripts/server.py` refuses when
`OSINT_SANDBOX=1`, and neither the state directory nor the program checkout is
writable inside the sandbox. Device detection asks the binary itself
(`--list-devices`), so a Vulkan device is found however it is reached, and
otherwise the same build starts on the CPU with GPU offloading disabled; the
backend is recorded in `<state>/server-state/server.json`.

On the Windows deployment llama.cpp runs natively on Windows, outside WSL, because
that is where the graphics driver is: the Windows installer installs Pixi and the
same environment inside the Windows checkout, and the **Start llama.cpp** and
**Stop llama.cpp** desktop icons run the same `_server` task. The server binds
`0.0.0.0` there - loopback inside WSL is a different machine - and the firewall
rule the installer added admits only the WSL adapter's local subnet. Both the
assistant's model list and Pi's own provider get the address from
`scripts/sandbox.py`, which resolves the guest's default gateway (the Windows host)
at every launch: `LLAMA_BASE_URL` for Pi's built-in llama.cpp provider and
`OSINT_INFERENCE_URL`, which `scripts/pi-entry.sh` rewrites into
`~/.pi/agent/models.json`. A WSL restart can change that address, which is why it
is never stored in a file the user could edit and why the model list is generated
rather than shipped.

`pixi r update-project` updates the Linux inference environment together with the
assistant's, and the **Update OSINT AI** icon does that and then reinstalls the
Windows environment from the updated manifest, so `models.ini` and the inference
recipes never drift apart from the binary.

Pi's built-in llama.cpp provider lists the models and its `/llama` command loads,
unloads and downloads them; `pi-llama-cpp` used to do that and is gone, so there is
one provider rather than two. The two presets in `models.ini` are named by hand in
`pixi-recipes/pi-home/models.json`, which a test keeps in step with the presets
(section names and context size), because that list is what `/model` shows and it
must not name a model the server does not have. The sampling settings are not
repeated there: llama.cpp starts every request from the model's own defaults - the
preset's `temperature`, `top-k`, `repeat-penalty` and the rest - and overrides only
the fields a request names, and Pi names none for a model that declares none, so the
preset is the one place those are written. What `models.json` keeps is the display
name and context window.

The hosted models are a different problem, because the good ones change: that list
is `model-shortlist.json` in the project root, and `scripts/pi-entry.sh` merges its
`enabledModels` patterns into `~/.pi/agent/settings.json` on every launch. It is a
project file rather than a shipped setting because it is the part that goes stale -
`README.md` says when it was last checked - and because the merge is additive: a
model the user saved with `/model` survives it, an entry already there is not added
twice, and nothing in the launcher removes a model. The entry script derives the
checkout from the environment prefix (`<checkout>/.pixi/envs/<name>`, three levels
up) and reads the file without asking whether it is there: it is part of the
checkout, like `pixi.toml`, and in WSL that checkout is the read-only program mount,
so the assistant cannot widen its own model list. On plain Linux the checkout is the
maintainer's own and writable by design. A test keeps its `llama.cpp/...` entries in
step with `pixi-recipes/pi-home/models.json`, so the shortlist never offers a local
model the server has no preset for, and never the unit-test preset.

Starting the server downloads no weights: llama.cpp loads a model, and downloads it
if necessary, when a request names it - which is also why the CI smoke test loads
the preset explicitly before asking. Review presets against supported hardware:
appearing in the list does not mean a model fits the user's GPU, RAM or patience.
`stop-server` stops inference but retains cached models.

`pi-subagents` lets the assistant hand a narrow job to a child session, and
`pi-intercom` gives the sessions one channel to talk over. Both run inside the
same bubblewrap namespace: a child has the same model, the same read-only project
root and the same writable workspace as its parent. The intercom broker state is
a per-launch tmpfs, so a second terminal window gets its own channel and no
message survives a restart. The sub-agent supervisor channel is a separate
mechanism under the sandbox's own temporary directory and needs no broker.

On WSL, llama.cpp uses the Windows NVIDIA driver. Do not install a Linux NVIDIA
kernel driver. The agent itself needs no GPU device access.

## Validation

Run automated tests inside Linux or WSL:

```bash
python3 -m unittest discover -s tests -v     # or: pixi r test
```

Linux integration tests exercise real bubblewrap where user namespaces are
available; otherwise they report an explicit skip. See
[testing.md](testing.md) for the Pi smoke test, the PowerShell parse test and the
manual Windows acceptance matrix. Passing Linux tests does not validate a Windows
installation, reboot, DrvFS, MobaXterm, OAuth or actual inference.

GitHub Actions runs the same checks on every push to `main` and every pull
request: `.github/workflows/ci.yml` installs the locked `default` environment
with `prefix-dev/setup-pixi` and runs `pixi run test`, parses
`windows/Install.ps1` with `pwsh` on a Windows and a Linux runner, and runs the
bubblewrap smoke test only where unprivileged user namespaces work. Its Windows
job installs the win-64 inference environment and starts and stops a real server
through the same controller the desktop icons run; it never installs the
assistant's environment, which does not resolve for win-64 and never should.
`.github/workflows/llamacpp.yml` is separate: it runs the documented
`pixi r install` (the AppArmor profile included), starts the Linux server - on a
GPU-less runner that exercises the CPU fallback, because the Vulkan backend is a
shared object a machine without a driver simply fails to load - loads the
`LFM2.5-230M` unit-test preset, and asks the sandboxed assistant for an answer.
It reports which half ran rather than pretending a runner that blocks user
namespaces exercised containment. CI is a floor, not the acceptance matrix.
