#!/usr/bin/python3
"""Build the agent's allowlisted mount namespace, then start Pi inside it.

Two deployment modes share this file.

``native``
    Plain Linux. The project root holds Git, ``pixi.toml`` and ``.pixi``. The
    functional workspace is ``<project root>/workspace``.

``wsl``
    Windows deployment. The same repository is checked out twice:

    * a Linux checkout (default ``/home/osint/osint-ai``) owns the manifest and
      the Pixi environments, and is what executes;
    * a Windows checkout (mounted by the boot helper at ``/mnt/osint-ai``)
      holds the files the user edits and commits.

    The agent works in the Windows checkout, which is bound read-write with its
    ``.git``, while the Linux checkout stays read-only at
    ``/opt/osint-ai/project`` so the program that starts Pi cannot be changed
    from inside a session. In plain Linux there is only one checkout, so the
    project root is the writable one.

Nothing the sandboxed agent can write is executed outside the sandbox; the
read-only ``.pixi`` environment supplies the Pi binary and the command-line
tools available to skills. The agent can read its checkout's whole Git history
and, because ``.git`` is writable, could commit, switch branches or discard
work. ``AGENTS.md`` and ``docs/security.md`` state that, and the user reviews
every diff in the Windows GUI.
"""

import argparse
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_MOUNT = Path("/opt/osint-ai/project")
WORKSPACE_MOUNT = Path("/workspace")
WINDOWS_MOUNT = Path("/mnt/osint-ai")
DEFAULT_PROJECT_ROOT = Path("/home/osint/osint-ai")
DEFAULT_STATE = Path("/var/lib/osint-ai")
ENV_NAME = "default"
LINUX_FILESYSTEMS = {"ext4", "xfs", "btrfs"}
# pi-intercom keeps its broker socket, PID file, spawn lock and queued mail in
# ~/.pi/agent/intercom. The agent home is persistent and writable, so without a
# private mount that runtime state would outlive the session: a second terminal
# window would unlink the live broker's socket on startup, and mail queued for a
# closed session could be redelivered to a later one. A fresh tmpfs per sandbox
# gives every launch its own broker, keeps the socket out of the persistent home,
# and still lets a parent session talk to its sub-agent children, which share
# this namespace. Nothing outside the sandbox can reach the socket.
INTERCOM_DIR = "/home/osint/.pi/agent/intercom"


def require_directory(path, hint=""):
    if path.is_symlink():
        raise RuntimeError(f"Expected a real directory, not a symlink: {path}{hint}")
    if not path.is_dir():
        raise RuntimeError(f"Expected a real directory, found nothing usable: {path}{hint}")


def filesystem(path):
    return subprocess.check_output(
        ["/usr/bin/findmnt", "-n", "-o", "FSTYPE", "-T", str(path)],
        text=True,
    ).strip()


def default_state(mode):
    """Persistent, writable, Linux-native application state."""
    if mode == "wsl":
        return DEFAULT_STATE
    override = os.environ.get("OSINT_STATE_DIR")
    if override:
        return Path(override)
    return Path.home() / ".local" / "state" / "osint-ai"


def default_workspace(mode, project):
    return (WINDOWS_MOUNT / "workspace") if mode == "wsl" else project / "workspace"


def check_storage(mode, project, workspace, state):
    require_directory(project, " (the project root; choose another with --root)")
    require_directory(
        workspace,
        " (the working directory; choose another with --workspace, or start the "
        "OSINT AI terminal so the Windows checkout is mounted)",
    )
    require_directory(state / "agent-home", " (restart the OSINT AI terminal)")
    if not (project / ".pixi" / "envs" / ENV_NAME / "bin" / "pi").is_file():
        raise RuntimeError(
            f"The '{ENV_NAME}' environment is not installed in {project}. "
            "Run: pixi install --locked -e "
            + ENV_NAME
        )
    # Pixi environments must never live on a Windows filesystem.
    fs = filesystem(project / ".pixi")
    if fs not in LINUX_FILESYSTEMS:
        raise RuntimeError(f"Refusing to use Linux environments stored on {fs!r}.")
    if mode == "wsl":
        if not os.path.ismount(WINDOWS_MOUNT):
            raise RuntimeError(
                f"{WINDOWS_MOUNT} is not mounted. Restart the OSINT AI terminal."
            )
        if workspace != WINDOWS_MOUNT / "workspace":
            raise RuntimeError(f"In WSL mode the workspace must be {WINDOWS_MOUNT}/workspace.")
        # The agent works in this checkout and runs its own Git, so the
        # repository has to be really there.
        checkout_git = WINDOWS_MOUNT / ".git"
        if checkout_git.is_symlink() or not checkout_git.is_dir():
            raise RuntimeError(
                f"{WINDOWS_MOUNT} is not a Git checkout ({checkout_git} is missing). "
                "Re-run the Windows installer."
            )
    if os.path.realpath(workspace) == os.path.realpath(project):
        raise RuntimeError("The workspace must be a subdirectory, not the project root.")


