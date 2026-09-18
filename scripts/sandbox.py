#!/usr/bin/python3
"""Build the agent's allowlisted mount namespace, then start Pi inside it.

Started by ``scripts/bwrap-pi.sh``, which passes one of two modes.

``native``
    Plain Linux. One checkout does everything: it holds Git, ``pixi.toml`` and
    ``.pixi``, and it is mounted read-write at ``/osint-ai``. Pi starts in
    ``/osint-ai/workspace``.

``wsl``
    Windows deployment. The same repository is checked out twice:

    * a Linux checkout (default ``/home/osint/osint-ai``) owns the manifest and
      the Pixi environments, and is what executes;
    * a Windows checkout (mounted by the boot helper at ``/mnt/osint-ai``)
      holds the files the user edits and commits.

    The Windows checkout is mounted read-write at ``/osint-ai`` and Pi starts in
    its ``workspace``, so ``git status`` there describes the checkout the user
    commits from GitHub Desktop. The Linux checkout stays read-only at
    ``/opt/osint-ai/project`` with its own ``.git`` masked, so the program that
    starts Pi cannot be changed from inside a session.

In both modes the checkout is mounted **whole**, and Pi's working directory is
the ``workspace`` directory *inside* it. Git finds its repository by walking up
from the working directory, so mounting ``workspace/`` on its own - as earlier
revisions did - leaves no ``.git`` above it and every Git command fails with
"not a git repository". The agent's checkout is at the same sandbox path,
``/osint-ai``, in both modes, so skills, ``workspace/AGENTS.md`` and every
documented path are the same on Linux and on Windows.

Nothing the sandboxed agent can write is executed outside the sandbox; the
read-only ``.pixi`` environment supplies the Pi binary and the command-line
tools available to skills, and it supplies the bubblewrap that builds the
namespace too, so the containment itself is pinned by the same lockfile rather
than being whatever the distribution happens to ship. The agent can read its
checkout's whole Git history and, because ``.git`` is writable, could commit,
switch branches or discard work. ``workspace/AGENTS.md`` and ``docs/security.md``
state what it is told not to do, and the user reviews every change.
"""

import argparse
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

# The checkout the agent works in. Same sandbox path in both modes, so every
# path in workspace/AGENTS.md, in the skills and in Pi's settings is
# deployment-independent.
AGENT_MOUNT = Path("/osint-ai")
WORKSPACE_SUBDIR = "workspace"
WORKSPACE_MOUNT = AGENT_MOUNT / WORKSPACE_SUBDIR
SKILLS_MOUNT = WORKSPACE_MOUNT / ".agents" / "skills"
# WSL only: the read-only Linux checkout that supplies the code and the tools.
PROGRAM_MOUNT = Path("/opt/osint-ai/project")
# WSL only: where the root-owned boot hook mounts the Windows checkout on the host.
WINDOWS_HOST_MOUNT = Path("/mnt/osint-ai")
DEFAULT_PROJECT_ROOT = Path("/home/osint/osint-ai")
# The agent home lives in the Linux user's own state directory in both
# deployments. In WSL that user is `osint`, so it is /home/osint/.local/state/
# osint-ai - the same place a plain Linux install puts it.
STATE_SUBPATH = Path(".local") / "state" / "osint-ai"
ENV_NAME = "default"
# Where the assistant talks to local inference. Plain Linux runs llama.cpp in
# this checkout, so that is loopback. The Windows deployment runs it natively,
# outside WSL: the assistant reaches it through the default gateway of the WSL
# network, which *is* the Windows host, and never through loopback - the two are
# different network namespaces. `inference_url()` resolves it at launch.
INFERENCE_PORT = 8080
INFERENCE_FALLBACK_URL = f"http://127.0.0.1:{INFERENCE_PORT}"
# The sandbox binary itself, from the environment this lockfile pins. Running the
# distribution's `/usr/bin/bwrap` would leave the program that builds the agent's
# mount namespace outside the reviewed lockfile, so `update-project` would update
# Pi and the tools while the containment stayed whatever the distro shipped.
# Ubuntu 23.10+ needs an AppArmor profile for this path; `pixi r install` loads it
# (scripts/install-apparmor.sh) and proves the binary can start a sandbox.
BWRAP_SUBPATH = Path(".pixi") / "envs" / ENV_NAME / "bin" / "bwrap"
LINUX_FILESYSTEMS = {"ext4", "xfs", "btrfs"}
# Debian and Ubuntu resolve many /usr/bin names through /etc/alternatives:
# /usr/bin/which, /usr/bin/awk, /usr/bin/pager, /usr/bin/editor and others are
# symlinks into it. /etc is a fresh directory here with only the files listed
# below, so without this bind those commands are present but broken and the
# assistant sees "which: command not found".
ETC_ALTERNATIVES = "/etc/alternatives"
# pi-intercom keeps its broker socket, PID file, spawn lock and queued mail in
# ~/.pi/agent/intercom. The agent home is persistent and writable, so without a
# private mount that runtime state would outlive the session: a second terminal
# window would unlink the live broker's socket on startup, and mail queued for a
# closed session could be redelivered to a later one. A fresh tmpfs per sandbox
# gives every launch its own broker, keeps the socket out of the persistent home,
# and still lets a parent session talk to its sub-agent children, which share
# this namespace. Nothing outside the sandbox can reach the socket.
INTERCOM_DIR = "/home/osint/.pi/agent/intercom"
# Program-owned Pi home files, mounted read-only out of the environment instead
# of copied into the agent home. A copy written once into a home that outlives the
# layout keeps telling the agent paths that no longer exist, and nothing refreshes
# it; a mount always shows what the installed environment actually contains, and
# the agent cannot rewrite it. Relative to
# <project root>/.pixi/envs/<env>/home/.pi. The agent's instructions are not here:
# they are `workspace/AGENTS.md` in the checkout the agent works in, which
# `scripts/pi-entry.sh` names on Pi's command line while Pi's own context-file
# discovery is switched off, so the checkout root's maintainer `AGENTS.md` above
# the working directory is not loaded either.
PI_HOME_BINDS = (
    ("agent/keybindings.json", "/home/osint/.pi/agent/keybindings.json"),
    ("web-search.json", "/home/osint/.pi/web-search.json"),
)
# The identity every commit the assistant makes is attributed to. See
# `GIT_AUTHOR_NAME` below.
GIT_IDENTITY_NAME = "OSINT AI assistant"
GIT_IDENTITY_EMAIL = "assistant@osint-ai.invalid"
BUNDLED_HOME_SUBPATH = Path(".pixi") / "envs" / ENV_NAME / "home" / ".pi"
# The shortlist of models the assistant is offered, in the project root. It is
# read from the *program* checkout - read-only in WSL, with its `.git` masked -
# so the assistant cannot widen its own model list by editing its own checkout.
MODEL_SHORTLIST_NAME = "model-shortlist.json"


