#!/usr/bin/python3
"""User-level llama.cpp server lifecycle, started by a human in a terminal.

Local inference is optional and lives in its own Pixi environment
(`.pixi/envs/llamacpp-binary-vulkan`). On Linux that environment is inside the
project root checkout; on the Windows deployment it is inside the Windows
checkout, because llama.cpp runs natively there, outside WSL, where it reaches
the GPU directly. The server listens on port 8080 in router mode with the model
presets in `models.ini`, which is what the assistant's model list talks to.

The bundled Vulkan build also runs on machines without a usable Vulkan device:
device detection then selects CPU inference instead of failing, so the desktop
shortcut works on every supported PC.
"""

import contextlib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

RUNTIME_ENV = "llamacpp-binary-vulkan"
RUNTIME_SUBPATH = Path(".pixi") / "envs" / RUNTIME_ENV
# Written by windows/provision-wsl.sh: which checkout owns the runtime. Patched in
# tests, so the resolution is testable without a WSL distribution.
PROJECT_CONFIG = Path("/etc/osint-ai.json")
# The WSL deployment pre-creates this and owns it; a plain Linux checkout has no
# such directory and keeps its inference state in the user's own state directory,
# exactly where the assistant keeps its sign-in and sessions.
SYSTEM_STATE = Path("/var/lib/osint-ai")
STATE_SUBPATH = Path(".local") / "state" / "osint-ai"
# Windows: `%LOCALAPPDATA%\\osint-ai` is what the Windows installer creates and
# owns, next to the pixi binary and the portable MobaXterm it downloaded.
WINDOWS_STATE_SUBPATH = Path("osint-ai")
# Used only when run from neither a checkout nor an installed WSL distribution.
DEFAULT_PROJECT_ROOT = Path("/home/osint/osint-ai")
# The Windows deployment serves the assistant inside WSL, which is a different
# network namespace: it has to listen beyond loopback, and the Windows installer
# adds a firewall rule that admits only the WSL interface's local subnet.
HOST = "0.0.0.0" if os.name == "nt" else "127.0.0.1"
# The controller always talks to the server over loopback, wherever it listened.
LOOPBACK = "127.0.0.1"
PORT = 8080
STARTUP_TIMEOUT = 120
# Keep the Vulkan build on system memory when no Vulkan device answers.
CPU_ONLY_ARGS = ["--n-gpu-layers", "0"]
WINDOWS = os.name == "nt"


def project_root():
    """The checkout whose Pixi environments hold the inference runtime.

    Pixi names it in `PIXI_PROJECT_ROOT` when a task started this controller, and
    the installed WSL copy reads it from `/etc/osint-ai.json`. On the Windows
    deployment it is the Windows checkout the desktop shortcut names, never the
    Linux checkout inside WSL: llama.cpp runs on Windows and never in the private
    distribution.
    """
    override = os.environ.get("PIXI_PROJECT_ROOT")
    if override:
        return Path(override)
    config = PROJECT_CONFIG
    if config.is_file():
        try:
            return Path(json.loads(config.read_text())["linux_project"])
        except (OSError, ValueError, KeyError) as error:
            raise RuntimeError(f"Cannot read the installed project root from {config}: {error}")
    here = Path(__file__).resolve().parent
    if (here.parent / "pixi.toml").is_file():
        return here.parent
    if WINDOWS:
        raise RuntimeError(
            "Cannot tell which checkout holds local inference. Start it from the desktop "
            "shortcut the OSINT AI installer created, which names the checkout explicitly."
        )
    return DEFAULT_PROJECT_ROOT


def state_root():
    """Where the server keeps its pid file and log; weights are not here."""
    override = os.environ.get("OSINT_INFERENCE_STATE")
    if override:
        return Path(override)
    if WINDOWS:
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            raise RuntimeError("LOCALAPPDATA is not set; start inference from the desktop shortcut.")
        return Path(local) / WINDOWS_STATE_SUBPATH
    if SYSTEM_STATE.is_dir() and os.access(SYSTEM_STATE, os.W_OK):
        return SYSTEM_STATE
    override = os.environ.get("OSINT_STATE_DIR")
    return Path(override) if override else Path.home() / STATE_SUBPATH


ROOT = project_root()
RUNTIME = ROOT / RUNTIME_SUBPATH
SERVER_NAME = "llama-server.exe" if WINDOWS else "llama-server"
PRESETS = ROOT / "models.ini"
STATE_ROOT = state_root()
STATE = STATE_ROOT / "server-state"
# Weights are not under the state directory, and the child environment below is
# scrubbed: it passes HOME (USERPROFILE on Windows) and nothing that could
# redirect a cache, so `llama-server --hf-repo` resolves its own default - the
# standard Hugging Face cache, `~/.cache/huggingface/hub` (see
# `common/hf-cache.cpp`: LLAMA_CACHE, HF_HUB_CACHE, HUGGINGFACE_HUB_CACHE, HF_HOME
# and XDG_CACHE_HOME are all absent). That keeps the state directory - pid file
# and log - small, and lets another Hugging Face tool on the same PC share the
# weights instead of downloading a second copy. Pinning the path here instead
# would be a second copy of llama.cpp's own default to keep in step.


