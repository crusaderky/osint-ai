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
| Project root (this checkout) | Maintainer. Start Pi here for code work. | Git, `pixi.toml`, `pixi.lock`, `wsl/`, `pixi-recipes/`, `tests/`, `docs/`, `README.md`, `AGENTS.md` |
| `workspace/` | Compliance officer, through the chatbot | `AGENTS.md` (working rules) and `.agents/skills/` (user-authored skills), plus research output |

On Windows the repository is checked out at `C:\Users\<name>\osint-ai`; WSL
mounts it at `/mnt/osint-ai`. Inside the private WSL distribution a second
checkout exists at `/home/osint/osint-ai`. That Linux checkout owns Git, Pixi
environments and all code that executes. The Windows checkout supplies only its
`workspace/` directory to the assistant.

```text
Linux checkout /home/osint/osint-ai  --read-only-->  /opt/osint-ai/project  (sandbox)
Windows checkout /mnt/osint-ai/workspace --read-write--> /workspace         (sandbox, cwd)
```

Because they are separate checkouts, editing `pixi.toml` in the Windows checkout
changes nothing that runs. The user pushes from the Windows Git GUI; the Linux
side is updated with `update-project` (see below). Nothing is rsynced, symlinked
or duplicated by the runtime.

## Windows installation and packaging

Supported target: Windows 11 x64 with hardware virtualization and internet
access. WSL installation may require administrator approval and a reboot. Local
inference uses a CUDA build of llama.cpp and falls back to CPU inference when no
CUDA device answers, so a GPU is an optimisation, not a requirement. Hosted
providers never need a GPU. Installation uses several GB for packages; model
weights download separately on first use.

Distribute the `wsl/` folder (`Install.cmd` and `Install.ps1` together). The
bootstrap defaults to `https://github.com/crusaderky/osint-ai.git`, branch
`main`. Publish the repository and installer before directing users to download
them; pin a reviewed release for distribution rather than relying on a mutable
branch.

Developer overrides, from PowerShell inside the `wsl` folder:

```powershell
.\Install.ps1 -RepositoryUrl https://github.com/YOUR-ORG/osint-ai.git -Ref YOUR-TAG `
    -ProjectPath C:\Users\Alice\osint-ai -LinuxProjectPath /home/osint/osint-ai
