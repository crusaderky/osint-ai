#!/usr/bin/python3
"""Run the llama.cpp server in the foreground, in the terminal that started it.

Local inference is optional and lives in its own Pixi environment
(`.pixi/envs/llamacpp-binary-vulkan`). On Linux that environment is inside the
project root checkout; on the Windows deployment it is inside the Windows
checkout, because llama.cpp runs natively there, outside WSL, where it reaches
the GPU directly. The server listens on port 8080 in router mode with the model
presets in `models.ini`, which is what the assistant's model list talks to.

There is no service here: no pid file, no log file, no start/stop/restart. The
server's stdout and stderr are the terminal's own, so the user watches it load a
model, and stopping it is closing that window. On plain Linux that means a second
terminal window next to the assistant's; on Windows it means the **Start
llama.cpp** window stays open for as long as local models are available.

The bundled Vulkan build also runs on machines without a usable Vulkan device:
device detection then selects CPU inference instead of failing, so the same
command works on every supported PC.
"""

import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

RUNTIME_ENV = "llamacpp-binary-vulkan"
RUNTIME_SUBPATH = Path(".pixi") / "envs" / RUNTIME_ENV
# Written by windows/provision-wsl.sh: which checkout owns the runtime. Patched in
# tests, so the resolution is testable without a WSL distribution.
PROJECT_CONFIG = Path("/etc/osint-ai.json")
# Used only when run from neither a checkout nor an installed WSL distribution.
DEFAULT_PROJECT_ROOT = Path("/home/osint/osint-ai")
# The Windows deployment serves the assistant inside WSL, which is a different
# network namespace: it has to listen beyond loopback, and the Windows installer
# adds a firewall rule that admits only the WSL interface's local subnet.
HOST = "0.0.0.0" if os.name == "nt" else "127.0.0.1"
PORT = 8080
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


ROOT = project_root()
RUNTIME = ROOT / RUNTIME_SUBPATH
SERVER_NAME = "llama-server.exe" if WINDOWS else "llama-server"
PRESETS = ROOT / "models.ini"
# Model weights are nowhere near the checkout: `child_environment()` below passes
# HOME (USERPROFILE on Windows) and nothing that could redirect a cache, so
# `llama-server --hf-repo` resolves its own default - the standard Hugging Face
# cache, `~/.cache/huggingface/hub` (see `common/hf-cache.cpp`: LLAMA_CACHE,
# HF_HUB_CACHE, HUGGINGFACE_HUB_CACHE, HF_HOME and XDG_CACHE_HOME are all absent).
# That lets another Hugging Face tool on the same PC share the weights instead of
# downloading a second copy. Pinning the path here would be a second copy of
# llama.cpp's own default to keep in step.


def server_binary():
    """The llama.cpp server of the inference environment of this checkout."""
    return RUNTIME / "bin" / SERVER_NAME


def refuse_other_listener():
    """Never mistake an arbitrary HTTP listener for our inference server.

    With a foreground server there is no pid file to ask, so the port itself is
    the question: a clear refusal beats llama.cpp failing to bind a moment later.
    """
    with socket.socket() as probe:
        # Permit immediate reuse despite TCP TIME_WAIT, like llama-server does.
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((HOST, PORT))
        except OSError as error:
            raise RuntimeError(
                f"Port {PORT} is in use. Local inference is probably already running in "
                "another window; close that window first."
            ) from error


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
        check=False,
    )
    if not devices.returncode and re.search(
        r"(?m)^\s*Vulkan\d+:", devices.stdout + devices.stderr
    ):
        return "vulkan", []
    return "cpu", CPU_ONLY_ARGS


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


def command_line(backend_args):
    """The llama.cpp command line: router mode, nothing loaded at startup."""
    return [
        str(server_binary()),
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


def serve(command, env):
    """Hand this terminal to the server and return when it stops.

    On POSIX this replaces the current process, so the terminal's foreground
    process *is* llama.cpp: its output is the window's output, Ctrl-C reaches it
    directly, and its exit code is what the shell sees. Windows has no exec, so
    there the child is started attached to this console - which is exactly what
    makes closing the window stop it - and Ctrl-C is forwarded to it.
    """
    if WINDOWS:
        child = subprocess.Popen(command, env=env)
        try:
            return child.wait()
        except KeyboardInterrupt:
            child.terminate()
            try:
                return child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                child.kill()
                return child.wait()
    os.execve(command[0], command, env)


def main():
    if not WINDOWS and os.geteuid() == 0:
        raise RuntimeError("Run the inference server as the normal user, not root.")
    if os.environ.get("OSINT_SANDBOX"):
        raise RuntimeError("Run llama.cpp in its own terminal window, outside Pi.")
    server = server_binary()
    if not server.is_file():
        raise RuntimeError(
            f"Local inference is not installed: {server} is missing, and it is optional. "
            f"`pixi r llamacpp` runs in the {RUNTIME_ENV} environment, which Pixi "
            f"installs; if this runner was started some other way, run "
            f"'pixi install --locked -e {RUNTIME_ENV}' in {ROOT}. Or sign in to a hosted "
            "model with /login and leave local inference out."
        )
    if not PRESETS.is_file():
        raise RuntimeError(f"Model presets are missing: {PRESETS}")
    refuse_other_listener()
    env = child_environment()
    backend, backend_args = detect_backend(server, env)
    if backend == "vulkan":
        print("Vulkan device detected. Local inference will use the GPU.", flush=True)
    else:
        print(
            "No usable Vulkan device. Local inference will use the CPU, which is much "
            "slower. Install a GPU driver with Vulkan support to use the GPU.",
            flush=True,
        )
    # Named after what the user actually has in front of them: a console window on
    # Windows, a terminal window on Linux. It is the server now, so it has to stay.
    where = "window" if WINDOWS else "terminal"
    print(
        f"Serving on {HOST}:{PORT}. Keep this {where} open: the assistant uses local "
        "models only while it runs.",
        flush=True,
    )
    print(
        "Weights download the first time a model is used, which can take a while.",
        flush=True,
    )
    print(f"Ctrl-C, or closing this {where}, stops the server.", flush=True)
    if WINDOWS:
        print(
            "Start the assistant from the OSINT AI Terminal icon and pick a model with /model.",
            flush=True,
        )
    return serve(command_line(backend_args), env)


if __name__ == "__main__":
    if len(sys.argv) != 1:
        # Model settings live in models.ini; this runner has no options of its own.
        sys.exit("OSINT AI: llama.cpp takes no arguments. Edit models.ini to change models.")
    try:
        code = main()
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        sys.exit(f"OSINT AI: {error}")
    sys.exit(code)
