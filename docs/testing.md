# Validation checklist

This layout is incompatible with installations made before the move to `scripts/`
and `windows/`, and with the ones made before the agent's checkout was mounted
whole at `/osint-ai`: those PCs still have the old root-owned copies in
`/usr/local/lib/osint-ai`, and the launcher prefers an installed copy over the
checkout copy, so `update-project` alone does not change the sandbox. Reinstall
the private WSL distribution (`wsl --unregister osint-ai`, then run
`windows\Install.cmd` again). The Windows checkout and its `workspace/` content
are not touched by the installer. The agent home moved to
`~/.local/state/osint-ai/agent-home` in both deployments, so an old
`/var/lib/osint-ai/agent-home` is simply unused; unregistering the distro deletes
it, and `/login` has to be run again afterwards. Model weights moved out of the
state directory as well: they now live in the standard Hugging Face cache, so an
old `models/` directory under `/var/lib/osint-ai` or
`~/.local/state/osint-ai` is unused and can be deleted to reclaim the space.

## Automated Linux tests

Run `python3 -m unittest discover -s tests -v` (or `pixi r test`). These cover
manifest and recipe configuration, that the sandbox runs the bubblewrap the
lockfile pins rather than `/usr/bin/bwrap` and reports it when that binary is
missing, that the AppArmor profile names that path and that provisioning loads it,
launcher argv construction for both the plain
Linux and the Windows workspace, environment scrubbing, the read-only program
mount and the writable agent checkout, that the checkout is mounted whole so Git
finds `.git` above the working directory, that `/etc/alternatives` is bound so
`which` and `awk` work, that the program-owned `~/.pi` files are read-only mounts
rather than copies and that a stale `~/.pi/agent/npm` link or a stale `skills`
path is repaired, that the model shortlist in the project root is merged into the
assistant's `enabledModels` additively (a model the user saved survives, an entry
already there is not added twice, and the list is read from the checkout that owns
the environment), actual bubblewrap filesystem isolation, Git inside the sandbox
(that `git status` works from Pi's own directory, and that a commit from
inside succeeds, which is the documented consequence of a writable `.git`),
CPU-versus-GPU backend selection and server process ownership/lifecycle with a
fake local server. Integration tests explicitly skip when namespaces are blocked.
A green run on a machine that skips them proves nothing about bubblewrap; say so.

README checks cover the essential commands and workspace paths, and verify that
its contents links and links to local guides resolve. They do not prove that the
guide is easy to follow, that external sites still use the same menus, or that
installation and sign-in work.

```powershell
pwsh -NoProfile -File tests/Test-Installer.ps1     # parse windows/Install.ps1, check escaping
```

Optional full Linux smoke test (installs the real environment, downloads
packages into temporary Linux storage):

```bash
python3 tests/smoke_pixi_sandbox.py
```

CI runs this job too, but only on a runner where unprivileged user namespaces
work; on GitHub-hosted runners it prints `SKIP: ...` and exits 0. See the CI
section below.

It installs the locked `default` environment, probes the bubblewrap that
environment installed - the one the launcher execs - launches real Pi inside
bubblewrap in the plain Linux (`--native`) layout, verifies that Pi's working
directory is `/osint-ai/workspace` and that `git status` succeeds there, and
verifies
`/llama` registration plus discovery of a skill under
`workspace/.agents/skills/`, without any model API calls. Also run Bash syntax
checks and ShellCheck over `scripts/` and `windows/`, and install both Pixi
environments to validate the local build recipes. Never claim Windows support
based on the Python tests alone.

There is no Linux installer to test, by design. The check is that a clean Linux
VM follows the README's Linux commands - including `pixi r install` - and ends up
at a chat prompt. On Ubuntu 24.04 that also proves the AppArmor half: the profile
for `<checkout>/.pixi/envs/*/bin/bwrap` is written and loaded, the assistant starts
afterwards, and a second `pixi r install` asks for no password and changes nothing.
When you cannot do that, say the Linux install is unverified.