```

The bootstrap expects a public repository. For a private repository, first clone
it with a Windows Git GUI, then supply the matching URL and checkout path.
GitHub credentials are not copied into the agent sandbox.

The installer:

- Creates a dedicated `osint-ai` WSL distribution, leaving existing
  distributions unchanged, plus the Windows checkout.
- Verifies pinned Ubuntu and Pixi downloads and never resets an existing
  checkout; it never pulls, discards or deletes user content.
- Clones the Linux checkout and installs the `agents` environment inside it.
- Provisions root-owned launchers, the boot mount helper, the AppArmor bwrap
  profile and an inference runtime snapshot.
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

Uninstalling is manual and documented for users in the README. What it removes:
`wsl --unregister osint-ai` deletes the private distribution and its disk — Pi
credentials, sessions and settings, cached model weights, the Linux checkout and
the root-owned launchers under `/usr/local`. Deleting `%LOCALAPPDATA\osint-ai`
removes the download cache and the portable MobaXterm copy. The Windows checkout,
including `workspace/`, and everything pushed to GitHub survive both steps, and
`wsl.exe` plus the Windows feature stay installed for other software.

`pixi r install` is an installation check **after** Windows provisioning. It
does not elevate or execute root commands from the checkout.

## Filesystem and process layout

| Location | Purpose |
| --- | --- |
| Windows checkout | Everything the user commits: `workspace/AGENTS.md`, `workspace/.agents/skills/`, reports |
| `/mnt/osint-ai` | That checkout, bind-mounted from DrvFS by the root-owned boot hook |
| `/home/osint/osint-ai` | Linux checkout: Git, `pixi.toml`, `.pixi`, code that runs |
| `/opt/osint-ai/project` | The Linux checkout inside the sandbox, read-only |
| `/workspace` | `/mnt/osint-ai/workspace` inside the sandbox, read-write; Pi's working directory |
| `/var/lib/osint-ai/agent-home` | Persistent sandbox home: Pi credentials, sessions, settings, caches |
| `/var/lib/osint-ai/git-status` | Launcher-written Git summary exposed read-only at `/run/git-status` |
| `/opt/osint-ai/server` | Root-owned inference runtime and `models.ini` snapshot |
| `/var/lib/osint-ai/models` | Downloaded model cache |
| `/var/lib/osint-ai/server-state/llama-server.log` | Inference server log |

The sandbox never sees a `.git` directory, the Windows drive root, other drives,
host homes, WSL interop sockets or GPU devices. Networking stays enabled.
`osint-pi` (plain Linux) and `osint-pi-wsl` (Windows workspace) are the same
launcher with a different workspace source; both enter bubblewrap before Pi
starts, and both mount the environment that supplies Pi read-only.

Installed launchers and the boot helper are root-owned. Their tracked originals
(`wsl/`, `pixi-recipes/`, `wsl/Install.*`) are inside the read-only project
mount inside the sandbox. See [security.md](security.md) for enforcement details
and the limits that still need Windows validation.

## Tasks

| Task | Effect |
| --- | --- |
| `pixi r osint-pi` | Assistant in `workspace/` of the current (Linux) checkout |
| `pixi r osint-pi-wsl` | Assistant in `workspace/` of the Windows checkout |
| `pixi r install` | Installation check and usage summary |
| `pixi r start-server` / `stop-server` / `restart-server` | Local inference outside the sandbox, GPU with automatic CPU fallback |
| `pixi r update-project` | Trusted maintenance: `git pull --ff-only` then `pixi install --locked -e agents` |
| `pixi r test` | Python test suite |

The launcher tasks are thin wrappers: they `exec` the root-owned launcher in
`/usr/local/bin` when it is installed, and otherwise the checkout copy. The
outer Pixi process therefore only reads the manifest of the checkout it runs
from — never anything the sandboxed agent could have modified. `update-project`
and the Windows installer are deliberate, human-run operations: they execute
repository content with normal user rights. Never wire them into startup or into
the sandbox.

Inside WSL these commands are also installed as `osint-pi`, `osint-pi-wsl`,
`osint-terminal`, `start-server`, `stop-server`, `restart-server` and
`update-project`. `osint-terminal` is what the desktop shortcut runs.

## Skills and dependency changes

Pi discovers skills from `--skill /workspace/.agents/skills` (passed by
`wsl/scripts/pi-entry.sh`) and from `pixi-recipes/pi-home/settings.json`. Skills
are `<skill-name>/SKILL.md` with `scripts/`, `references/` and `assets/` beneath
the same folder. `/reload` picks up changes. Bundled skills:
`spreadsheet-reader` (`.xls`/`.xlsx`/`.xlsb`/CSV through pandas) and
`markdown-pdf` (Markdown to PDF with pandoc + WeasyPrint, PDF text back into
Markdown).

The environment on the sandbox `PATH` is
`/opt/osint-ai/project/.pixi/envs/agents/bin`, mounted read-only. A functional
agent can use tools but cannot install them, which is the point: dependency
changes are maintainer work in a project root checkout.

```bash
pixi add <conda-package>          # or: pixi add --pypi <package>
pixi lock
pixi install -e agents
pixi r test
```

Commit `pixi.toml` and `pixi.lock` together, then have each WSL installation run
`update-project`. Users review and publish with a Windows Git GUI; the chatbot
does not control Git metadata at all, only reads the launcher-written summary at
`/run/git-status` so it can remind the user.

## Providers and local inference

Pi handles hosted-provider authentication through `/login` and model selection
through `/model`. Browser auto-launch is unavailable inside the sandbox. For
OAuth, users open the displayed URL in a Windows browser and paste the requested
redirect URL or code back into Pi. API-key login is also supported. Credentials
and sessions persist in private Linux application state, never the checkout.

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
supported hardware: appearing in the list does not imply a model fits the user's
GPU, RAM or patience. `stop-server` stops inference but retains cached models.

WSL uses the Windows NVIDIA driver. Do not install a Linux NVIDIA kernel driver.
The agent itself needs no GPU device access.

## Validation

Run automated tests inside Linux or WSL:

```bash
python3 -m unittest discover -s tests -v     # or: pixi r test
```

Linux integration tests exercise real bubblewrap where user namespaces are
available; otherwise they report an explicit skip. See
[testing.md](testing.md) for the Pi smoke test, PowerShell checks and the manual
Windows acceptance matrix. Passing Linux tests does not validate Windows
installation, reboot, DrvFS, MobaXterm, OAuth or actual inference.
