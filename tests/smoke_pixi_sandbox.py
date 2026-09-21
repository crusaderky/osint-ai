#!/usr/bin/env python3
"""Optional Linux integration: install the real environment and run Pi sandboxed.

Downloads packages into temporary Linux storage; no Windows or root changes.
Run explicitly: python3 tests/smoke_pixi_sandbox.py
"""

import base64
import importlib.util
import json
import os
import selectors
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("sandbox", ROOT / "wsl/scripts/sandbox.py")
sandbox = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sandbox)


def rpc_command(process, payload, timeout=90):
    process.stdin.write((json.dumps(payload) + "\n").encode())
    process.stdin.flush()
    deadline = time.monotonic() + timeout
    buffer = b""
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while time.monotonic() < deadline:
            for key, _ in selector.select(timeout=1):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    raise RuntimeError("Pi exited before responding")
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if line.startswith(b"{"):
                        event = json.loads(line)
                        if event.get("type") == "extension_error":
                            raise RuntimeError(event)
                        if event.get("id") == payload["id"]:
                            return event
    raise RuntimeError("timed out waiting for Pi")


def main():
    pixi = shutil.which("pixi")
    if not pixi:
        raise SystemExit("Install Pixi first.")
    logpath = Path(tempfile.gettempdir()) / "osint-pixi-sandbox-smoke.log"
    with tempfile.TemporaryDirectory(prefix="osint-pixi-smoke-") as directory:
        root = Path(directory)
        project = root / "linux checkout"
        shutil.copytree(
            ROOT,
            project,
            ignore=shutil.ignore_patterns(".pixi", ".git", "__pycache__", ".ruff_cache", "*.log"),
        )
        workspace = project / "workspace"
        skill = workspace / ".agents/skills/smoke-test"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: smoke-test\ndescription: Packaging smoke test skill for CI only.\n---\n"
            "Test only.\n"
        )
        state = root / "state"
        (state / "agent-home").mkdir(parents=True)

        print("Installing the locked 'agents' environment into the copy (this downloads)...")
        subprocess.run(
            [pixi, "install", "--locked", "-e", "agents", "--manifest-path", str(project / "pixi.toml")],
            check=True,
        )

        args = sandbox.build_command(
            project, workspace, state, mode="native", pi_args=["--version"]
        )
        with logpath.open("w") as log:
            result = subprocess.run(args, stdout=log, stderr=subprocess.STDOUT, check=False)
        if result.returncode:
            raise SystemExit(f"Sandbox Pi startup failed ({result.returncode}). Log: {logpath}")
        assert (state / "agent-home/.pi/agent/settings.json").is_file(), "Pi home was not prepared"

        # RPC is used only by this test: it exercises real extension loading and
        # explicit .agents/skills discovery without calling a model.
        index = args.index("OSINT_PI_ARGS") + 1
        args[index] = base64.b64encode(
            json.dumps(["--mode", "rpc", "--no-session"]).encode()
        ).decode()
        with (
            logpath.open("a") as log,
            subprocess.Popen(
                args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log
            ) as process,
        ):
            try:
                response = rpc_command(process, {"type": "get_commands", "id": "smoke"})
                assert response.get("success"), f"No command response; see {logpath}"
                names = {entry["name"] for entry in response["data"]["commands"]}
                assert "models" in names, f"pi-llama-cpp did not load: {sorted(names)}"
                assert "skill:smoke-test" in names, f"skill not discovered: {sorted(names)}"
                assert "skill:markdown-pdf" in names and "skill:spreadsheet-reader" in names
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        print(
            "Real environment, Pi startup inside bubblewrap, /models registration and "
            f".agents/skills discovery: OK. Log: {logpath}"
        )


if __name__ == "__main__":
    main()