def require_directory(path, hint=""):
    if path.is_symlink():
        raise RuntimeError(f"Expected a real directory, not a symlink: {path}{hint}")
    if not path.is_dir():
        raise RuntimeError(f"Expected a real directory, found nothing usable: {path}{hint}")


def require_checkout(checkout, repair):
    """The agent works in a real Git repository, so it has to be really there."""
    git = checkout / ".git"
    if git.is_symlink() or not git.is_dir():
        raise RuntimeError(
            f"{checkout} is not a Git checkout ({git} is missing). Without it the "
            f"assistant cannot run `git status`. {repair}"
        )


def filesystem(path):
    return subprocess.check_output(
        ["/usr/bin/findmnt", "-n", "-o", "FSTYPE", "-T", str(path)],
        text=True,
    ).strip()


def default_state():
    """Persistent, writable, private application state: the same in both modes.

    The only thing a deployment changes is which checkout the workspace comes
    from. Where the assistant keeps its sign-in, sessions and settings is not a
    deployment-specific detail.
    """
    override = os.environ.get("OSINT_STATE_DIR")
    if override:
        return Path(override)
    return Path.home() / STATE_SUBPATH


def bwrap_path(project):
    """The bubblewrap this checkout's locked environment provides."""
    return project / BWRAP_SUBPATH


def default_gateway():
    """The default gateway of this machine, or None.

    `/proc/net/route` rather than `ip route`: the private WSL distribution
    installs no iproute2, and this has to work before anything else is
    installed. The field is little-endian hex.
    """
    try:
        lines = Path("/proc/net/route").read_text().splitlines()
    except OSError:
        return None
    for line in lines[1:]:
        fields = line.split()
        if len(fields) >= 3 and fields[1] == "00000000":
            address = int(fields[2], 16)
            return ".".join(str((address >> shift) & 0xFF) for shift in (0, 8, 16, 24))
    return None


def inference_url(mode):
    """Where the assistant finds local inference.

    Plain Linux: the server runs in this checkout and listens on loopback. WSL:
    llama.cpp runs natively on Windows, outside the virtual machine, so the
    address is the host at the other end of the WSL network - the default
    gateway - and loopback would find nothing. The address is recomputed at every
    launch because WSL can hand out a different subnet; the Windows firewall rule
    that admits it is bound to the interface, not to the address.
    """
    override = os.environ.get("OSINT_INFERENCE_URL")
    if override:
        return override
    if mode == "wsl":
        host = default_gateway()
        if host:
            return f"http://{host}:{INFERENCE_PORT}"
    return INFERENCE_FALLBACK_URL


