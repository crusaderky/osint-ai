#!/usr/bin/python3 -I
"""Root-owned WSL boot hook. No shell evaluation or code from the checkout."""

import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path, PureWindowsPath

CONFIG = Path("/etc/osint-ai.json")
PROJECT = Path("/workspace")
STATE = Path("/var/lib/osint-ai")


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


def mount_windows_project(windows_path):
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
            target_fd = directory_fd(PROJECT)
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
    if PROJECT.is_symlink() or (PROJECT / ".pixi").is_symlink():
        raise RuntimeError("Workspace and .pixi must be real directories.")
    if not os.path.ismount(PROJECT):
        raise RuntimeError("Windows workspace is not mounted; restart the OSINT AI terminal.")
    if not (PROJECT / ".pixi").exists() or not os.path.samefile(PROJECT / ".pixi", STATE / "pixi"):
        raise RuntimeError("Linux .pixi mount is missing; restart the OSINT AI terminal.")


def mount():
    if os.geteuid() != 0:
        raise RuntimeError("Mount setup is performed by the WSL boot hook, not by the agent.")
    config = json.loads(CONFIG.read_text())
    windows_path = config["windows_project"]
    windows_parts(windows_path)
    PROJECT.mkdir(exist_ok=True)
    if PROJECT.is_symlink():
        raise RuntimeError("Workspace mount point is a symlink.")
    if not os.path.ismount(PROJECT):
        mount_windows_project(windows_path)
    target = PROJECT / ".pixi"
    target.mkdir(exist_ok=True)
    source_fd = directory_fd(STATE / "pixi")
    try:
        target_fd = directory_fd(target)
        try:
            if not os.path.samestat(os.fstat(source_fd), os.fstat(target_fd)):
                bind_fds(source_fd, target_fd)
        finally:
            os.close(target_fd)
    finally:
        os.close(source_fd)
    restrict = Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns")
    if restrict.exists() and restrict.read_text().strip() == "1":
        run("/usr/sbin/apparmor_parser", "-r", "/etc/apparmor.d/bwrap")
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