The Linux suite checks that the extension pins and the Pi version are what the
repository claims, and that the intercom runtime directory is mounted as a
tmpfs. It cannot show that delegation works: no test starts a child session,
delivers an intercom message, or calls a model. See the checklist items on
delegation.

## GitHub Actions CI

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs on every push to
`main`, on every pull request and on manual dispatch. Three jobs:

* **Unit tests** (`ubuntu-latest`): installs the locked `default` Pixi
  environment, then `pixi run test`. It installs no bubblewrap of its own: the
  sandbox runs the one that environment brings, which is also the binary the
  integration tests probe, so a green job tests the containment it actually ships.
  Installing `default` is what lets the tests that look inside `.pixi/envs/default`
  (the packaged extension tree, the bundled Pi home) run instead of skipping.
  `locked: true` fails a `pixi.toml` change whose `pixi.lock` was not re-locked in
  the same change. The cache key includes the contents of `pixi-recipes/`, because
  those packages are built from source and are not covered by `pixi.lock`: without
  it a recipe edit would be tested against a stale cached environment.
* **Windows installer parse** (`windows-latest` and `ubuntu-latest`):
  `pwsh -NoProfile -File tests/Test-Installer.ps1`. It parses
  `windows/Install.ps1`, checks its shell-argument escaping and the syntax of
  the Bash it embeds. Parsing is not installing.
* **Sandbox smoke test** (`ubuntu-latest`): `python3 tests/smoke_pixi_sandbox.py`,
  gated on a cheap `unshare` probe so a runner that cannot sandbox does not sit
  through a package download first. The job installs only the `pixi` binary; the
  script copies the checkout, installs the locked environment into that copy, and
  probes the bubblewrap that install produced. GitHub-hosted runners restrict
  unprivileged user namespaces (AppArmor on Ubuntu 24.04), so there the job posts
  a warning and does not run, and the script itself prints `SKIP: ...` and exits
  0. Run it by hand where bubblewrap works. This job only probes: it deliberately
  installs no AppArmor profile, while the inference job below runs
  `pixi r install`, which does.

* **Native Windows inference** (`windows-latest`): installs Pixi and the locked
  `llamacpp-binary-vulkan` environment - the only environment that resolves for
  win-64, and the only place the win-64 half of the recipe is built - runs the
  native `llama-server --version` and `--list-devices`, and then starts and stops a
  real server through `_server`, which is the same controller and the same task the
  desktop icons run. Nothing on Linux can substitute: the recipe builds a different
  asset there, and the controller's Windows code path (no `fork`, no `fcntl`,
  process identity from a creation time, `taskkill`) never executes on Linux. This
  job never installs the `default` environment, because Pi does not run natively on
  Windows.

No job in `ci.yml` installs the assistant's environment on Windows or macOS: it
resolves for linux-64 only, on purpose. Its unit job installs `default` alone, so
neither inference environment is part of it.

[`.github/workflows/llamacpp.yml`](../.github/workflows/llamacpp.yml) is the one
job that does install and run local inference on Linux:

* **Local inference + assistant smoke test** (`ubuntu-latest`): installs the
  locked `default` and `llamacpp-binary-vulkan` environments, then runs the
  documented `pixi r install` - which loads the AppArmor profile the pinned
  bubblewrap needs - and starts the real server with `pixi r start-server`. On a
  GPU-less runner that proves the documented CPU fallback, because the Vulkan
  backend is a shared object next to the executable and a machine with no Vulkan
  device cannot load it, so the same build runs on the processor. It loads the
  `LFM2.5-230M` preset - the one `models.ini` marks unit-test only - through
  `/models/load` and waits for the status to say `loaded`, so the assistant's own
  request is not the thing paying for a cold download. It then asks the real
  assistant, through `pixi r osint-pi` and therefore inside bubblewrap, for an
  answer, restarts the server and asks again with the weights now cached, stops it,
  and dumps the server log either way. A missing model, a dead server or a sandbox
  that cannot start fails the job; there is no unsandboxed `pi` in it, and no
  `--no-sandbox` flag to reach for.
  Where the runner refuses unprivileged user namespaces *outright* the profile
  cannot help, so the job records a warning and runs the inference half only; if
  Ubuntu's AppArmor restriction is still on after the profile was loaded, the
  sandbox is broken and the job fails. It never starts a bare `pi`.

  On a GitHub-hosted runner this job does reach the sandboxed half: the AppArmor
  profile is written for the pinned binary there and Pi starts inside it - a
  prompt answered with `Hello world! How can I assist you today?` on a runner with
  no GPU is real evidence, not a claim. The `ci.yml` sandbox job still skips on
  those runners, because it probes instead of installing the profile.