def build_command(
    project,
    workspace,
    state,
    *,
    mode="native",
    bwrap="/usr/bin/bwrap",
    pi_args=(),
    command=None,
):
    """Pure argv construction apart from validating protected mount points.

    Without ``command`` the sandbox starts the Pi entry script; tests and
    diagnostics may pass an explicit argv instead.
    """
    home = state / "agent-home"
    # Defence in depth: a symlinked source would silently bind elsewhere.
    require_directory(project)
    require_directory(workspace)
    require_directory(home)
    env_prefix = PROJECT_MOUNT / ".pixi" / "envs" / ENV_NAME
    args = [
        bwrap,
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
        "/etc/ssl/certs",
        "/etc/ld.so.cache",
        "/etc/localtime",
        "/etc/passwd",
        "/etc/group",
    ):
        if Path(path).exists():
            args += ["--ro-bind", path, path]
    # The checkout the agent works in is bound read-write, including its `.git`,
    # so the assistant can run `git status` itself and the user reviews real
    # changes. In WSL that is the Windows checkout, at the same path the boot
    # helper mounted it; the Linux checkout that starts Pi stays read-only
    # there. In plain Linux there is only one checkout, so the project root is
    # both the program and the work, and it is writable.
    if mode == "wsl":
        args += ["--ro-bind", str(project), str(PROJECT_MOUNT)]
        args += ["--bind", str(WINDOWS_MOUNT), str(WINDOWS_MOUNT)]
    else:
        args += ["--bind", str(project), str(PROJECT_MOUNT)]
        # The project root is writable here, and it holds the Pixi environment
        # the assistant runs on. Re-bind `.pixi` read-only on top of it, so the
        # tools it uses still cannot be installed or replaced from inside.
        environment_dir = project / ".pixi"
        if environment_dir.is_dir():
            args += ["--ro-bind", str(environment_dir), str(PROJECT_MOUNT / ".pixi")]
    args += [
        "--bind",
        str(workspace),
        str(WORKSPACE_MOUNT),
        "--bind",
        str(home),
        "/home/osint",
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
                str(PROJECT_MOUNT / ".git"),
                "--remount-ro",
                str(PROJECT_MOUNT / ".git"),
            ]
    # Installed copies are authoritative when present; a plain Linux checkout
    # only has its own (developer-editable) copy.
    installed = Path("/usr/local/lib/osint-ai/pi-entry.sh")
    entry = installed if installed.is_file() else PROJECT_MOUNT / "wsl/scripts/pi-entry.sh"
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
        "LLAMA_SERVER_URL": "http://127.0.0.1:8080",
        "OSINT_SANDBOX": "1",
        "OSINT_MODE": mode,
        "OSINT_PROJECT_ROOT": str(PROJECT_MOUNT),
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
        prog="osint-pi", description="Start the sandboxed OSINT AI assistant."
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--native", action="store_true", help="Use <project root>/workspace (plain Linux)."
    )
    target.add_argument(
        "--wsl", action="store_true", help=f"Use {WINDOWS_MOUNT}/workspace (Windows checkout)."
    )
    parser.add_argument("--root", type=Path, help="Project root containing pixi.toml and .pixi.")
    parser.add_argument("--workspace", type=Path, help="Directory exposed read-write as /workspace.")
    parser.add_argument("--state", type=Path, help="Linux directory for persistent agent state.")
    known, pi_args = parser.parse_known_args(argv)
    mode = "wsl" if known.wsl else "native"
    # A developer normally starts the task from inside their own checkout, so
    # the current directory is the native default. WSL always uses Linux storage.
    fallback = os.environ.get("OSINT_PROJECT_ROOT") or (
        str(Path.cwd()) if mode == "native" else str(DEFAULT_PROJECT_ROOT)
    )
    project = known.root or Path(fallback)
    return {
        "mode": mode,
        "project": project,
        "workspace": known.workspace or default_workspace(mode, project),
        "state": known.state or default_state(mode),
        "pi_args": pi_args,
    }


def main(argv=None):
    if os.geteuid() == 0:
        raise RuntimeError("Run the assistant as the normal user, not root.")
    options = parse_args(sys.argv[1:] if argv is None else argv)
    if options["mode"] == "native":
        # A plain Linux checkout creates its own private state on first use. In
        # WSL the state belongs to root-owned provisioning and is never created
        # by the launcher.
        (options["state"] / "agent-home").mkdir(parents=True, exist_ok=True)
    check_storage(options["mode"], options["project"], options["workspace"], options["state"])
    argv = build_command(
        options["project"],
        options["workspace"],
        options["state"],
        mode=options["mode"],
        pi_args=options["pi_args"],
    )
    os.execv(argv[0], argv)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        sys.exit(f"OSINT AI: {error}\nThe sandbox was not bypassed.")
