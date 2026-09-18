# Developer guide

The [README](../README.md) is the end-user quick start. Keep implementation,
packaging, and troubleshooting details here rather than in that guide.

Related documentation:

- [Security design and limits](security.md)
- [Tests and Windows release checklist](testing.md)
- [Copied components and upstream provenance](upstream.md)

## Windows installation and packaging

Supported target: Windows 11 x64 with hardware virtualization and internet
access. WSL installation may require administrator approval and a reboot.
Local inference requires an NVIDIA GPU and Windows driver compatible with the
bundled CUDA 13.3 runtime. Hosted providers do not require a GPU. Installation
uses several GB for packages; model weights download separately on first use.

Distribute `Install.cmd` and `Install.ps1` together. The bootstrap defaults to
`https://github.com/crusaderky/osint-ai.git`, branch `main`. Publish the repository
and installer before directing users to download them; pin a reviewed release
for distribution rather than relying on a mutable branch.

Developer overrides, from PowerShell:

```powershell
.\Install.ps1 -RepositoryUrl https://github.com/YOUR-ORG/osint-ai.git -Ref YOUR-TAG -ProjectPath C:\Users\Alice\osint-ai
```

The bootstrap expects a public repository. For a private repository, first clone
it with a Windows Git GUI, then supply the matching URL and checkout path.
GitHub credentials are not copied into the agent sandbox.

The installer:

- Creates a dedicated `osint-ai` WSL distribution, leaving existing distributions
  unchanged, and a Windows checkout at `%USERPROFILE%\osint-ai` by default.
- Verifies pinned Ubuntu and Pixi downloads and never resets an existing checkout.
- Refuses to reuse an unrelated distribution named `osint-ai`.
- Creates **OSINT AI Terminal** and **OSINT AI Files** desktop shortcuts.
- Preserves user state on a completed-install rerun; it does not update the trusted
  runtime. There is no automatic updater in this skeleton.

`pixi r install` is a user-level installation check **after** Windows provisioning.
It does not elevate or execute root commands from the checkout. Do not run Pixi
on an unmounted `/mnt/c/...` checkout before setup: it could install Linux
packages onto NTFS instead of the intended Linux-backed `.pixi`.

## Filesystem and process layout

| Location | Purpose |
| --- | --- |
| Windows checkout | All tracked files, including `agents/`, `AGENTS.md`, manifests, recipes, and `.git` |
| `/workspace` | WSL view of that same Windows checkout |
| `/var/lib/osint-ai/pixi` | Linux ext4 storage mounted over `/workspace/.pixi` before Pixi runs |
| `/var/lib/osint-ai/agent-home` | Persistent sandbox home, including Pi credentials, sessions, settings, and caches |
| `/opt/osint-ai/server` | Protected installed inference runtime and `models.ini` snapshot |
| `/var/lib/osint-ai/models` | Downloaded model cache |
| `/var/lib/osint-ai/server-state/llama-server.log` | Inference server log |

There is one Git checkout: no duplicate skills, file synchronization, detached
Pixi environments, or Linux symlink stored in the Windows checkout.

`osint-pi` enters bubblewrap **before** Pixi reads the editable manifest. Activation
hooks, package builds, extensions, and shell commands execute inside containment.
The agent can write project content and its own Linux state. OS tools are
read-only; other Windows drives, host homes, WSL interop sockets, GPU devices,
and actual `.git` contents are not exposed. Networking remains enabled.

Installed launchers and the boot helper are root-owned. Their tracked originals
(`scripts/`, `pixi-recipes/`, `Install.*`) are read-only during skill authoring.
See the [security guide](security.md) for enforcement details, limitations, and
Windows filesystem cases that still require validation.

## Skills and dependency changes

Pi explicitly discovers `/workspace/agents`. Root `AGENTS.md` tells the chatbot
to write skills there, not into WSL home or Pi's conventional skill directories.
User-authored skills have the layout `agents/<skill-name>/SKILL.md`, with helper
scripts and references beneath the same directory. `/reload` discovers changes.

`AGENTS.md`, `pixi.toml`, and `pixi.lock` remain agent-editable. Inside the sandbox:

```bash
pixi add <conda-package>
pixi add --pypi <package>
pixi run python ...
```

The default tools environment is separate from the running `agents` environment.
Restarting Pi applies updated agent dependencies. Humans review and publish
changes using a Windows Git GUI; the chatbot does not control Git metadata.

## Providers and local inference

Pi handles hosted-provider authentication through `/login` and model selection
through `/model`. Browser auto-launch is unavailable inside the sandbox. For
OAuth, users open the displayed URL in a Windows browser and paste the requested
redirect URL or code back into Pi. API-key login is also supported. Credentials
and sessions persist in private Linux application state, never the checkout.

`pi-web-access` may need separate search-provider credentials. A chat-provider
login does not authorize every web-search service. Provider accounts and billing
are separate from this software.

`start-server` launches CUDA inference outside bubblewrap as an ordinary Linux
user, listening on WSL loopback at `127.0.0.1:8080`. It uses a protected runtime
and preset snapshot, not agent-editable activation hooks or binaries. Changes
to checkout inference recipes or `models.ini` require a maintainer-reviewed
runtime reinstall; daily startup does not apply them automatically.

`pi-llama-cpp` supplies the plural `/models` command for browsing, loading, and
switching local models. Starting the server downloads no weights; selecting a
model triggers loading and any required download. Pi displays progress. Review
presets against supported hardware: appearing in the list does not imply a model
fits the user's GPU or RAM. `stop-server` stops inference but retains cached models.

WSL uses the Windows NVIDIA driver. Do not install a Linux NVIDIA kernel driver.
The agent itself needs no GPU device access.

## Validation

Run automated tests inside Linux or WSL:

```bash
python3 -m unittest discover -s tests -v
```

Linux integration tests exercise real bubblewrap where user namespaces are
available; otherwise they report an explicit skip. See [testing.md](testing.md)
for the full Pi smoke test, PowerShell checks, and manual Windows acceptance
matrix. Passing Linux tests does not validate Windows installation, reboot,
DrvFS, OAuth, or actual CUDA inference.