A green CI run does **not** prove: the sandbox's mount layout, environment
scrubbing or read-only program checkout (Pi really does start inside the pinned
bubblewrap, but no job asserts what the namespace contains), Git inside the
sandbox on a runner that blocks unprivileged user namespaces anyway, the
Windows installer, WSL provisioning, reboot, DrvFS mounts, MobaXterm, desktop
shortcuts, the firewall rule, the WSL-to-Windows link the assistant actually uses
for local models, GPU offload or that a preset fits the user's PC (the smoke test
proves CPU inference of one 350M test model; the Windows job proves the server
starts, not that a model loads), OpenRouter OAuth, delegation, or that a
non-technical user can follow the README. Those stay in the matrix
below.

## Required Windows 11 x64 acceptance matrix

Test on clean Home and Pro machines/VMs with virtualization enabled:

- [ ] No WSL: Install.cmd elevates only feature setup; reboot/rerun works under
      the original Windows account. No unwanted default Ubuntu distro is created.
- [ ] Existing WSL and unrelated distros remain unchanged. An unrelated
      `osint-ai` distro is rejected; no distro is unregistered.
- [ ] A non-technical user can follow the README to start a chat, put a file in
      `workspace`, edit and reload a rule, and review and share only intended
      files in the correct team repository. Check online login menus, the local
      model workflow (**Start llama.cpp**, then `/model`, then `/llama` for a
      visible download) and the optional basic shortcut against the guide.
- [ ] First install, interrupted install retry, and completed-install rerun
      preserve both checkouts and user state. Paths with spaces, apostrophes and
      non-ASCII work.
- [ ] NTFS selected; OneDrive/junction/UNC paths fail clearly. A private GitHub
      clone prepared by a Windows GUI is reused without importing credentials
      into WSL.
- [ ] Linux checkout is created at `/home/osint/osint-ai` with the right origin;
      the Windows checkout is mounted at `/mnt/osint-ai` on every distro start.
- [ ] The sandbox runs `/home/osint/osint-ai/.pixi/envs/default/bin/bwrap` and the
      distro has no bubblewrap package installed at all. Provisioning loaded the
      AppArmor profile in the same boot it installed the environment: the
      acceptance check `osint-pi-wsl --version` passing, `cat /etc/apparmor.d/bwrap`
      naming that path, and `apt list --installed '*bubblewrap*'` answering nothing
      together prove it. A later `pixi r install` as the `osint` user reports
      `ok bubblewrap`, needs no password and changes nothing.
- [ ] Desktop shortcuts work: **OSINT AI Terminal** opens MobaXterm, runs
      `osint-terminal` (reports whether local inference answers, then
      `pixi r osint-pi-wsl`), and reaches the chat prompt. With inference stopped it
      still reaches the chat, says no local server is running, and uses a hosted
      model.
      **OSINT AI Terminal (basic)** works when MobaXterm is absent or
      refuses the command. **OSINT AI Files** opens the checkout.