def server_binary():
    """The llama.cpp server of the inference environment of this checkout."""
    return RUNTIME / "bin" / SERVER_NAME


def process_identity(pid):
    """A value that is unique per process run, so a reused pid is not ours."""
    if WINDOWS:
        return windows_process_identity(pid)
    try:
        # comm may contain spaces and parentheses. starttime is field 22.
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return fields[19] if fields[0] != "Z" else None
    except (FileNotFoundError, ProcessLookupError):
        return None


def windows_process_identity(pid):
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return None
    try:
        creation = wintypes.FILETIME()
        exited = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        ok = kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        )
        if not ok:
            return None
        # 100 ns ticks since 1601, the Windows analogue of /proc's starttime.
        return (creation.dwHighDateTime << 32) | creation.dwLowDateTime
    finally:
        kernel32.CloseHandle(handle)


def owned_process(record):
    return (
        isinstance(record.get("pid"), int)
        and record["pid"] > 1
        and record.get("start") is not None
        and process_identity(record["pid"]) == record["start"]
    )


def healthy():
    try:
        with build_opener(ProxyHandler({})).open(
            f"http://{LOOPBACK}:{PORT}/health", timeout=2
        ) as response:
            data = json.load(response)
            return response.status == 200 and isinstance(data, dict) and data.get("status") == "ok"
    except (OSError, URLError, ValueError):
        return False


def terminate(record):
    """Stop the server this pid file describes, and nothing else."""
    pid = record["pid"]
    if WINDOWS:
        # /T takes the router's own children with it if it ever has any.
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
            timeout=30,
        )
    else:
        # A dedicated session/process group includes router model subprocesses.
        if os.getpgid(pid) != pid:
            raise RuntimeError(
                "Server process group changed; refusing to kill unrelated processes."
            )
        os.killpg(pid, signal.SIGTERM)
    for _ in range(100):
        if not owned_process(record):
            return
        time.sleep(0.1)
    if owned_process(record) and not WINDOWS:
        os.killpg(pid, signal.SIGKILL)


def stop(record, pidfile):
    if owned_process(record):
        terminate(record)
    pidfile.unlink(missing_ok=True)


@contextlib.contextmanager
def control_lock(path):
    """Serialize starts and stops; fcntl on POSIX, msvcrt on Windows."""
    with path.open("a") as handle:
        if WINDOWS:
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if WINDOWS:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def detect_backend(executable, env):
    """Return (backend, extra arguments). CPU-only PCs are fully supported.

    The question is asked of the binary itself, so a real Vulkan device is found
    however it is reached, and the same build on a PC without one starts on the
    CPU with GPU offloading disabled.
    """
    devices = subprocess.run(
        [str(executable), "--list-devices"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=STATE,
        check=False,
    )
    if not devices.returncode and re.search(
        r"(?m)^\s*Vulkan\d+:", devices.stdout + devices.stderr
    ):
        return "vulkan", []
    return "cpu", CPU_ONLY_ARGS


def prepare_state():
    """Create the inference state directories and make them private (0700).

    `mkdir` inherits the umask, which on a shared PC leaves a group- and
    world-readable directory, so the mode is enforced on every start. The model
    cache is not created here: it is llama.cpp's own default under the user's
    home, shared with any other tool that downloads from Hugging Face, and it
    must not become a second, private copy.
    """
    for directory in (STATE_ROOT, STATE):
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o700)


def child_environment():
    """The child's environment: HOME alone, plus what Windows itself needs.

    Windows does not inherit HOME from the Linux side, and `common/hf-cache.cpp`
    reads USERPROFILE there, so both are passed by name and nothing that could
    redirect the model cache is passed at all.
    """
    if WINDOWS:
        system_root = os.environ.get("SystemRoot") or r"C:\Windows"
        return {
            "USERPROFILE": os.environ.get("USERPROFILE") or str(Path.home()),
            "SystemRoot": system_root,
            "PATH": f"{RUNTIME / 'bin'};{system_root}\\System32;{system_root}",
        }
    library_path = [f"{RUNTIME}/lib"]
    if Path("/usr/lib/wsl/lib").is_dir():
        # The WSL driver libraries (libvulkan and friends) live here.
        library_path.append("/usr/lib/wsl/lib")
    return {
        "HOME": os.environ.get("HOME") or str(Path.home()),
        "LANG": "C.UTF-8",
        "PATH": f"{RUNTIME}/bin:/usr/bin:/bin",
        "LD_LIBRARY_PATH": ":".join(library_path),
    }


def child_status(pid, process):
    """None while the child runs, else its exit code."""
    if process is not None:
        return process.poll()
    child, status = os.waitpid(pid, os.WNOHANG)
    return os.waitstatus_to_exitcode(status) if child else None


def reap(pid, process):
    if process is None:
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
    else:
        process.wait(timeout=30)


