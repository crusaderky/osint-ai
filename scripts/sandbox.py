#!/usr/bin/python3
"""Build the agent's allowlisted mount namespace before Pixi reads the project.

This installed file is root-owned. Never import Python modules from the checkout.
All project activation hooks, build backends and extensions execute inside bwrap.
"""

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT = Path("/workspace")
STATE = Path("/var/lib/osint-ai")


def require_directory(path):
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError(f"Expected a real directory, not a symlink: {path}")


def check_storage(project, state):
    require_directory(project)
    require_directory(project / ".pixi")
    require_directory(state / "pixi")
    if not os.path.samefile(project / ".pixi", state / "pixi"):
        raise RuntimeError("Linux .pixi mount is missing. Restart the OSINT AI WSL terminal.")
    fs = subprocess.check_output(
        ["/usr/bin/findmnt", "-n", "-o", "FSTYPE", "-T", str(project / ".pixi")],
        text=True,
    ).strip()
    if fs not in {"ext4", "xfs", "btrfs"}:
        raise RuntimeError(f"Refusing to install Linux environments on {fs!r}.")


def build_command(project, state, command, *, bwrap="/usr/bin/bwrap", pi_args=()):
    """Pure argv construction apart from validating protected mount points."""
    home = state / "agent-home"
    require_directory(home)
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
    # No root bind: in particular, /mnt, /init, /run, /root and host homes
    # never enter the sandbox. Do not forward WSL/SSH/DBus integration sockets.
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
    args += [
        "--bind",
        str(project),
        "/workspace",
        "--bind",
        str(state / "pixi"),
        "/workspace/.pixi",
        "--bind",
        str(home),
        "/home/osint",
    ]
    # Prevent changing the Windows Git index, hooks, config, or remote.
    git = project / ".git"
    if git.exists() or git.is_symlink():
        require_directory(git)  # Linked worktrees are deliberately unsupported.
        args += ["--tmpfs", "/workspace/.git", "--remount-ro", "/workspace/.git"]
    # Root-owned installed copies are authoritative, but also protect their
    # tracked originals against accidental edits during ordinary skill work.
    for name in ("scripts", "pixi-recipes", "Install.ps1", "Install.cmd"):
        path = project / name
        if path.is_symlink():
            raise RuntimeError(f"Protected path must not be a symlink: {path}")
        if path.exists():
            args += ["--ro-bind", str(path), f"/workspace/{name}"]
    env = {
        "HOME": "/home/osint",
        "USER": "osint",
        "LOGNAME": "osint",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "SHELL": "/bin/bash",
        "LANG": "C.UTF-8",
        "TERM": os.environ.get("TERM", "xterm-256color"),
        "PIXI_HOME": "/home/osint/.pixi",
        "PIXI_CACHE_DIR": "/home/osint/.cache/pixi",
        "XDG_CACHE_HOME": "/home/osint/.cache",
        "XDG_CONFIG_HOME": "/home/osint/.config",
        "LLAMA_SERVER_URL": "http://127.0.0.1:8080",
        "OSINT_SANDBOX": "1",
        # Do not pass user prompt strings through Pixi's task shell parser.
        "OSINT_PI_ARGS": base64.b64encode(json.dumps(list(pi_args)).encode()).decode(),
        "PI_SKIP_VERSION_CHECK": "1",
        "PI_TELEMETRY": "0",
    }
    for key in ("COLORTERM", "WT_SESSION"):
        if key in os.environ:
            env[key] = os.environ[key]
    for key, value in env.items():
        args += ["--setenv", key, value]
    return args + ["--chdir", "/workspace", "--"] + list(command)


def main():
    if os.geteuid() == 0:
        raise RuntimeError("Run osint-pi as the normal WSL user, not root.")
    check_storage(PROJECT, STATE)
    command = [
        "/usr/local/bin/pixi",
        "run",
        "--manifest-path",
        "/workspace/pixi.toml",
        "-e",
        "agents",
        "/usr/local/lib/osint-ai/pi-entry.sh",
    ]
    argv = build_command(PROJECT, STATE, command, pi_args=sys.argv[1:])
    os.execv(argv[0], argv)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        sys.exit(f"OSINT AI: {error}\nSandbox was not bypassed.")
