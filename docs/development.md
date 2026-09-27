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
Pixi environments and everything that executes. The Windows checkout contributes
only its `workspace/` directory to the assistant.

```text
Linux checkout /home/osint/osint-ai  --read-only-->  /opt/osint-ai/project  (sandbox)
Windows checkout /mnt/osint-ai/workspace --read-write--> /workspace         (sandbox, cwd)
```

That separation is the reason `pixi.toml` edited in the Windows checkout changes
nothing that runs. The user pushes from the Windows Git GUI and the Linux side is
updated with `update-project`. The runtime never rsyncs, symlinks or duplicates
anything between them.

## One launcher, two arguments

`scripts/bwrap-pi.sh` starts the assistant on both platforms. The first argument
picks the deployment; the rest goes to Pi.

| Argument | Assistant works in | Used by |
| --- | --- | --- |
| `--native` | `<project root>/workspace` | `pixi r osint-pi`, and `/usr/local/bin/osint-pi` inside WSL |
| `--wsl` | `/mnt/osint-ai/workspace` | `pixi r osint-pi-wsl`, `/usr/local/bin/osint-pi-wsl`, the desktop shortcut |

`scripts/sandbox.py` builds the mount namespace and `scripts/pi-entry.sh` runs
after containment, so Pi is never started outside bubblewrap. When the root-owned
copies in `/usr/local/lib/osint-ai` exist they are used instead of the checkout
copies, so an installed PC runs the code it installed rather than whatever the
checkout happens to contain. In `wsl` mode the Linux checkout's `.git` is masked
and the Windows checkout is mounted read-write; in `native` mode the project root
is writable and `.pixi` is re-mounted read-only on top of it. See
[security.md](security.md).

## Windows installation and packaging

Supported target: Windows 11 x64 with hardware virtualization and internet
access. WSL installation may require administrator approval and a reboot. Local
inference uses a CUDA build of llama.cpp and starts on the CPU when no CUDA
device answers, so a GPU is an optimisation rather than a requirement. Hosted
providers never need a GPU. Installation uses several GB for packages; model
weights download separately on first use.

Distribute the `windows/` folder (`Install.cmd` and `Install.ps1` together). The
bootstrap defaults to `https://github.com/crusaderky/osint-ai.git`, branch
`main`. Publish the repository and installer before directing users at them, and
pin a reviewed release tag rather than relying on a mutable branch.

Developer overrides, from PowerShell inside the `windows` folder:

```powershell
.\Install.ps1 -RepositoryUrl https://github.com/YOUR-ORG/osint-ai.git -Ref YOUR-TAG `
    -ProjectPath C:\Users\Alice\osint-ai -LinuxProjectPath /home/osint/osint-ai