- [ ] **Start llama.cpp** installs the environment on first use if needed, reports
      the Vulkan device (or the CPU fallback), and exits; **Stop llama.cpp** stops
      it. The installer already proved the link once: it starts the server, asks
      `/health` from inside WSL at the address `sandbox.py --wsl --inference-url`
      prints, and stops it. After that, a local model answers in the assistant
      without any further setup, and `pixi r update-project` inside WSL does not
      disturb it.
- [ ] The firewall rule exists once, is named `OSINT AI local inference`, is bound
      to the WSL adapter and the local subnet, and rerunning the installer reuses it
      without a new prompt. Declining that prompt leaves online models working and
      prints a message saying what to do - not a failed installation.
- [ ] MobaXterm: an existing installation is reused, not duplicated. The download
      is checksum verified, `-SkipMobaXterm` skips it, and a tampered download is
      refused.
- [ ] WSL termination/restart remounts `/mnt/osint-ai` before any Pixi
      invocation. A failed mount fails closed instead of writing to NTFS.
- [ ] Chatbot starts in `/osint-ai/workspace`, the `workspace/` of the Windows
      checkout. `/opt/osint-ai/project` is present and read-only; `pixi add` and
      writes to root files fail inside the session.
- [ ] No `C:\`, other drives, `\\wsl$`, `/dev/dxg`, WSL interop sockets or host
      home directories are reachable from inside the session. Neither the host
      path `/mnt/osint-ai` nor a workspace mount of its own exists inside the
      session. The Linux checkout's `.git`
      is absent, and `/opt/osint-ai/project` is read-only.
- [ ] `git status` inside the session, run from the assistant's own working
      directory, reports the Windows checkout and matches GitHub Desktop for
      clean, modified, untracked and ahead-of-remote cases, and the assistant's
      reminder wording is right. `which awk` and `awk --version` work inside the
      session. Confirm by hand that the assistant commits when asked, starts on
      `staging` (switching from `main` when the checkout is there), merges `main`
      into `staging` when `main` has moved on, and never pushes, leaves `staging`,
      rebases or discards anything on its own; treat any behaviour to the
      contrary as a bug.
- [ ] New skill lands in `workspace\.agents\skills\<name>\SKILL.md`; Notepad
      sees it immediately and
      `/reload` + `/skill:<name>` find it. `workspace\AGENTS.md` is loaded and
      editable. Nothing is written to `~/.agents` or `.pi/skills`.
- [ ] The assistant's guidance comes from `workspace\AGENTS.md` alone: the installed
      package ships no `AGENTS.md`, nothing is mounted at `~/.pi/agent/AGENTS.md`, and a
      copy left there by an earlier version is renamed to `AGENTS.md.stale` on the next
      start instead of being loaded by Pi. The startup header lists
      `/osint-ai/workspace/AGENTS.md` under `Context` and **no other** instructions
      file: not `/osint-ai/AGENTS.md`, the maintainer's guide that sits above the
      workspace so Git works, and not anything in the agent home. `git status` inside
      the session must show a clean checkout, with no phantom `AGENTS.md` change. `~/.pi/agent/keybindings.json` is still a
      read-only mount: a file left there by an earlier version is shadowed, and a write
      to it from inside the session fails. After a
      fresh install plus a used agent home, `~/.pi/agent/npm` is a working link and
      Pi starts instead of crashing with `ENOENT ... mkdir '/home/osint/.pi/agent/npm'`.
- [ ] Login, sessions and settings persist in `~/.local/state/osint-ai/agent-home`
      across restarts,
      including `~/.pi/agent/settings.json` keys the user changed; `packages` and
      `skills` are reset to the installed values on each launch.
- [ ] `~/.pi/agent/auth.json` is inside a `0700` directory: `/home/osint/.local/state/
      osint-ai/agent-home`, the same location a plain Linux install uses. A second
      local account cannot read it, and it is absent from the Windows checkout, from
      `/mnt/osint-ai` and from `/osint-ai`. Running the assistant repairs an agent
      home left group-readable by an older version, and the installer must not have
      created `/var/lib/osint-ai/agent-home`.
- [ ] `spreadsheet-reader` reads `.xls`, `.xlsx`, `.xlsb`, `.csv`, warns on a
      mislabelled file, and never modifies the source.
- [ ] `compliance-report` produces a report with the agreed section order, a
      confidence label on every fact, a populated `Sources` list, and nothing
      invented; the Markdown is left in `workspace\reports\` next to the PDF.
- [ ] `markdown-pdf` produces a PDF whose title is printed **once**, with the
      date and the optional contents list after it, that `pdfinfo`/`pdftotext`
      confirm and whose rendered page image is readable; `.notdef glyph`
      warnings are reported to the user instead of shipping empty boxes;
      scanned PDFs are reported as unreadable.
- [ ] Windows junctions, symlinks, hardlinks and rename races across the shared
      directory boundary are tested. These require Windows tests, not Linux mocks.
- [ ] OpenRouter OAuth URL/callback paste and API-key login work. Login, sessions
      and settings persist after a restart.
- [ ] Delegation: the assistant hands a wide research job to a sub-agent, the
      child finishes, and the answer arrives with links and dates. The child
      creates no file outside the checkout; it cannot read the Linux checkout's
      code or history; note the extra time on a local model.
- [ ] A blocked sub-agent can reach the chat it was started from, and a second
      **OSINT AI Terminal** window does not steal the first window's intercom
      broker. After a restart, no message from the previous session is
      delivered. The socket is absent outside the sandbox.
- [ ] No Vulkan device at all: **Start llama.cpp** reports the CPU fallback, exits
      0, and a small model answers (slowly). Accept only a real answer, not
      `vulkaninfo` output.
- [ ] Vulkan-capable GPU + driver (NVIDIA, AMD or Intel): **Start llama.cpp** names
      a Vulkan device and the model really offloads. **Stop llama.cpp** and a second
      **Start llama.cpp** are idempotent; an occupied port, a startup timeout and a
      crash are reported with the log path; cached weights survive.
- [ ] The server is reachable from inside WSL and from nowhere else: the assistant
      gets an answer from a local model, while another PC on the same LAN cannot
      open `http://<windows-host>:8080/health`. Removing the firewall rule breaks
      the assistant's access and nothing else, and the message it prints names the
      rule.
