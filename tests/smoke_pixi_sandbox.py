#!/usr/bin/env python3
"""Optional Linux integration: install and launch real Pi inside the sandbox.

Downloads packages into temporary Linux storage; no Windows/root changes.
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
spec = importlib.util.spec_from_file_location("sandbox", ROOT / "scripts/sandbox.py")
sandbox = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sandbox)


def main():
    pixi = shutil.which("pixi")
    if not pixi:
        raise SystemExit("Install Pixi first.")
    logpath = Path(tempfile.gettempdir()) / "osint-pixi-sandbox-smoke.log"
    with tempfile.TemporaryDirectory(prefix="osint-pixi-smoke-") as directory:
        root = Path(directory)
        project = root / "checkout"
        shutil.copytree(
            ROOT,
            project,
            ignore=shutil.ignore_patterns(".pixi", ".git", "__pycache__", ".ruff_cache", "*.log"),
        )
        (project / ".git").mkdir()
        (project / ".pixi").mkdir()
        skill = project / "agents/smoke-test"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: smoke-test\ndescription: Packaging smoke test.\n---\nTest only.\n"
        )
        state = root / "state"
        (state / "pixi").mkdir(parents=True)
        (state / "agent-home").mkdir()
        command = [
            "/usr/local/bin/pixi",
            "run",
            "--manifest-path",
            "/workspace/pixi.toml",
            "-e",
            "agents",
            "/usr/local/lib/osint-ai/pi-entry.sh",
        ]
        args = sandbox.build_command(project, state, command, pi_args=["--version"])
        # Emulate root-owned installation within the namespace only.
        index = args.index("--chdir")
        args[index:index] = [
            "--tmpfs",
            "/usr/local",
            "--ro-bind",
            str(Path(pixi).resolve()),
            "/usr/local/bin/pixi",
            "--ro-bind",
            str(ROOT / "scripts"),
            "/usr/local/lib/osint-ai",
        ]
        with logpath.open("w") as log:
            result = subprocess.run(args, stdout=log, stderr=subprocess.STDOUT, check=False)
        if result.returncode:
            raise SystemExit(f"Sandbox Pi startup failed ({result.returncode}). Log: {logpath}")
        assert (state / "agent-home/.pi/agent/settings.json").is_file()
        assert not list((project / ".pixi").iterdir()), "Pixi wrote through to Windows storage"
        # RPC is used only by this test, not as a replacement UI/harness.
        # It exercises actual extension loading and explicit agents/ discovery.
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
                process.stdin.write(b'{"type":"get_commands","id":"smoke"}\n')
                process.stdin.flush()
                buffer = b""
                response = None
                deadline = time.monotonic() + 45
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    while time.monotonic() < deadline and response is None:
                        for key, _ in selector.select(timeout=1):
                            chunk = os.read(key.fileobj.fileno(), 65536)
                            if not chunk:
                                raise RuntimeError(f"Pi exited before RPC response; see {logpath}")
                            buffer += chunk
                            while b"\n" in buffer:
                                line, buffer = buffer.split(b"\n", 1)
                                if not line.startswith(b"{"):
                                    continue
                                event = json.loads(line)
                                if event.get("type") == "extension_error":
                                    raise RuntimeError(event)
                                if event.get("id") == "smoke":
                                    response = event
                assert response and response.get("success"), f"No command response; see {logpath}"
                names = {entry["name"] for entry in response["data"]["commands"]}
                assert "models" in names, f"pi-llama-cpp did not load: {names}"
                assert "skill:smoke-test" in names, f"agents/ skill not discovered: {names}"
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        print(
            f"Real Pixi install, Pi startup, /models registration and agents/ discovery: OK. Log: {logpath}"
        )


if __name__ == "__main__":
    main()