```

The bootstrap expects a public repository. For a private one, clone it first with
a Windows Git GUI, then supply the matching URL and checkout path. GitHub
credentials are not copied into the agent sandbox.

The installer:

- Creates a dedicated `osint-ai` WSL distribution, leaving existing
  distributions unchanged, plus the Windows checkout.
- Verifies pinned Ubuntu and Pixi downloads and never resets an existing
  checkout; it does not pull, discard or delete user content.
- Clones the Linux checkout and installs the `default` environment inside it.
- Runs `windows/provision-wsl.sh`, which installs the root-owned launchers, the
  boot mount helper, the AppArmor bwrap profile and an inference runtime
  snapshot.
- Reuses an existing MobaXterm installation or downloads the pinned, checksum
  verified portable build (`-SkipMobaXterm` disables the download). MobaXterm is
  third-party freeware under its own licence: check it before redistributing the
  installation package.
- Creates desktop shortcuts: **OSINT AI Terminal** (MobaXterm tab, runs
  `pixi r restart-server && pixi r osint-pi-wsl` in the Linux checkout),
  **OSINT AI Terminal (basic)** (plain `wsl.exe` console) and
  **OSINT AI Files** (Windows checkout).
- Preserves user state on a completed-install rerun; it does not update the
  trusted runtime. There is no automatic updater in this skeleton.

Uninstalling is manual and documented for users in the README. In short:
`wsl --unregister osint-ai` deletes the private distribution and its disk, which
holds the Pi credentials, sessions and settings, cached model weights, the Linux
checkout and the root-owned launchers under `/usr/local`. Deleting
`%LOCALAPPDATA\osint-ai` removes the download cache and the portable MobaXterm
copy. The Windows checkout, including `workspace/`, and everything pushed to
GitHub survive both steps, and `wsl.exe` plus the Windows feature stay installed
for other software.

`pixi r install` (`scripts/install-check.sh`) reports what is set up and what is
missing. It never elevates and never runs root commands from the checkout.

## Installing on Linux

Deliberately a list of commands and not a script; the Windows installer's other
job is registering a WSL distro as root, and a Linux user has nothing like that
to do.

```bash
# Debian, Ubuntu, Arch: the bubblewrap package; then Pixi from https://pixi.sh
git clone https://github.com/crusaderky/osint-ai.git
cd osint-ai && pixi install --locked -e default
pixi r osint-pi
```

The assistant keeps its sign-in, sessions and settings in
`~/.local/state/osint-ai`; override with `OSINT_STATE_DIR`.

Ubuntu 24.04 ships an AppArmor policy that stops `bwrap` creating a user
namespace. Load the same profile `windows/provision-wsl.sh` installs:

```bash
sudo tee /etc/apparmor.d/bwrap >/dev/null <<'EOF'
abi <abi/4.0>,
include <tunables/global>
profile bwrap /usr/bin/bwrap flags=(unconfined) {
  userns,
  include if exists <local/bwrap>
}
EOF
sudo apparmor_parser -r /etc/apparmor.d/bwrap
```

What a Linux install does not get, because it belongs to the Windows deployment:
the root-owned launchers in `/usr/local`, the boot mount helper, desktop
shortcuts, and the inference runtime snapshot. Hosted models work as they do on
Windows. For local inference, build the snapshot the way provisioning does, and
keep it out of any checkout:

```bash
sudo install -d -m 755 /opt/osint-ai/server
cp -a pixi-recipes pixi.toml pixi.lock models.ini /opt/osint-ai/server/
pixi install --locked -e llamacpp-binary-cuda --manifest-path /opt/osint-ai/server/pixi.toml
sudo chown -R root:root /opt/osint-ai/server     # readable, never writable
sudo install -d -m 755 -o "$USER" /var/lib/osint-ai/server-state /var/lib/osint-ai/models
pixi r restart-server       # reads /opt/osint-ai/server/models.ini, binds 127.0.0.1:8080
```

The paths are hardcoded in `scripts/server.py` for a reason: the runtime a
session talks to must not be something the session can edit.

## Filesystem and process layout

| Location | Purpose |
| --- | --- |
| Windows checkout | Everything the user commits: `workspace/AGENTS.md`, `workspace/.agents/skills/`, reports |
| `/mnt/osint-ai` | That checkout, bind-mounted from DrvFS by the root-owned boot hook |
| `/home/osint/osint-ai` | Linux checkout: `pixi.toml`, `.pixi`, code that runs |
| `/opt/osint-ai/project` | The Linux checkout inside the sandbox, read-only, with its `.git` masked |
| `/mnt/osint-ai` (inside the sandbox) | The Windows checkout, read-write with `.git`; `/workspace` is its `workspace/` subdirectory |
| `/workspace` | The functional workspace, read-write; Pi's working directory |
| `/var/lib/osint-ai/agent-home` | Persistent sandbox home: Pi credentials, sessions, settings, caches (on Linux: `~/.local/state/osint-ai`) |
| `/opt/osint-ai/server` | Root-owned inference runtime and `models.ini` snapshot |
| `/var/lib/osint-ai/models` | Downloaded model cache |
| `/var/lib/osint-ai/server-state/llama-server.log` | Inference server log |

Inside the sandbox the agent works in a real Git checkout: it can read the whole
history and, with `.git` writable, commit or discard work. Guidance tells it not
to, and the user reviews the diff. It never sees the Windows drive root, other
drives, host homes, WSL interop sockets or GPU devices, and in WSL it never sees
the Linux checkout's own repository. Networking stays enabled.

The installed launchers and the boot helper are root-owned. Their tracked
originals (`scripts/`, `windows/`) sit inside the read-only project mount in the
sandbox. [security.md](security.md) has the enforcement details and the limits
that still need Windows validation.

## Tasks

| Task | Effect |
| --- | --- |
| `pixi r osint-pi` | Assistant in `workspace/` of the current (Linux) checkout |
| `pixi r osint-pi-wsl` | Assistant in `workspace/` of the Windows checkout |
| `pixi r install` | Installation check and usage summary; installs nothing |
| `pixi r start-server` / `stop-server` / `restart-server` | Local inference outside the sandbox, GPU with automatic CPU fallback |
| `pixi r update-project` | Trusted maintenance: `git pull --ff-only` then `pixi install --locked -e default` |
| `pixi r test` | Python test suite |

The launcher tasks are thin wrappers: they `exec` the root-owned launcher in
`/usr/local/bin` when it is installed, and otherwise the copy next to this
manifest. The outer Pixi process therefore only reads the manifest of the
checkout it runs from, never anything a sandboxed agent could have modified.
`update-project` and the Windows installer are deliberate, human-run operations.
Never wire them into startup or into the sandbox.

Inside WSL these commands are also installed as `osint-pi`, `osint-pi-wsl`,
`osint-terminal`, `start-server`, `stop-server`, `restart-server` and
`update-project`. `osint-terminal` is what the desktop shortcut runs.

## Skills and dependency changes

Pi discovers skills from `--skill /workspace/.agents/skills` (passed by
`scripts/pi-entry.sh`) and from `pixi-recipes/pi-home/settings.json`. Skills are
`<skill-name>/SKILL.md` with `scripts/`, `references/` and `assets/` beneath the
same folder. `/reload` picks up changes. Bundled skills: `spreadsheet-reader`
(`.xls`/`.xlsx`/`.xlsb`/CSV through pandas), `compliance-report` (structure,
confidence labels and evidence rules for the final deliverable) and
`markdown-pdf` (Markdown to PDF with pandoc + WeasyPrint, PDF text back into
Markdown). Report authorship and PDF conversion are separate skills on purpose,
and a test keeps them from merging back.

The environment on the sandbox `PATH` is
`/opt/osint-ai/project/.pixi/envs/default/bin`, mounted read-only. A functional
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

Commit `pixi.toml` and `pixi.lock` together, then have each WSL installation run
`update-project`. Users review and publish with a Windows Git GUI. The chatbot
does run Git, in the user's own checkout and only to read status; its guidance
forbids committing, pushing, branch switching and discarding work, and the user
reviews every diff. It has no access to the Linux checkout's repository.

## Providers and local inference

Pi handles hosted-provider authentication through `/login` and model selection
through `/model`. Browser auto-launch is unavailable inside the sandbox. For
OAuth, users open the displayed URL in a Windows browser and paste the requested
redirect URL or code back into Pi. API-key login is also supported. Credentials
and sessions persist in private Linux application state, never in the checkout.

`pi-web-access` may need separate search-provider credentials. A chat-provider
login does not authorize every web-search service. Provider accounts and billing
are separate from this software.

`start-server` launches inference outside bubblewrap as the ordinary Linux user,
listening on `127.0.0.1:8080`. It uses a protected runtime and preset snapshot,
not agent-editable activation hooks or binaries. Device detection selects the
GPU when a CUDA device answers `--list-devices`, and otherwise starts the same
build on the CPU with GPU offloading disabled, recording the backend in
`/var/lib/osint-ai/server-state/server.json`. Changes to checkout inference
recipes or `models.ini` require a maintainer-reviewed runtime reinstall; daily
startup does not apply them automatically.

`pi-llama-cpp` supplies the plural `/models` command for browsing, loading and
switching local models. Starting the server downloads no weights; selecting a
model triggers loading and any required download. Review presets against
supported hardware: appearing in the list does not mean a model fits the user's
GPU, RAM or patience. `stop-server` stops inference but retains cached models.

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