- [ ] Local inference is optional, and on the Windows deployment it is not inside
      the distribution at all: `python3 /usr/local/lib/osint-ai/sandbox.py --wsl
      --inference-url` prints the Windows host, and `install-check.sh` reports
      whether it answers instead of claiming a missing environment. Deleting
      `C:\Users\<name>\osint-ai\.pixi\envs\llamacpp-binary-vulkan` is repaired by
      the next **Start llama.cpp** (that is what `pixi run --locked` does), while a
      manifest that no longer matches `pixi.lock` fails with a clear message.
      On plain Linux `pixi r start-server` installs the environment into the
      checkout as the current user, `pixi r update-project` updates it together
      with the assistant's environment, `stop-server` installs nothing, and
      `pixi r install` reports its absence without calling it MISSING.
- [ ] `pixi r update-project` updates a WSL installation and the next chatbot
      start uses the new tools; a diverged Linux checkout is refused.
- [ ] README uninstall steps work in order on a used installation: unregistered
      distro, `%LOCALAPPDATA\osint-ai` gone (including the native Pixi and the
      Windows inference environment), `%USERPROFILE%\.cache\huggingface` gone,
      firewall rule removed, icons gone, no other distro touched,
      `wsl --uninstall` not required. Reinstall + **Pull** restores skills and
      `workspace/AGENTS.md`, and a deleted OpenRouter key stops working.

## Release gates still outside skeleton

Signed Windows installer, published immutable release, full supply-chain lock and
update process, download/disk-space UX, installer rollback/uninstall, automated
Windows VM tests, supported GPU/driver matrix, security review, resource quotas,
and model presets appropriate for supported consumer hardware.
