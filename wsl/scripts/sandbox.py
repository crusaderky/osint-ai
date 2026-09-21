#!/usr/bin/python3
"""Build the agent's allowlisted mount namespace, then start Pi inside it.

Two deployment modes share this file.

``native``
    Plain Linux. The project root holds Git, ``pixi.toml`` and ``.pixi``. The
    functional workspace is ``<project root>/workspace``.

``wsl``
    Windows deployment. The same repository is checked out twice:

    * a Linux checkout (default ``/home/osint/osint-ai``) owns Git, the
      manifest and Pixi environments, and is what executes;
    * a Windows checkout (mounted by the boot helper at ``/mnt/osint-ai``)
      supplies only its ``workspace/`` directory to the agent.

    So Pi runs with its working directory inside the Windows deployment, while
    the code that launched it stays in Linux storage. The agent can neither see
    nor modify the project root: it is a *different* Git checkout, and edits to
    its root files have no effect here.

The namespace is built before Pi starts. Nothing the sandboxed agent can write
is ever executed outside it; the read-only ``.pixi`` environment supplies the
Pi binary and the command-line tools available to skills.
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
ENV_NAME = "agents"
LINUX_FILESYSTEMS = {"ext4", "xfs", "btrfs"}


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
    if os.path.realpath(workspace) == os.path.realpath(project):
        raise RuntimeError("The workspace must be a subdirectory, not the project root.")


def git_status_snapshot(project, destination):
    """Write a read-only Git summary the agent can use to remind the user.

    Git belongs to the human's Windows GUI, so the sandbox never sees a Git
    directory or credentials. This trusted launcher-side inspection reads only
    the repository's own status: hooks, fsmonitors, system and global Git
    configuration are disabled, and no lock file is written.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    git = Path("/usr/bin/git")
    if not git.is_file():
        git = Path("/bin/git")
    lines = []
    try:
        if git.is_file() and (project / ".git").is_dir():
            result = subprocess.run(
                [
                    str(git),
                    "--no-optional-locks",
                    "-c",
                    f"safe.directory={project}",
                    "-c",
                    "core.fsmonitor=false",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-c",
                    "core.autocrlf=false",
                    "-C",
                    str(project),
                    "status",
                    "--porcelain=v1",
                    "-b",
                    "--untracked-files=normal",
                ],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
                env={"GIT_CONFIG_NOSYSTEM": "1", "HOME": "/nonexistent", "PATH": "/usr/bin:/bin"},
            )
            if result.returncode == 0:
                lines = result.stdout.splitlines()
            else:
                lines = ['git status failed: ' + (result.stderr or "").strip()[:200]]
        else:
            lines = ["No Git repository is available on this installation."]
    except (OSError, subprocess.SubprocessError) as error:
        lines = [f"git status unavailable: {error}"]
    header = (
        f"Git status of the user's checkout ({project}). Read-only information for "
        "reminding the user; never run Git yourself."
    )
    temporary = destination.with_suffix(".tmp")
    temporary.write_text("\n".join([header, *lines]) + "\n")
    temporary.chmod(0o600)
    temporary.replace(destination)


def build_command(
    project,
    workspace,
    state,
    *,
    mode="native",
    bwrap="/usr/bin/bwrap",
    pi_args=(),
    git_status=None,
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
    # The project root is the code that starts Pi. It stays read-only, so a
    # sandboxed agent can never change what runs next or escape into Git.
    args += ["--ro-bind", str(project), str(PROJECT_MOUNT)]
    args += [
        "--bind",
        str(workspace),
        str(WORKSPACE_MOUNT),
        "--bind",
        str(home),
        "/home/osint",
    ]
    if git_status is not None and Path(git_status).is_file():
        # Launcher-produced read-only summary used only for user reminders.
        args += ["--ro-bind", str(git_status), "/run/git-status"]
    git = project / ".git"
    if git.exists() or git.is_symlink():
        require_directory(git)  # Linked worktrees are deliberately unsupported.
        args += ["--tmpfs", str(PROJECT_MOUNT / ".git"), "--remount-ro", str(PROJECT_MOUNT / ".git")]
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
        # In WSL the user edits and commits the Windows checkout, so reminders
        # describe that checkout rather than the Linux one that executes.
        "status_repo": WINDOWS_MOUNT if mode == "wsl" else project,
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
    status = options["state"] / "git-status"
    try:
        git_status_snapshot(options["status_repo"], status)
    except OSError as error:  # Reminders are optional; starting Pi is not.
        print(f"OSINT AI: Git status unavailable ({error}).", file=sys.stderr)
        status = None
    argv = build_command(
        options["project"],
        options["workspace"],
        options["state"],
        mode=options["mode"],
        pi_args=options["pi_args"],
        git_status=status,
    )
    os.execv(argv[0], argv)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        sys.exit(f"OSINT AI: {error}\nThe sandbox was not bypassed.")