def check_storage(mode, project, windows, state):
    require_directory(project, " (the project root; choose another with --root)")
    require_directory(state / "agent-home", " (restart the OSINT AI terminal)")
    if not (project / ".pixi" / "envs" / ENV_NAME / "bin" / "pi").is_file():
        raise RuntimeError(
            f"The '{ENV_NAME}' environment is not installed in {project}. "
            "Run: pixi install --locked -e "
            + ENV_NAME
        )
    # Nothing about the sandbox works without it, and a missing or non-executable
    # file here would otherwise look like a failure of bubblewrap itself.
    bwrap = bwrap_path(project)
    if not bwrap.is_file() or not os.access(bwrap, os.X_OK):
        raise RuntimeError(
            f"bubblewrap is missing or not executable: {bwrap}. The sandbox cannot "
            f"start without it. Run: pixi install --locked -e {ENV_NAME} "
            "(then `pixi r install`, which also loads the AppArmor profile Ubuntu "
            "needs for this path)."
        )
    # The keybindings and the extension settings come out of that environment, so
    # a half-installed environment has to be reported before the sandbox starts.
    if not (project / BUNDLED_HOME_SUBPATH / "agent/keybindings.json").is_file():
        raise RuntimeError(
            f"The bundled Pi home is missing from {project}. "
            "Run: pixi install --locked -e "
            + ENV_NAME
        )
    # Pixi environments must never live on a Windows filesystem.
    fs = filesystem(project / ".pixi")
    if fs not in LINUX_FILESYSTEMS:
        raise RuntimeError(f"Refusing to use Linux environments stored on {fs!r}.")
    if mode == "wsl":
        # The boot hook has to have mounted the Windows checkout first; without
        # that the agent would be shown an empty directory instead of the user's
        # files, and its writes would go nowhere the user can open.
        if not os.path.ismount(windows):
            raise RuntimeError(
                f"{windows} is not mounted. Restart the OSINT AI terminal."
            )
        require_checkout(
            windows, "Re-run the Windows installer, or pull the checkout in your Windows Git app."
        )
    else:
        require_checkout(project, "Clone the project with `git clone` instead of copying a folder.")


def prepare_state(state):
    """Create the agent home and make it private.

    It holds ``~/.pi/agent/auth.json``: provider API keys and OAuth tokens.
    ``mkdir`` inherits the umask, which on a shared PC leaves the directory group-
    and world-readable, so 0700 is enforced on every launch rather than only on
    the first one - a home created by an older version is repaired instead of
    staying open. Both deployments go through here; the Windows installer does not
    pre-create it any more.
    """
    home = state / "agent-home"
    home.mkdir(parents=True, exist_ok=True)
    for directory in (home, state):
        os.chmod(directory, 0o700)
    return home