def spawn(command, env, log):
    """Start the server detached from this controller; return (pid, handle).

    On POSIX the controller forks: that detaches the server without a Popen
    object or platform-specific posix_spawn flags. Windows has no fork, so there
    the child is a detached process group.
    """
    if WINDOWS:
        process = subprocess.Popen(
            command,
            env=env,
            cwd=STATE,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            close_fds=True,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
        )
        return process.pid, process
    pid = os.fork()
    if pid == 0:
        try:
            os.setsid()
            os.chdir(STATE)
            with open(os.devnull, "rb") as null:
                os.dup2(null.fileno(), 0)
            os.dup2(log.fileno(), 1)
            os.dup2(log.fileno(), 2)
            os.execve(command[0], command, env)
        except BaseException as error:
            os.write(2, f"Cannot launch inference: {error}\n".encode())
            os._exit(127)
    return pid, None


def main(action):
    if not WINDOWS and os.geteuid() == 0:
        raise RuntimeError("Run the inference server as the normal user, not root.")
    if os.environ.get("OSINT_SANDBOX"):
        raise RuntimeError("Run start-server/restart-server in the terminal, outside Pi.")
    # Stopping never needs the inference program, and it must not install it:
    # `stop-server` is the one command that should work on a PC without it.
    if action == "stop" and not STATE.is_dir():
        print("Local inference is not running.")
        return
    if action != "stop":
        server = server_binary()
        if not server.is_file():
            raise RuntimeError(
                f"Local inference is not installed: {server} is missing, and it is optional. "
                f"`pixi r start-server` runs in the {RUNTIME_ENV} environment, which Pixi "
                f"installs; if this controller was started some other way, run "
                f"'pixi install --locked -e {RUNTIME_ENV}' in {ROOT}. Or sign in to a hosted "
                "model with /login and leave local inference out."
            )
        if not PRESETS.is_file():
            raise RuntimeError(f"Model presets are missing: {PRESETS}")
    prepare_state()
    with control_lock(STATE / "control.lock"):
        pidfile = STATE / "server.json"
        record = json.loads(pidfile.read_text()) if pidfile.exists() else {}
        if action == "stop":
            if not owned_process(record):
                pidfile.unlink(missing_ok=True)
                print("Local inference is not running.")
                return
            stop(record, pidfile)
            print("Local inference stopped.")
            return
        if owned_process(record):
            if action == "restart":
                stop(record, pidfile)
                record = {}
            elif not healthy():
                raise RuntimeError("Existing server is not healthy. Run stop-server and retry.")
            else:
                print("Local inference is already running. Pick a model in the assistant.")
                return
        # Never mistake an arbitrary HTTP listener for our inference server.
        with socket.socket() as probe:
            # Permit immediate restart despite TCP TIME_WAIT, like llama-server.
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((HOST, PORT))
            except OSError as error:
                raise RuntimeError(f"Port {PORT} is in use by another process.") from error
        env = child_environment()
        backend, backend_args = detect_backend(server, env)
        logfile = STATE / "llama-server.log"
        if backend == "vulkan":
            print("Vulkan device detected. Starting local inference on the GPU.", flush=True)
        else:
            print(
                "No usable Vulkan device. Starting local inference on the CPU, which is much "
                "slower. Install a GPU driver with Vulkan support to use the GPU.",
                flush=True,
            )
        print(f"Local inference server log: {logfile}", flush=True)
        with logfile.open("ab", buffering=0) as log:
            command = [
                str(server),
                "--models-preset",
                str(PRESETS),
                "--models-max",
                "1",
                # Nothing loads at startup, and a request naming a model loads it
                # and downloads its weights if they are not cached yet.
                "--models-autoload",
                "--host",
                HOST,
                "--port",
                str(PORT),
                # Appended last so it overrides any GPU-layer preset.
                *backend_args,
            ]
            pid, process = spawn(command, env, log)
        record = {"pid": pid, "start": process_identity(pid), "backend": backend}
        try:
            pidfile.write_text(json.dumps(record))
            deadline = time.monotonic() + STARTUP_TIMEOUT
            while time.monotonic() < deadline:
                code = child_status(pid, process)
                if code is not None:
                    raise RuntimeError(f"Server exited ({code}). See {logfile}.")
                if healthy():
                    print(
                        f"Ready: local inference listens on {HOST}:{PORT}. Weights download "
                        "the first time a model is used, which can take a while.",
                    )
                    if WINDOWS:
                        print(
                            "Start the assistant from the OSINT AI Terminal icon and pick a "
                            "model with /model.",
                        )
                    return
                time.sleep(0.25)
            raise RuntimeError(f"Server startup timed out. See {logfile}.")
        except BaseException:
            stop(record, pidfile)
            reap(pid, process)
            raise


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in {"start", "stop", "restart"}:
            raise RuntimeError("Usage: start-server | stop-server | restart-server")
        main(sys.argv[1])
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        sys.exit(f"OSINT AI: {error}")
