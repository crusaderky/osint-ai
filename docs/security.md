# Security design and limits

This is a first implementation, not an audited security product. Do not distribute
it as protection from hostile malware until Windows acceptance and security tests
have passed. Bubblewrap is the enforcement mechanism; AGENTS.md is guidance only.

## Trust boundaries

1. Windows installer and first cloned release are trusted. Pin a reviewed release
   tag when packaging; a mutable `main` default is for skeleton development only.
   Ubuntu rootfs, Pixi binary and llama.cpp release asset are SHA-256 verified.
   Apt/Conda/npm retain their upstream trust and supply-chain risks.
2. WSL root provisions boot helper, launchers and inference snapshot once. The
   root helper reads only `/etc/osint-ai.json`; no project shell code or config is
   sourced at boot. A drive is temporarily mounted under root-only `/run` storage;
   only the selected checkout is bind-mounted, then the full-drive mount is removed.
   Directory file descriptors pin bind-mount sources/targets; mount canonicalization
   is disabled so those handles are not converted back to mutable pathnames.
3. `osint-pi` constructs an allowlisted root filesystem with cleared environment.
   It enters bubblewrap *before* Pixi reads `pixi.toml` or executes build backends.
   Runtime code installed through agent-edited dependencies remains sandboxed.
4. The agent can write project content, `AGENTS.md`, manifests, its Linux .pixi,
   and persistent application home/cache. Its `.git` is an empty read-only mount.
   Tracked installer scripts and bundled recipes are read-only. No blanket `/`
   bind, Windows drive mount, WSL interop socket, host /run or host home is exposed.
5. Inference intentionally runs outside bubblewrap under the ordinary WSL user.
   It never executes the project manifest or project environment. Its installed
   binary, libraries and model preset are a root-owned snapshot; its package
   cache is separate to avoid writable hardlink aliases from agent environments.
   The server only binds WSL loopback. Agent talks to it through HTTP.
6. The normal WSL user is not a sudoer. Windows owner can still enter the distro
   as root; protecting against the machine owner is not a goal.

## Explicit limitations

- The sandbox can send any readable data over the network. Pi provider credentials
  must be available to Pi and are not isolated from its shell tools/extensions.
- Network isolation is not attempted. Local/LAN services can be reached, including
  inference and browser OAuth callback listeners. Network-mounted files/services
  are not covered by filesystem hiding.
- The agent can delete or poison writable skills, manifests and its own state.
  Human review, backups and Git history remain necessary. Generated dependencies,
  skills and extensions are code, not inert documents.
- Any user who chooses to run an edited project task outside the sandbox grants it
  normal WSL-user privileges. In particular, `pixi r install` is a trusted manual
  operation, not an automatic daily startup command.
- The native inference HTTP/model parser is not sandboxed. Use trusted model
  sources. Its model-management API must not be treated as a hardened untrusted
  file broker. Review server security updates separately.
- Windows NTFS reparse points/junctions, hardlinks, DrvFS semantics and concurrent
  Windows edits need adversarial validation. Linux symlink tests alone do not
  establish that Windows filesystem paths cannot bypass intended boundaries.
- No resource quotas yet: malicious code can consume CPU, memory, disk or network.
- Browser, clipboard and Windows executable bridging are deliberately omitted.
  OAuth uses displayed URLs and manual copy/paste, not generic host execution.
- Global device access is absent from the agent; CUDA inference retains WSL GPU
  access outside bubblewrap as explicitly required.

## Maintenance

`start-server` ignores later edits to checkout `models.ini` and inference recipes.
The maintainer must review and reinstall its trusted snapshot deliberately. Never
"fix" this by running an agent-editable `pixi run start-server` outside containment.
Do not add passwordless sudo of a project script or load `/etc/wsl.conf` commands
from the writable checkout. Existing installations are not silently upgraded.
