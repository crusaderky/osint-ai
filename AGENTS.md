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
| `AGENTS.md` | This file: instructions for maintaining the project. |
| `workspace/` | The **functional** workspace. Its own `AGENTS.md` and `.agents/skills/` drive the chatbot; that is a different job from this one. |
| `scripts/` | The runtime, shared by both deployments: `bwrap-pi.sh` (the one sandbox launcher), `sandbox.py`, `pi-entry.sh`, the inference server controller, `update-project.sh`, `install-check.sh`. |
| `windows/` | Everything only the Windows deployment uses: `Install.cmd`, `Install.ps1`, `provision-wsl.sh`, the boot mount helper, and `launchers/` (the copies installed to `/usr/local/bin`). The bash scripts in here run inside the WSL distro the installer creates. |
| `pixi-recipes/` | Local build recipes: Pi, extensions, the bundled home configuration, the CUDA llama.cpp binary. |
| `models.ini` | Inference presets snapshot used by the installed runtime. |
| `docs/` | `development.md`, `security.md`, `testing.md`, `upstream.md`. |
| `tests/` | Linux/Python tests plus the PowerShell installer parse test. |

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
  user edits `workspace/` there and commits with a Windows Git GUI. Bound
  read-write in the sandbox, `.git` included, so the assistant can run
  `git status` itself; it is told never to commit, push or discard work.

`bwrap-pi.sh --wsl` binds the Linux checkout **read-only** at
`/opt/osint-ai/project` and the Windows checkout **read-write** at
`/mnt/osint-ai`. The sandboxed agent sees neither root-owned file and cannot
change the program. Tell the user that changes to the program's own files happen
in the project root checkout, followed by `update-project` on the WSL side.

There is no Linux installer script, and there should not be one. The README lists
the commands; [docs/development.md](docs/development.md) has the one extra
step (an AppArmor profile) that Ubuntu needs. The Windows side is
`windows/Install.cmd`, which is a different job: it registers a private WSL
distro as root.

## Tasks

```bash
pixi r test                 # python unittest suite; run before declaring anything done
pixi r osint-pi             # chatbot in workspace/ of this checkout (plain Linux)
pixi r osint-pi-wsl         # chatbot in workspace/ of the Windows checkout
pixi r install              # installation check and usage summary; installs nothing
pixi r restart-server       # local inference (CPU fallback when no CUDA device works)
pixi r update-project       # trusted: git pull --ff-only + pixi install --locked -e default
```

For code maintenance you run Pi yourself, unsandboxed, in this checkout:
`pixi shell -e default` and then `pi`. That is different from the sandboxed
assistant, which always works in `workspace/`.

`pixi r osint-pi*` and `pixi r *-server` are thin wrappers: they exec the
root-owned launcher when it is installed, and enter bubblewrap before Pi starts.

Adding or updating a dependency is a project-root job:

```bash
pixi add <conda-package>            # or: pixi add --pypi <package>
pixi lock                            # keep pixi.lock in step
pixi install -e default && pixi r test
```

Commit `pixi.toml` **and** `pixi.lock` together. Inside the sandbox the
environment is read-only, so a functional agent can never install its own
dependencies; it must ask instead.

## Rules for this repository

* Never commit, push, rebase or configure Git, and never ask for GitHub
  credentials. The human reviews and publishes with a Windows Git GUI. List the
  files you created or changed, with repository-relative paths, and say what is
  unverified.
* Never write API keys, tokens, model weights, Pi sessions or anything personal
  into the checkout.
* Keep the security boundaries described in [`docs/security.md`](docs/security.md)
  intact: bubblewrap before Pi, allowlisted mounts, cleared environment, the
  program checkout read-only with its repository masked, no writable copy of the
  inference runtime, no Windows drive other than the selected checkout, and no
  project code executed outside the sandbox at boot or startup. The agent's own
  checkout is writable on purpose, `.git` included; guidance forbids it from
  publishing, and the human reviews every change.
* Do not add passwordless `sudo`, do not load shell code from `workspace/`, and
  do not let the boot helper read anything but `/etc/osint-ai.json`.
* Anything new that only the Windows installation uses goes under `windows/`.
  Anything both deployments run goes in `scripts/`. Keep the path tables in
  `README.md`, `docs/development.md` and this file in step with that.
* Functional guidance belongs to the functional workspace: user-facing skill
  rules go in `workspace/AGENTS.md` and `workspace/.agents/skills/`, never into
  this file. User skills are always `workspace/.agents/skills/<name>/SKILL.md`,
  never `~/.pi`, `~/.agents` or `.pi/skills`.
* Update `README.md`, `docs/` and `tests/` in the same change as behaviour.
  `docs/testing.md` lists what Linux tests cannot prove; do not imply Windows,
  GPU or OAuth behaviour from a green test run.
