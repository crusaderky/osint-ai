#!/usr/bin/python3 -I
"""Root-owned WSL boot hook. No shell evaluation or code from the checkout.

Mounts the *Windows* checkout of this repository at ``/mnt/osint-ai`` so that
``osint-pi-wsl`` can mount it whole, ``workspace/`` and ``.git`` included, at
``/osint-ai`` inside the sandbox. The Linux checkout that owns Git, Pixi and
this program lives in Linux storage and is never touched here.
"""

import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path, PureWindowsPath

CONFIG = Path("/etc/osint-ai.json")
WINDOWS_TARGET = Path("/mnt/osint-ai")


def run(*args):
    subprocess.run(args, check=True)


def directory_fd(path):
    # Pin the directory inode and refuse symlinks, including replacement races.
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)


def windows_parts(value):
    if not isinstance(value, str) or any(char in value for char in "\r\n\0"):
        raise RuntimeError("Invalid Windows project path.")
    path = PureWindowsPath(value)
    if (
        not path.is_absolute()
        or not re.fullmatch(r"[A-Za-z]:", path.drive)
        or len(path.parts) < 2
        or ".." in path.parts
    ):
        raise RuntimeError("Expected a local Windows folder, not a drive root or UNC path.")
    return path.drive, path.parts[1:]


def bind_fds(source_fd, target_fd):
    # mount(8) must not resolve these stable FDs back to mutable pathnames.
    subprocess.run(
        [
            "/usr/bin/mount",
            "--no-canonicalize",
            "--bind",
            f"/proc/self/fd/{source_fd}",
            f"/proc/self/fd/{target_fd}",
        ],
        check=True,
        pass_fds=(source_fd, target_fd),
    )


def mount_windows_checkout(windows_path):
    drive, parts = windows_parts(windows_path)
    # DrvFS mounts drive roots, not reliably arbitrary subdirectories. Keep the
    # temporary whole-drive mount under a root-only directory, then discard it.
    temporary = Path(tempfile.mkdtemp(prefix="osint-drive-", dir="/run"))
    drive_root = temporary / "drive"
    drive_root.mkdir()
    try:
        run(
            "/usr/bin/mount",
            "-t",
            "drvfs",
            "-o",
            "uid=1000,gid=1000,umask=022",
            drive,
            str(drive_root),
        )
        source_fd = directory_fd(drive_root)
        try:
            for part in parts:
                next_fd = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=source_fd
                )
                os.close(source_fd)
                source_fd = next_fd
            target_fd = directory_fd(WINDOWS_TARGET)
            try:
                bind_fds(source_fd, target_fd)
            finally:
                os.close(target_fd)
        finally:
            os.close(source_fd)
    finally:
        if os.path.ismount(drive_root):
            run("/usr/bin/umount", str(drive_root))
        # NEVER recursively delete a path that might still contain a drive mount.
        drive_root.rmdir()
        temporary.rmdir()


def check():
    if WINDOWS_TARGET.is_symlink():
        raise RuntimeError(f"{WINDOWS_TARGET} must be a real directory.")
    if not os.path.ismount(WINDOWS_TARGET):
        raise RuntimeError("Windows checkout is not mounted; restart the OSINT AI terminal.")
    workspace = WINDOWS_TARGET / "workspace"
    if workspace.is_symlink() or not workspace.is_dir():
        raise RuntimeError(f"{workspace} is missing. Update the checkout in your Windows Git app.")


def mount():
    if os.geteuid() != 0:
        raise RuntimeError("Mount setup is performed by the WSL boot hook, not by the agent.")
    config = json.loads(CONFIG.read_text())
    windows_parts(config["windows_project"])
    if WINDOWS_TARGET.is_symlink():
        raise RuntimeError(f"{WINDOWS_TARGET} is a symlink.")
    WINDOWS_TARGET.mkdir(parents=True, exist_ok=True)
    if not os.path.ismount(WINDOWS_TARGET):
        mount_windows_checkout(config["windows_project"])
    workspace = WINDOWS_TARGET / "workspace"
    if not workspace.is_dir():
        # An outdated checkout must not prevent the assistant from starting.
        workspace.mkdir()
    check()


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["--check"]:
            check()
        elif not sys.argv[1:]:
            # Serialize the WSL boot hook and an installer retry.
            with open("/run/osint-ai-mount.lock", "a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                mount()
        else:
            raise RuntimeError("Usage: mount-workspace.py [--check]")
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(f"OSINT AI mount setup failed: {error}")
