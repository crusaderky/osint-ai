# Open Source Intelligence AI

A sandboxed chatbot for researching public information and authoring reusable
compliance skills. **First implementation skeleton: Windows/WSL/CUDA validation
is still required before distributing this to inexperienced users.**

## Install on Windows

Requirements: Windows 11 x64, hardware virtualization, internet access, and
administrator approval if WSL is not installed. Local inference additionally
requires an NVIDIA GPU and Windows driver compatible with CUDA 13.3. Cloud
providers do not require a GPU. Expect several GB for runtime packages; model
weights are downloaded separately, on first use.

1. Download the release containing `Install.cmd` and `Install.ps1` together.
2. Double-click **Install.cmd** as your ordinary Windows user.
3. Approve Windows feature installation if asked. If setup requests a reboot,
   restart Windows and double-click **Install.cmd** again.
4. Setup creates a dedicated **osint-ai** WSL distribution and a Windows Git
   checkout at `%USERPROFILE%\osint-ai`. Existing WSL distributions are untouched.
5. Open the **OSINT AI Terminal** desktop shortcut.

The bootstrap currently defaults to `https://github.com/crusaderky/osint-ai.git`
and branch `main`. A maintainer must publish the repository/release before this
flow can be used. The skeleton expects a public repository; for a private one,
clone it using your Windows Git GUI first and pass its matching URL/path to the
installer. GitHub credentials are never copied into the agent sandbox.

Developer overrides, from PowerShell:

```powershell
.\Install.ps1 -RepositoryUrl https://github.com/YOUR-ORG/osint-ai.git -Ref YOUR-TAG -ProjectPath C:\Users\Alice\osint-ai
```

The installer verifies pinned Ubuntu and Pixi downloads, never resets an existing
checkout, and refuses to reuse an unrelated distribution named `osint-ai`.
Rerunning a completed installation does not update the trusted runtime. This
skeleton deliberately has no automatic updater.

## Use a hosted model

In the OSINT AI WSL terminal, from any directory:

```bash
osint-pi
```

Inside Pi, use `/login` and choose OpenRouter, OpenCode, or another supported
provider. OAuth browser auto-launch is deliberately unavailable inside the
sandbox: open the displayed URL in your Windows browser; paste the redirect
URL/code back when requested. API-key login is also available inside Pi.
Credentials and sessions persist in private Linux application state, not Git.

Use `/model` to select a hosted model. Provider billing and accounts are separate
from this software. Web-search tools from `pi-web-access` may need their own
provider credentials; a chat-provider login does not unlock every search service.

## Use local NVIDIA inference

```bash
start-server
osint-pi
```

Inside Pi, use **`/models`** (provided by `pi-llama-cpp`) to browse, load, and
switch local models. Hosted models use Pi's singular `/model` command.

The server listens only on `127.0.0.1:8080` inside WSL. Starting it downloads no
model weights. Loading a model can download many GB and take substantial time;
Pi displays progress. Some copied `models.ini` presets require far more memory
than ordinary consumer GPUs. Start with a suitably small model. A preset being
listed does not imply that it fits your hardware.

```bash
stop-server
```

Server logs: `/var/lib/osint-ai/server-state/llama-server.log`. Model files remain
cached after stopping. No Linux NVIDIA kernel driver is installed or required:
WSL uses the Windows NVIDIA driver.

## Create, review and publish a skill

1. Ask Pi: "Create a skill for checking a company's public ownership records."
2. Pi writes `agents/<skill-name>/SKILL.md` and supporting files into your
   Windows checkout. `AGENTS.md` explicitly forbids putting user skills in WSL home.
3. Open **OSINT AI Files**, browse `agents`, and inspect/edit files with Notepad
   or your preferred text editor. Use `/reload` in Pi after edits.
4. Open this same folder in GitHub Desktop, GitKraken, or your preferred Git GUI.
   Review differences, enter a commit message, commit, then push.

Only one Git checkout exists. No VS Code, Linux Git commands, duplicate skills,
or file synchronization is required. Your Git GUI handles GitHub sign-in.

`AGENTS.md`, `pixi.toml`, and `pixi.lock` are writable by the agent. It can add
Python tools with `pixi add <package>` or `pixi add --pypi <package>`, then run
`pixi run python ...`. The default tools environment is separate from Pi's
`agents` environment; restarting Pi applies updated agent dependencies.

## Layout and isolation

- Windows owns all tracked files: `agents/`, `AGENTS.md`, manifests, recipes,
  installer source, and `.git`.
- WSL mounts only this Windows directory at `/workspace`. `.pixi` is overlaid
  with ext4 storage at `/var/lib/osint-ai/pixi`, **before Pixi runs**. No detached
  environments and no Linux symlink stored in the Windows checkout.
- `osint-pi` starts bubblewrap before reading the editable manifest. Activation
  hooks, builds, packages and shell commands stay inside its namespace.
- Sandbox sees writable project content, its own persistent home and caches,
  read-only OS tools, and networking. It cannot see other Windows drives, host
  home directories, WSL interop sockets, GPU devices, or actual `.git` contents.
- Installed launchers and boot helper are root-owned. Their tracked originals
  (`scripts/`, `pixi-recipes/`, `Install.*`) are read-only during skill authoring.
- CUDA inference runs outside bubblewrap as an ordinary Linux user. It uses a
  protected installed runtime and `models.ini` snapshot, not agent-editable
  activation hooks or binaries. No second Git repository is involved. Changes
  to inference recipes/presets require a maintainer-reviewed runtime reinstall.

**Security limits:** networking is allowed; readable data and Pi credentials can
be sent over the network. The chatbot can destroy files in its writable project.
Generated skills must be reviewed before use. This is not a hostile-malware VM
boundary, and the inference server remains outside bubblewrap. See
[security and validation](docs/security.md), including required Windows tests.

## Development

`pixi r install` is the simplified user-level installation check after Windows
provisioning; it never elevates or executes root commands from the checkout.
For first installation, use the Windows bootstrap rather than running Pixi on
an unmounted `/mnt/c/...` checkout.

Inside Linux or WSL, run the automated tests:

```bash
python3 -m unittest discover -s tests -v
```

Linux tests exercise actual bubblewrap when unprivileged namespaces are available;
otherwise integration tests report an explicit skip. Windows bootstrap, DrvFS,
reboot handling, OAuth and CUDA need the manual acceptance checks in
[docs/testing.md](docs/testing.md). No Windows/CUDA end-to-end claim is made by
passing Linux unit tests.

Recipes, model presets and launcher design were adapted from
[crusaderky/pixi-llm-recipes](https://github.com/crusaderky/pixi-llm-recipes).
See [copied components](docs/upstream.md).
