# OSINT AI — developer instructions

This checkout is the **project root**: Git, `pixi.toml`, `pixi.lock`, the
installer and the sandbox live here. You are here to maintain the software, not
to do compliance research. Start Pi in this directory for maintenance work.

The end user is a compliance officer with no programming background. The main
target is a Windows 11 PC running through WSL; plain Linux also works, for
people who can follow a handful of commands instead of double-clicking. Prefer
boring,
verifiable solutions and explain results in plain language.

## Layout

| Path | Purpose |
| --- | --- |
| `README.md` | Absolute-beginner guide: install, Git, Pi commands, AGENTS.md, skills. Keep it jargon-free. It stays at the root because it is where a Windows user is pointed. |
| `AGENTS.md` | This file: instructions for maintaining the project. The sandboxed assistant does not load it; see the rules below. |
| `workspace/` | The **functional** workspace. Its own `AGENTS.md` (the assistant's only instructions) and `.agents/skills/` drive the chatbot; that is a different job from this one. It is the assistant's working directory: `/osint-ai/workspace` inside the sandbox. |
| `scripts/` | The runtime, shared by both deployments: `bwrap-pi.sh` (the one sandbox launcher), `sandbox.py`, `pi-entry.sh`, the inference server controller, `update-project.sh`, `install-check.sh`, `install-apparmor.sh`. |
| `windows/` | Everything only the Windows deployment uses: `Install.cmd`, `Install.ps1`, `provision-wsl.sh`, the boot mount helper, and `launchers/` (the copies installed to `/usr/local/bin`). The bash scripts in here run inside the WSL distro the installer creates. |
| `pixi-recipes/` | Local build recipes: Pi, extensions, the bundled home configuration, the Vulkan llama.cpp binary. |
| `models.ini` | Inference presets snapshot used by the installed runtime. `LFM2.5-230M` is unit-test only: the CI smoke test asks that preset, nothing else uses it. The same preset names are listed in `pixi-recipes/pi-home/models.json`, which the launcher turns into the assistant's model list; a test keeps the two in step. |
| `model-shortlist.json` | The models the assistant is offered. `scripts/pi-entry.sh` merges its `enabledModels` list into the agent's `~/.pi/agent/settings.json` on every start, additively: missing entries are added, a model the user saved stays, nothing is duplicated. Read from the program checkout, so on Windows the agent cannot widen its own model list. Current as of 2026-10-10 and expected to change. |
| `docs/` | `development.md`, `security.md`, `testing.md`, `upstream.md`. |
| `tests/` | Linux/Python tests plus the PowerShell installer parse test. |
| `.github/workflows/ci.yml` | GitHub Actions CI: the unit suite in the locked `default` environment, the installer parse test, the bubblewrap smoke test where user namespaces work, and the native Windows inference job on `windows-latest` (the assistant's own environment is never installed on Windows). What it cannot prove is in `docs/testing.md`. |
| `.github/workflows/llamacpp.yml` | GitHub Actions CI: starts the real inference server and the real assistant through the sandbox launcher with the unit-test preset, on a runner with no GPU. Same honesty rules as `ci.yml`. |

## Two deployments, one sandbox launcher

`scripts/bwrap-pi.sh` starts the assistant on both platforms; only the first
argument differs:

* `--native` — plain Linux. One checkout holds Git, `pixi.toml`, `.pixi` and
  `workspace/`, and the agent works in that `workspace/`.
* `--wsl` — Windows. The agent works in the Windows checkout.

On Windows the repository exists twice, by design:

* `/home/osint/osint-ai` — Linux checkout. Owns `pixi.toml`, the Pixi
  environments and the code that executes. A maintainer updates it with
  `update-project`. Mounted read-only in the sandbox, with its `.git` masked.
* `C:\Users\<name>\osint-ai`, mounted at `/mnt/osint-ai` — Windows checkout. The
  user edits `workspace/` there and publishes with a Windows Git GUI. Mounted
  whole and read-write in the sandbox at `/osint-ai`, `.git` included, so the
  assistant can run `git status` and commit there itself; it is told never to
  push or discard work.

`bwrap-pi.sh --wsl` binds the Linux checkout **read-only** at
`/opt/osint-ai/project` and the Windows checkout **read-write** at `/osint-ai`,
then starts Pi in `/osint-ai/workspace`. `bwrap-pi.sh --native` mounts the single
checkout read-write at `/osint-ai` and re-binds `.pixi` read-only on top of it.
The sandboxed agent sees neither root-owned file and cannot change the program.
Tell the user that changes to the program's own files happen in the project root
checkout, followed by `update-project` on the WSL side.

The checkout is always mounted whole, never as a bare `workspace/` bind: Git
walks up from the working directory looking for `.git`, so a workspace mounted on
its own has no repository above it and `git status` fails.

That mount choice is the only deployment-specific thing the launcher makes. The
working directory `/osint-ai/workspace`, the skills path, the read-only
environment and the agent home at `~/.local/state/osint-ai/agent-home` of the
Linux user running it (`/home/osint/.local/state/osint-ai/agent-home` in WSL,
created by the launcher at `0700`) are the same everywhere. Do not reintroduce a
WSL-only state directory such as `/var/lib/osint-ai/agent-home`: that is how a
sign-in, a session or a setting ends up where the other deployment never looks.
`/var/lib/osint-ai` holds inference state where the WSL deployment pre-created it;
a plain Linux checkout keeps the same `server-state/` directory in the user's own
`~/.local/state/osint-ai`, because asking for a password to make a state directory
is how a second, half-installed layout appears. The Windows deployment's inference
state is neither: llama.cpp runs natively there, so its pid file and log are in
`%LOCALAPPDATA%\osint-ai\server-state`. Downloaded weights are in none of them:
llama.cpp writes them to the standard Hugging Face cache, `~/.cache/huggingface/hub`
under the Linux user and `%USERPROFILE%\.cache\huggingface\hub` on Windows, so
another Hugging Face tool on that PC shares them instead of downloading a second
copy.

Local inference is the one thing the two deployments do differently, and it is the
reason the manifest resolves a second platform. On plain Linux and in WSL the
server is a Pixi environment in the Linux checkout
(`llamacpp-binary-vulkan`), which `pixi r start-server` installs on demand. On
Windows it runs **natively on Windows**, outside the virtual machine, where the
GPU driver is a Windows driver: the Windows installer installs Pixi natively too,
installs the same environment in the Windows checkout (`.pixi/envs/llamacpp-binary-vulkan`
there), and creates the **Start llama.cpp** and **Stop llama.cpp** desktop icons,
which run the same `_server` task the Linux side runs. An assistant inside WSL
reaches that server through the WSL network - the Windows host is the guest's
default gateway, which `scripts/sandbox.py` resolves and exports as `LLAMA_BASE_URL`
and `OSINT_INFERENCE_URL` - and reaching it at all needs an inbound Windows
firewall rule, which the installer adds with one permission prompt, bound to the
WSL virtual adapter and the local subnet. Windows is also the only platform where
the agent-visible checkout is the checkout local inference runs from; keep that in
mind in `docs/security.md`.

There is no Linux installer script, and there should not be one. The README lists
the commands. `pixi r install` is the one step that changes anything on Linux:
`scripts/install-apparmor.sh` loads the AppArmor profile Ubuntu needs for the
bubblewrap this project pins - asking for the maintainer's own password, and a
no-op when the profile is already correct - and `scripts/install-check.sh` then
reports what is missing and proves that binary can start a sandbox. See
[docs/development.md](docs/development.md). The Windows side is
`windows/Install.cmd`, which is a different job: it registers a private WSL
distro as root, its provisioning runs the same AppArmor script as root once, and
it installs the native Windows side of local inference.

## Tasks

```bash
pixi r test                 # python unittest suite; run before declaring anything done
pixi r osint-pi             # chatbot in workspace/ of this checkout (plain Linux)
pixi r osint-pi-wsl         # chatbot in workspace/ of the Windows checkout
pixi r install              # make the pinned bubblewrap allowed to run, then report what is missing
pixi r start-server         # local inference on 127.0.0.1:8080, running in the llamacpp-binary-vulkan environment that Pixi installs; CPU fallback when no Vulkan device available
pixi r update-project       # trusted: git pull --ff-only + pixi install --locked -e default (and inference when installed)
```

For code maintenance you run Pi yourself, unsandboxed, in this checkout:
`pixi shell -e default` and then `pi`. That is different from the sandboxed
assistant, which always works in `workspace/`.

`pixi r osint-pi*` and `pixi r *-server` are thin wrappers: they exec the
root-owned launcher when it is installed, and enter bubblewrap before Pi starts.
The bubblewrap they enter is the one this checkout's locked environment installs
(`.pixi/envs/default/bin/bwrap`), never `/usr/bin/bwrap`: the containment is
pinned by `pixi.lock` and updated by `update-project` with everything else, so a
change to it is a manifest change reviewed like any other.

Local inference has no install task of its own and no wrapper script. It is a
locked dependency in the separate `llamacpp-binary-vulkan` environment, and
`start-server` and `restart-server` depend on `_server`, a task defined in that
environment (`[feature.llamacpp-binary-vulkan.tasks]`), so Pixi installs the
environment because it is about to run a task in it. `stop-server` stays in the
default environment and installs nothing; the Windows desktop icons run
`_server start` / `_server stop` in the inference environment instead, because the
default environment does not resolve for win-64. Do not add a task a user has to
remember before the first start, and do not write a script that asks whether the
inference binary happens to exist - inside that task Pixi already guarantees it.

Adding or updating a dependency is a project-root job:

```bash
pixi add <conda-package>            # or: pixi add --pypi <package>
pixi lock                            # keep pixi.lock in step, both platforms at once
pixi install -e default && pixi r test
```

`pixi lock` solves linux-64 and win-64 together, because the inference environment
resolves for both; `default` is gated to linux-64 and must never gain a Windows
environment, since Pi does not run natively there. A recipe change under
`pixi-recipes/` needs a re-lock too: the lock pins the recipe source, so
`pixi install --locked` fails on a checkout whose lock predates the edit - which is
the point.

Commit `pixi.toml` **and** `pixi.lock` together. Inside the sandbox the
environment is read-only, so a functional agent can never install its own
dependencies; it must ask instead.

## Rules for this repository

* Git here is maintenance work, not the assistant's job: commit with a clear
  message and push to the tracked remote when the operator asks you to, and only
  then. Never force-push, rewrite or discard history nobody asked you to touch,
  and never ask for GitHub credentials. List the files you created or changed,
  with repository-relative paths, and say what is unverified. The sandboxed
  assistant keeps the opposite rule in `workspace/AGENTS.md`: it may commit and
  must never publish.
* Never write API keys, tokens, model weights, Pi sessions or anything personal
  into the checkout.
* Keep the security boundaries described in [`docs/security.md`](docs/security.md)
  intact: bubblewrap before Pi, that bubblewrap being the pinned one from the
  locked environment rather than `/usr/bin/bwrap`, allowlisted mounts, cleared
  environment, the
  program checkout read-only with its repository masked, local inference kept out
  of reach of the agent on Linux (its environment lives in the program checkout,
  and `scripts/server.py` refuses when `OSINT_SANDBOX=1`), no Windows drive other
  than the selected checkout, and no
  project code executed outside the sandbox at boot or startup. One deliberate
  exception, and it is the reason `docs/security.md` has a section about it: on the
  Windows deployment llama.cpp runs natively from the Windows **checkout's**
  environment, which the agent may write to, so the human reviews that checkout
  before clicking a desktop icon that runs it. Keep `--locked` on those pixi
  commands so a manifest that does not match the lock fails instead of quietly
  installing something else. The agent's own
  checkout is writable on purpose, `.git` included; guidance lets it commit and
  forbids it from publishing, and the human reviews every change. The assistant's
  instructions are `workspace/AGENTS.md` and nothing else: the package ships no
  copy of it, `~/.pi/agent/AGENTS.md` is not mounted into the agent home, and
  `scripts/pi-entry.sh` starts Pi with `--no-context-files` plus
  `--append-system-prompt /osint-ai/workspace/AGENTS.md`. Pi loads a context file
  from its working directory *and from every parent directory*, and Pi 1.0.2 has
  no setting to limit that walk, so this file - which sits directly above the
  agent's working directory - is excluded by switching discovery off. Do not
  reintroduce a bind-mount shadow of it: `git status` in the agent's own checkout
  would then report `AGENTS.md` as modified, and a commit would write an empty
  file over it. The
  program-owned files that are in the persistent agent home
  (`~/.pi/agent/keybindings.json`, `~/.pi/web-search.json`) are bound read-only out
  of the environment, never copied: do not turn them back into a copy-on-first-start
  scheme, because a copy in a home that outlives the layout keeps naming paths that
  no longer exist.
* Do not add passwordless `sudo`, do not load shell code from `workspace/`, and
  do not let the boot helper read anything but `/etc/osint-ai.json`. The one
  elevation in the project is `scripts/install-apparmor.sh` asking for the
  maintainer's own password in their own terminal; it refuses to run when
  `OSINT_SANDBOX=1`, so the assistant can never reach it. The Windows installer has
  two of its own: enabling WSL when it is missing, and the inbound firewall rule
  that lets the assistant inside WSL reach the model server on Windows. Both run
  from `Install.ps1`, never from a startup path and never from inside the sandbox.
* Anything new that only the Windows installation uses goes under `windows/`.
  Anything both deployments run goes in `scripts/`. Keep the path tables in
  `README.md`, `docs/development.md` and this file in step with that.
* Functional guidance belongs to the functional workspace: user-facing skill
  rules go in `workspace/AGENTS.md` and `workspace/.agents/skills/`, never into
  this file. User skills are always `workspace/.agents/skills/<name>/SKILL.md`,
  never `~/.pi`, `~/.agents` or `.pi/skills`.
* `model-shortlist.json` is the one place the model shortlist is written. Entries
  are `provider/modelId`, the reference Pi matches, and a test keeps every
  `llama.cpp/...` entry in step with `pixi-recipes/pi-home/models.json` so the
  shortlist never offers a local model the server has no preset for - and never
  the unit-test preset. Merging it into the agent's settings stays additive: the
  launcher adds what is missing and removes nothing, because the user's own
  `/model` choices live in that same list.
* Update `README.md`, `docs/` and `tests/` in the same change as behaviour.
  `docs/testing.md` lists what Linux tests cannot prove; do not imply Windows,
  GPU or OAuth behaviour from a green test run.
* CI (`.github/workflows/ci.yml` and `.github/workflows/llamacpp.yml`) runs only
  what a runner can honestly verify. On Linux that is the unit suite, the installer
  parse test, the bubblewrap smoke test where user namespaces work, and the
  inference smoke test - and `llamacpp.yml` says which half of that smoke test ran
  instead of claiming the sandbox works on a runner that blocks unprivileged user
  namespaces. On Windows one job installs the win-64 inference environment and
  starts and stops the real server through the same controller the desktop icons
  run; it never installs the assistant's `default` environment, which does not
  resolve for win-64 and never should, because Pi only runs inside WSL. Keep the
  jobs in step with `tests/` and with the environment names the launcher and the
  desktop icons look up.
