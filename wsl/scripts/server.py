#!/usr/bin/python3
"""User-level llama.cpp server lifecycle; never executes the editable project manifest.

The bundled CUDA build also runs on machines without an NVIDIA GPU: device
detection then selects CPU inference instead of failing, so the desktop
shortcut works on every supported PC.
"""

import fcntl
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

RUNTIME = Path("/opt/osint-ai/server/.pixi/envs/llamacpp-binary-cuda")
STATE = Path("/var/lib/osint-ai/server-state")
MODELS = Path("/var/lib/osint-ai/models")
PRESETS = Path("/opt/osint-ai/server/models.ini")
HOST = "127.0.0.1"
PORT = 8080
GPU_DEVICE = Path("/dev/dxg")
STARTUP_TIMEOUT = 120
# Keep a CUDA build on system memory when no CUDA device is present.
CPU_ONLY_ARGS = ["--n-gpu-layers", "0"]


def process_identity(pid):
    try:
        # comm may contain spaces and parentheses. starttime is field 22.
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return fields[19] if fields[0] != "Z" else None
    except (FileNotFoundError, ProcessLookupError):
        return None


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
            f"http://{HOST}:{PORT}/health", timeout=2
        ) as response:
            data = json.load(response)
            return response.status == 200 and isinstance(data, dict) and data.get("status") == "ok"
    except (OSError, URLError, ValueError):
        return False


def stop(record, pidfile):
    if owned_process(record):
        pid = record["pid"]
        # A dedicated session/process group includes router model subprocesses.
        if os.getpgid(pid) != pid:
            raise RuntimeError(
                "Server process group changed; refusing to kill unrelated processes."
            )
        os.killpg(pid, signal.SIGTERM)
        for _ in range(100):
            if not owned_process(record):
                break
            time.sleep(0.1)
        if owned_process(record):
            os.killpg(pid, signal.SIGKILL)
    pidfile.unlink(missing_ok=True)


def detect_backend(executable, env):
    """Return (backend, extra arguments). CPU-only PCs are fully supported."""
    if not GPU_DEVICE.exists():
        return "cpu", CPU_ONLY_ARGS
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
        r"(?m)^\s*CUDA\d+:", devices.stdout + devices.stderr
    ):
        return "cuda", []
    return "cpu", CPU_ONLY_ARGS


def main(action):
    if os.geteuid() == 0:
        raise RuntimeError("Run the inference server as the normal user, not root.")
    if os.environ.get("OSINT_SANDBOX"):
        raise RuntimeError("Run start-server/restart-server in the terminal, outside Pi.")
    if not STATE.is_dir():
        raise RuntimeError("Trusted server installation is missing. Run the Windows installer.")
    with (STATE / "control.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        pidfile = STATE / "server.json"
        record = json.loads(pidfile.read_text()) if pidfile.exists() else {}
        if action == "stop":
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
                print("Local inference is already running. Use /models inside Pi.")
                return
        # Never mistake an arbitrary HTTP listener for our inference server.
        with socket.socket() as probe:
            # Permit immediate restart despite TCP TIME_WAIT, like llama-server.
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((HOST, PORT))
            except OSError as error:
                raise RuntimeError("Port 8080 is in use by another process.") from error
        executable = RUNTIME / "bin/llama-server"
        if not executable.is_file():
            raise RuntimeError("Inference runtime is missing. Complete the installation.")
        env = {
            "HOME": "/home/osint",
            "LANG": "C.UTF-8",
            "PATH": f"{RUNTIME}/bin:/usr/bin:/bin",
            "LD_LIBRARY_PATH": f"{RUNTIME}/lib:/usr/lib/wsl/lib",
            "XDG_CACHE_HOME": str(MODELS),
            "LLAMA_CACHE": str(MODELS / "llama.cpp"),
        }
        backend, backend_args = detect_backend(executable, env)
        logfile = STATE / "llama-server.log"
        if backend == "cuda":
            print("CUDA device detected. Starting local inference on the GPU.", flush=True)
        else:
            print(
                "No usable CUDA device. Starting local inference on the CPU, which is much "
                "slower. Install a supported NVIDIA Windows driver to use the GPU.",
                flush=True,
            )
        print(f"Local inference server log: {logfile}", flush=True)
        with logfile.open("ab", buffering=0) as log:
            # The controller is single-threaded. fork/exec detaches the server
            # without a Popen object or platform-specific posix_spawn flags.
            command = [
                str(executable),
                "--models-preset",
                str(PRESETS),
                "--models-max",
                "1",
                "--no-models-autoload",
                "--host",
                HOST,
                "--port",
                str(PORT),
                # Appended last so it overrides any GPU-layer preset.
                *backend_args,
            ]
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
        record = {"pid": pid, "start": process_identity(pid), "backend": backend}
        try:
            pidfile.write_text(json.dumps(record))
            deadline = time.monotonic() + STARTUP_TIMEOUT
            while time.monotonic() < deadline:
                child, status = os.waitpid(pid, os.WNOHANG)
                if child:
                    code = os.waitstatus_to_exitcode(status)
                    raise RuntimeError(f"Server exited ({code}). See {logfile}.")
                if healthy():
                    print("Ready. Run osint-pi, then /models. Weights download only when loaded.")
                    return
                time.sleep(0.25)
            raise RuntimeError(f"Server startup timed out. See {logfile}.")
        except BaseException:
            stop(record, pidfile)
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
            raise


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in {"start", "stop", "restart"}:
            raise RuntimeError("Usage: start-server | stop-server | restart-server")
        main(sys.argv[1])
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        sys.exit(f"OSINT AI: {error}")