def build_command(
    project,
    state,
    *,
    mode="native",
    windows=None,
    bwrap=None,
    pi_args=(),
    command=None,
):
    """Pure argv construction apart from validating protected mount points.

    ``project`` is the checkout that owns ``pixi.toml`` and ``.pixi``: the only
    checkout in ``native`` mode, and the Linux program checkout in ``wsl`` mode.
    ``windows`` is the Windows checkout in ``wsl`` mode. Without ``command`` the
    sandbox starts the Pi entry script; tests and diagnostics may pass an
    explicit argv instead. Without ``bwrap`` the pinned bubblewrap of that
    checkout's environment runs the sandbox.
    """
    bwrap = bwrap_path(project) if bwrap is None else str(bwrap)
    home = state / "agent-home"
    agent_source = Path(windows) if mode == "wsl" else project
    # Defence in depth: a symlinked source would silently bind elsewhere.
    require_directory(project)
    require_directory(agent_source)
    require_directory(agent_source / WORKSPACE_SUBDIR)
    require_directory(home)
    # The environment the agent runs on comes from the program checkout, which
    # is read-only in WSL and re-bound read-only in plain Linux.
    env_prefix = (PROGRAM_MOUNT if mode == "wsl" else AGENT_MOUNT) / ".pixi" / "envs" / ENV_NAME
    args = [
        str(bwrap),
        "--unshare-all",
        "--share-net",
        "--die-with-parent",
        "--new-session",
        "--cap-drop",
        "ALL",
        "--clearenv",
    ]
    # No root bind: in particular /mnt, /init, /run, /root and host homes never
    # enter the sandbox. Do not forward WSL/SSH/DBus integration sockets.
    for path in ("/usr", "/bin", "/sbin", "/lib", "/lib64"):
        if Path(path).exists():
            args += ["--ro-bind", path, path]
    args += [
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--tmpfs",
        "/run",
        "--dir",
        "/etc",
        "--dir",
        "/home",
    ]
    for path in (
        "/etc/resolv.conf",
        "/etc/hosts",
        "/etc/nsswitch.conf",
        "/etc/alternatives",
        "/etc/ssl/certs",
        "/etc/ld.so.cache",
        "/etc/localtime",
        "/etc/passwd",
        "/etc/group",
    ):
        if Path(path).exists():
            args += ["--ro-bind", path, path]
    # The checkout the agent works in is mounted whole and read-write, `.git`
    # included, at /osint-ai in both modes. Git needs the repository above the
    # working directory, so the workspace is never mounted on its own.
    args += ["--bind", str(agent_source), str(AGENT_MOUNT)]
    if mode == "wsl":
        # The Linux checkout is the program: read-only, so nothing the agent
        # writes can change what runs next.
        args += ["--ro-bind", str(project), str(PROGRAM_MOUNT)]
    else:
        # The project root is writable here, and it holds the Pixi environment
        # the assistant runs on. Re-bind `.pixi` read-only on top of it, so the
        # tools it uses still cannot be installed or replaced from inside.
        environment_dir = project / ".pixi"
        if environment_dir.is_dir():
            args += ["--ro-bind", str(environment_dir), str(AGENT_MOUNT / ".pixi")]
    args += [
        "--bind",
        str(home),
        "/home/osint",
    ]
    # Mounted after the home, so each one shadows whatever the persistent home
    # happens to hold at that path. Sources are host paths: the sandbox path of
    # the environment does not exist until bubblewrap creates it.
    bundled_home = project / BUNDLED_HOME_SUBPATH
    for relative, target in PI_HOME_BINDS:
        if (bundled_home / relative).is_file():
            args += ["--ro-bind", str(bundled_home / relative), target]
    args += [
        # Mounted after the home, so it shadows only the intercom subdirectory.
        "--tmpfs",
        INTERCOM_DIR,
    ]
    if mode == "wsl":
        # The Linux checkout's own history stays out of reach: the agent works
        # in the Windows checkout, so that repository is not its business.
        git = project / ".git"
        if git.exists() or git.is_symlink():
            require_directory(git)  # Linked worktrees are deliberately unsupported.
            args += [
                "--tmpfs",
                str(PROGRAM_MOUNT / ".git"),
                "--remount-ro",
                str(PROGRAM_MOUNT / ".git"),
            ]
    # Installed copies are authoritative when present; a plain Linux checkout
    # only has its own (developer-editable) copy.
    installed = Path("/usr/local/lib/osint-ai/pi-entry.sh")
    program_mount = PROGRAM_MOUNT if mode == "wsl" else AGENT_MOUNT
    entry = installed if installed.is_file() else program_mount / "scripts/pi-entry.sh"
    inference = inference_url(mode)
    env = {
        "HOME": "/home/osint",
        "USER": "osint",
        "LOGNAME": "osint",
        "PATH": f"{env_prefix / 'bin'}:/usr/local/bin:/usr/bin:/bin",
        "CONDA_PREFIX": str(env_prefix),
        "SHELL": "/bin/bash",
        "LANG": "C.UTF-8",
        "TERM": os.environ.get("TERM", "xterm-256color"),
        "PIXI_HOME": "/home/osint/.pixi",
        "PIXI_CACHE_DIR": "/home/osint/.cache/pixi",
        "XDG_CACHE_HOME": "/home/osint/.cache",
        "XDG_CONFIG_HOME": "/home/osint/.config",
        # The assistant's only local model server. `LLAMA_BASE_URL` is what Pi's
        # built-in llama.cpp provider reads; `OSINT_INFERENCE_URL` names the same
        # server for the generated models.json. In WSL both point at the Windows
        # host, where llama.cpp runs natively, and never at loopback.
        "LLAMA_BASE_URL": inference,
        "OSINT_INFERENCE_URL": inference,
        # Git needs an author identity, and this home has no ~/.gitconfig: the
        # Windows user's identity lives on the Windows side and is not mounted
        # here. Without it `git commit` - which `workspace/AGENTS.md` allows and
        # docs/security.md says the tests assert - fails with "Author identity
        # unknown". The fixed name also tells the person reviewing in GitHub
        # Desktop which commits the assistant wrote. `.invalid` is a reserved
        # domain that can never receive mail.
        "GIT_AUTHOR_NAME": GIT_IDENTITY_NAME,
        "GIT_AUTHOR_EMAIL": GIT_IDENTITY_EMAIL,
        "GIT_COMMITTER_NAME": GIT_IDENTITY_NAME,
        "GIT_COMMITTER_EMAIL": GIT_IDENTITY_EMAIL,
        "OSINT_SANDBOX": "1",
        "OSINT_MODE": mode,
        # The checkout the agent works in, its workspace inside it, and the
        # skills directory inside that. Same values in both modes.
        "OSINT_CHECKOUT": str(AGENT_MOUNT),
        "OSINT_WORKSPACE": str(WORKSPACE_MOUNT),
        "OSINT_SKILLS_DIR": str(SKILLS_MOUNT),
        # The model shortlist, as the sandbox path of the program checkout's copy:
        # `/opt/osint-ai/project/...` in WSL, `/osint-ai/...` on plain Linux. Not
        # `OSINT_CHECKOUT`: in WSL that is the Windows checkout the agent writes.
        "OSINT_MODEL_SHORTLIST": str(program_mount / MODEL_SHORTLIST_NAME),
        # Do not pass user prompt strings through a shell.
        "OSINT_PI_ARGS": base64.b64encode(json.dumps(list(pi_args)).encode()).decode(),
        "PI_SKIP_VERSION_CHECK": "1",
        "PI_TELEMETRY": "0",
    }
    for key in ("COLORTERM", "WT_SESSION"):
        if key in os.environ:
            env[key] = os.environ[key]
    for key, value in env.items():
        args += ["--setenv", key, value]
    inner = [str(part) for part in command] if command else ["/bin/bash", str(entry)]
    return args + ["--chdir", str(WORKSPACE_MOUNT), "--", *inner]


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="osint-pi",
        description=(
            "Start the sandboxed OSINT AI assistant. It works in the `workspace` "
            f"directory of its checkout, mounted at {AGENT_MOUNT}."
        ),
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--native",
        action="store_true",
        help="Use the workspace directory of the project root (plain Linux).",
    )
    target.add_argument(
        "--wsl",
        action="store_true",
        help=f"Use the workspace directory of the Windows checkout (default {WINDOWS_HOST_MOUNT}).",
    )
    parser.add_argument(
        "--root",
        type=Path,
        help="Project root containing pixi.toml and .pixi. In WSL this is the Linux checkout.",
    )
    parser.add_argument(
        "--windows",
        type=Path,
        help=f"WSL only: host path of the Windows checkout (default {WINDOWS_HOST_MOUNT}).",
    )
    parser.add_argument("--state", type=Path, help="Linux directory for persistent agent state.")
    parser.add_argument(
        "--inference-url",
        action="store_true",
        help=(
            "Print the local inference address for this deployment and exit. Used by the "
            "installer and the installation check to probe it from inside WSL."
        ),
    )
    known, pi_args = parser.parse_known_args(argv)
    mode = "wsl" if known.wsl else "native"
    # A developer normally starts the task from inside their own checkout, so
    # the current directory is the native default. WSL always uses Linux storage.
    fallback = os.environ.get("OSINT_PROJECT_ROOT") or (
        str(Path.cwd()) if mode == "native" else str(DEFAULT_PROJECT_ROOT)
    )
    return {
        "mode": mode,
        "project": known.root or Path(fallback),
        "windows": known.windows or WINDOWS_HOST_MOUNT,
        "state": known.state or default_state(),
        "inference_url": known.inference_url,
        "pi_args": pi_args,
    }


def main(argv=None):
    if os.geteuid() == 0:
        raise RuntimeError("Run the assistant as the normal user, not root.")
    options = parse_args(sys.argv[1:] if argv is None else argv)
    # A diagnostic, not a launch: it resolves the same address the sandbox then
    # hands to Pi, and it must work before any checkout or environment exists.
    if options["inference_url"]:
        print(inference_url(options["mode"]))
        return
    # Both deployments keep their state in the Linux user's own directory, so the
    # launcher prepares it the same way everywhere. In WSL that user is `osint`,
    # which owns /home/osint; the launcher never runs as root.
    prepare_state(options["state"])
    check_storage(options["mode"], options["project"], options["windows"], options["state"])
    argv = build_command(
        options["project"],
        options["state"],
        mode=options["mode"],
        windows=options["windows"],
        pi_args=options["pi_args"],
    )
    os.execv(argv[0], argv)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        sys.exit(f"OSINT AI: {error}\nThe sandbox was not bypassed.")
