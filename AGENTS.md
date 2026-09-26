# OSINT AI — developer instructions

This checkout is the **project root**: Git, `pixi.toml`, `pixi.lock`, the
installer and the sandbox live here. You are here to maintain the software, not
to do compliance research. Start Pi in this directory for maintenance work.

The end user is a compliance officer with no programming background, and the
result must run on a Windows 11 PC through WSL. Prefer boring, verifiable
solutions and explain results in plain language.

## Layout

| Path | Purpose |
| --- | --- |
| `README.md` | Absolute-beginner guide: install, Git, Pi commands, AGENTS.md, skills. Keep it jargon-free. |
| `AGENTS.md` | This file: instructions for maintaining the project. |
| `workspace/` | The **functional** workspace. Its own `AGENTS.md` and `.agents/skills/` drive the chatbot; that is a different job from this one. |
| `wsl/` | Windows installer (`Install.cmd`, `Install.ps1`) and the trusted Linux-side runtime: `wsl/scripts/` sandbox launcher, server controller, boot mount helper, provisioning. |
| `pixi-recipes/` | Local build recipes: Pi, extensions, the bundled home configuration, the CUDA llama.cpp binary. |
| `models.ini` | Inference presets snapshot used by the installed runtime. |
| `docs/` | `development.md`, `security.md`, `testing.md`, `upstream.md`. |
| `tests/` | Linux/Python tests plus the PowerShell installer parse test. |

## Two checkouts, one product

In WSL the repository exists twice, by design:

* `/home/osint/osint-ai` — Linux checkout. Owns `pixi.toml`, the Pixi
  environments and the code that executes. Updated by a maintainer with
  `update-project`. Mounted read-only in the sandbox, with its `.git` masked.
* `C:\Users\<name>\osint-ai`, mounted at `/mnt/osint-ai` — Windows checkout. The
  user edits `workspace/` there and commits with a Windows Git GUI. Bound
  read-write in the sandbox, `.git` included, so the assistant can run
  `git status` itself; it is told never to commit, push or discard work.

`osint-pi-wsl` binds the Linux checkout **read-only** at `/opt/osint-ai/project`
and the Windows checkout **read-write** at `/mnt/osint-ai`; the sandboxed agent
sees neither root-owned file, and cannot change the program. Tell the user that
changes to the program's own files must be made in the project root checkout,
then `update-project`d on the WSL side.

## Tasks

```bash
pixi r test                 # python unittest suite; run before declaring anything done
pixi r osint-pi             # chatbot in workspace/ of this checkout (plain Linux)
pixi r osint-pi-wsl         # chatbot in workspace/ of the Windows checkout
pixi r install              # installation check and usage summary
pixi r restart-server       # local inference (CPU fallback when no CUDA device works)
pixi r update-project       # trusted: git pull --ff-only + pixi install --locked -e default
```

For code maintenance you run Pi yourself, unsandboxed, in this checkout:
`pixi shell -e default` and then `pi`. That is different from the sandboxed
assistant, which always works in `workspace/`.

`pixi r osint-pi*` and `pixi r *-server` are thin wrappers: they exec the
root-owned launcher when installed, then enter bubblewrap before Pi starts.

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
* Functional guidance belongs to the functional workspace: user-facing skill
  rules go in `workspace/AGENTS.md` and `workspace/.agents/skills/`, never into
  this file. User skills are always `workspace/.agents/skills/<name>/SKILL.md` —
  never `~/.pi`, `~/.agents` or `.pi/skills`.
* Update `README.md`, `docs/` and `tests/` in the same change as behaviour.
  `docs/testing.md` lists what Linux tests cannot prove; do not imply Windows,
  GPU or OAuth behaviour from a green test run.
