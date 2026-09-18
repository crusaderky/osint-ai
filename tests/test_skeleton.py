import base64
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import tempfile
import textwrap
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sandbox = load_module("sandbox")
server = load_module("server")
mounts = load_module("mount-workspace")


class ConfigurationTests(unittest.TestCase):
    def test_manifest(self):
        data = tomllib.loads((ROOT / "pixi.toml").read_text())
        self.assertEqual(data["workspace"]["platforms"][0]["platform"], "linux-64")
        self.assertEqual(data["feature"]["pi"]["dependencies"]["pi-coding-agent"], "=0.85.1")
        self.assertEqual(data["environments"]["agents"], ["pi"])
        self.assertTrue(data["environments"]["llamacpp-binary-cuda"]["no-default-feature"])
        self.assertIn("python", data["dependencies"])

    def test_skill_discovery_and_guidance(self):
        settings = json.loads((ROOT / "pixi-recipes/pi-home/settings.json").read_text())
        self.assertEqual(settings["skills"], ["/workspace/agents"])
        self.assertEqual(settings["llamaSettings"]["servers"][0]["url"], "http://127.0.0.1:8080")
        for file in ("AGENTS.md", "pixi-recipes/pi-home/AGENTS.md"):
            self.assertIn("/workspace/agents/<skill-name>/SKILL.md", (ROOT / file).read_text())
        self.assertIn(
            "exec pi --skill /workspace/agents", (ROOT / "scripts/pi-entry.sh").read_text()
        )

    def test_shell_syntax(self):
        for file in [*ROOT.rglob("*.sh"), *(ROOT / "scripts/install").iterdir()]:
            if ".pixi" not in file.parts:
                with self.subTest(file=file):
                    subprocess.run(["/bin/bash", "-n", str(file)], check=True)

    def test_windows_bootstrap_is_non_destructive(self):
        script = (ROOT / "Install.ps1").read_text()
        self.assertNotIn("--unregister", script)
        self.assertNotIn("reset --hard", script)
        self.assertNotIn("git pull", script)
        self.assertIn("--no-distribution", script)
        self.assertIn("Get-FileHash", script)
        self.assertIn("Restart Windows", script)
        self.assertIn("ConvertTo-ShellLiteral", script)


class MountTests(unittest.TestCase):
    def test_windows_path_validation(self):
        self.assertEqual(
            mounts.windows_parts(r"C:\Users\O'Brien\My Skills"),
            ("C:", ("Users", "O'Brien", "My Skills")),
        )
        for value in ("C:\\", r"C:relative", r"\\server\share", r"C:\a\..\b", "C:\\a\nb", None):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                mounts.windows_parts(value)

    def test_fd_mount_does_not_recanonicalize(self):
        with patch.object(mounts.subprocess, "run") as run:
            mounts.bind_fds(4, 5)
        self.assertEqual(
            run.call_args.args[0],
            ["/usr/bin/mount", "--no-canonicalize", "--bind", "/proc/self/fd/4", "/proc/self/fd/5"],
        )
        self.assertEqual(run.call_args.kwargs["pass_fds"], (4, 5))

    def test_drive_is_temporary_and_only_subdirectory_is_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            temporary = root / "private"
            temporary.mkdir(mode=0o700)
            project = root / "workspace"
            project.mkdir()
            calls = []
            mounted = False

            def run(*args):
                nonlocal mounted
                calls.append(args)
                if args[0] == "/usr/bin/mount":
                    self.assertEqual(args[-2], "C:")
                    (temporary / "drive/Users/Alice/Skills").mkdir(parents=True)
                    mounted = True
                elif args[0] == "/usr/bin/umount":
                    # Simulate unmount revealing the original empty directory.
                    shutil.rmtree(temporary / "drive/Users")
                    mounted = False

            def bind(source_fd, target_fd):
                self.assertEqual(
                    os.fstat(source_fd).st_ino,
                    (temporary / "drive/Users/Alice/Skills").stat().st_ino,
                )
                self.assertEqual(os.fstat(target_fd).st_ino, project.stat().st_ino)

            with (
                patch.object(mounts, "PROJECT", project),
                patch.object(mounts.tempfile, "mkdtemp", return_value=str(temporary)),
                patch.object(mounts, "run", side_effect=run),
                patch.object(mounts, "bind_fds", side_effect=bind) as bind_mock,
                patch.object(mounts.os.path, "ismount", side_effect=lambda _: mounted),
            ):
                mounts.mount_windows_project(r"C:\Users\Alice\Skills")
            bind_mock.assert_called_once()
            self.assertEqual(calls[-1][0], "/usr/bin/umount")
            self.assertFalse(temporary.exists())


class PiEntryTests(unittest.TestCase):
    def test_arguments_stdin_and_user_settings_survive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            live = home / ".pi/agent"
            live.mkdir(parents=True)
            (live / "settings.json").write_text('{"defaultProvider":"openrouter"}')
            (live / "auth.json").write_text('{"preserve":"user login"}')
            prefix = root / "prefix"
            bundled = prefix / "home/.pi/agent"
            (bundled / "npm").mkdir(parents=True)
            for name in ("settings.json", "osint-defaults.json", "keybindings.json"):
                (bundled / name).write_text("{}")
            (bundled / "AGENTS.md").write_text("use /workspace/agents")
            (bundled.parent / "web-search.json").write_text("{}")
            bindir = root / "bin"
            bindir.mkdir()
            fake = bindir / "pi"
            fake.write_text(
                "#!/usr/bin/python3\nimport json,sys\nprint(json.dumps([sys.argv[1:],sys.stdin.read()]))\n"
            )
            fake.chmod(0o755)
            prompts = [
                "apostrophe's",
                "spaces and $HOME; $(exit 7)",
                "",
                "line1\nline2",
                "Unicode: café",
            ]
            env = dict(
                os.environ,
                HOME=str(home),
                CONDA_PREFIX=str(prefix),
                PATH=str(bindir) + ":/usr/bin:/bin",
                OSINT_SANDBOX="1",
                OSINT_PI_ARGS=base64.b64encode(json.dumps(prompts).encode()).decode(),
            )
            result = subprocess.run(
                ["/bin/bash", str(ROOT / "scripts/pi-entry.sh")],
                input="terminal input",
                capture_output=True,
                text=True,
                env=env,
                check=True,
            )
            args, stdin = json.loads(result.stdout)
            self.assertEqual(args, ["--skill", "/workspace/agents", *prompts])
            self.assertEqual(stdin, "terminal input")
            self.assertEqual(
                json.loads((live / "settings.json").read_text())["defaultProvider"], "openrouter"
            )
            self.assertEqual(
                json.loads((live / "auth.json").read_text()), {"preserve": "user login"}
            )


class SandboxFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="osint test ' spaces ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "windows checkout"
        self.state = self.root / "linux state"
        self.project.mkdir()
        self.state.mkdir()
        for name in (".git", ".pixi", "agents", "scripts", "pixi-recipes"):
            (self.project / name).mkdir()
        for name in ("agent-home", "pixi"):
            (self.state / name).mkdir()
        (self.project / ".git/config").write_text("private git configuration")
        (self.project / "scripts/protected").write_text("original")
        (self.project / "AGENTS.md").write_text("project instructions")
        (self.project / "pixi.toml").write_text("project manifest")
        self.secret = self.root / "host-secret"
        self.secret.write_text("not accessible")

    def argv(self, command):
        return sandbox.build_command(self.project, self.state, command)

    def test_argv_and_environment_allowlist(self):
        with patch.dict(os.environ, {"WSL_INTEROP": "/run/socket", "OPENAI_API_KEY": "secret"}):
            args = self.argv(["/bin/printf", "%s", "a'b $HOME; literal argument"])
        self.assertEqual(args[-1], "a'b $HOME; literal argument")
        self.assertIn("--clearenv", args)
        self.assertIn("--share-net", args)
        self.assertNotIn("WSL_INTEROP", args)
        self.assertNotIn("OPENAI_API_KEY", args)
        self.assertNotIn("secret", args)
        self.assertNotIn("/", args)
        self.assertNotIn("--dev-bind", args)
        self.assertIn(str(self.project), args)
        self.assertIn(str(self.state / "pixi"), args)

    def test_unmounted_storage_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "mount is missing"):
            sandbox.check_storage(self.project, self.state)

    def test_protected_symlink_rejected(self):
        shutil.rmtree(self.project / "scripts")
        (self.project / "scripts").symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "symlink"):
            self.argv(["/bin/true"])

    def test_worktree_git_file_rejected(self):
        shutil.rmtree(self.project / ".git")
        (self.project / ".git").write_text("gitdir: /elsewhere")
        with self.assertRaisesRegex(RuntimeError, "real directory"):
            self.argv(["/bin/true"])

    def test_mount_helper_rejects_symlink(self):
        link = self.root / "link"
        link.symlink_to(self.state / "pixi", target_is_directory=True)
        with self.assertRaises(OSError):
            mounts.directory_fd(link)

    def require_bwrap(self):
        if not Path("/usr/bin/bwrap").exists():
            self.skipTest("system bubblewrap is not installed")
        probe = subprocess.run(
            self.argv(["/bin/true"]), capture_output=True, text=True, check=False
        )
        if probe.returncode:
            self.skipTest("unprivileged bubblewrap unavailable: " + probe.stderr.strip())

    def test_real_filesystem_boundary(self):
        self.require_bwrap()
        code = textwrap.dedent("""
            import os
            from pathlib import Path
            import sys
            assert not Path(sys.argv[1]).exists(), 'host secret exposed'
            assert not Path('/mnt/c').exists()
            assert not Path('/init').exists()
            assert not Path('/dev/dxg').exists()
            assert list(Path('/run').iterdir()) == []
            assert not Path('/workspace/.git/config').exists()
            assert not os.environ.get('AWS_SECRET_ACCESS_KEY')
            for p in ['/workspace/.git/config', '/workspace/scripts/protected', '/etc/hosts']:
                try:
                    Path(p).write_text('should fail')
                except OSError:
                    pass
                else:
                    raise AssertionError('unexpected write: ' + p)
            Path('/workspace/AGENTS.md').write_text('updated instructions')
            Path('/workspace/pixi.toml').write_text('updated dependencies')
            Path('/workspace/.pixi/test').write_text('linux storage')
            Path('/workspace/agents/new-skill').mkdir()
            Path('/workspace/agents/new-skill/SKILL.md').write_text('new skill')
            link = Path('/workspace/agents/escape')
            link.symlink_to(sys.argv[1])
            assert not link.exists(), 'symlink escaped sandbox'
            Path.home().joinpath('state').write_text('persistent')
        """)
        with patch.dict(os.environ, {"AWS_SECRET_ACCESS_KEY": "must-not-leak"}):
            result = subprocess.run(
                self.argv(["/usr/bin/python3", "-c", code, str(self.secret)]),
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.secret.read_text(), "not accessible")
        self.assertEqual((self.state / "pixi/test").read_text(), "linux storage")
        self.assertFalse((self.project / ".pixi/test").exists())
        self.assertEqual((self.project / "agents/new-skill/SKILL.md").read_text(), "new skill")
        self.assertEqual((self.state / "agent-home/state").read_text(), "persistent")

    def test_shared_network_reaches_local_server(self):
        self.require_bwrap()
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            code = (
                f"import socket; socket.create_connection(('127.0.0.1', {port}), timeout=2).close()"
            )
            subprocess.run(self.argv(["/usr/bin/python3", "-c", code]), check=True)


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.state = root / "state"
        self.state.mkdir()
        runtime = root / "runtime"
        (runtime / "bin").mkdir(parents=True)
        self.binary = runtime / "bin/llama-server"
        self.binary.write_text(
            textwrap.dedent("""\
            #!/usr/bin/python3
            import http.server
            import sys
            if '--list-devices' in sys.argv:
                print('Available devices:\\n  CUDA0: fake test GPU')
                sys.exit(0)
            assert '--no-models-autoload' in sys.argv
            class Handler(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'{"status":"ok"}')
                def log_message(self, *args):
                    pass
            port = int(sys.argv[sys.argv.index('--port') + 1])
            http.server.HTTPServer(('127.0.0.1', port), Handler).serve_forever()
        """)
        )
        self.binary.chmod(0o755)
        gpu = root / "dxg"
        gpu.touch()
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        for name, value in [
            ("RUNTIME", runtime),
            ("STATE", self.state),
            ("MODELS", root / "models"),
            ("PRESETS", root / "models.ini"),
            ("GPU_DEVICE", gpu),
            ("PORT", port),
            ("STARTUP_TIMEOUT", 3),
        ]:
            patcher = patch.object(server, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.dict(os.environ, {}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(server.os, "geteuid", return_value=1000)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.stop)

    def stop(self):
        pidfile = self.state / "server.json"
        if pidfile.exists():
            record = json.loads(pidfile.read_text())
            server.stop(record, pidfile)
            try:
                os.waitpid(record["pid"], 0)
            except ChildProcessError:
                pass

    def test_start_idempotence_and_stop(self):
        server.main("start")
        record = json.loads((self.state / "server.json").read_text())
        self.assertTrue(server.healthy())
        server.main("start")
        self.assertEqual(json.loads((self.state / "server.json").read_text()), record)
        server.main("stop")
        self.assertFalse((self.state / "server.json").exists())
        self.assertFalse(server.owned_process(record))
        os.waitpid(record["pid"], 0)
        # No TIME_WAIT-induced false "port occupied" after stopping.
        server.main("start")
        self.assertTrue(server.healthy())

    def test_stale_pid_is_not_owned(self):
        self.assertFalse(server.owned_process({"pid": os.getpid(), "start": "wrong"}))
        self.assertFalse(server.owned_process({"pid": 1, "start": None}))

    def test_occupied_port_is_not_accepted(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", server.PORT))
            listener.listen()
            with self.assertRaisesRegex(RuntimeError, "another process"):
                server.main("start")

    def test_failed_cuda_detection(self):
        self.binary.write_text('#!/bin/sh\necho "failed to initialize CUDA" >&2\n')
        with self.assertRaisesRegex(RuntimeError, "No usable CUDA"):
            server.main("start")

    def test_startup_timeout_cleans_up(self):
        self.binary.write_text(
            "#!/usr/bin/python3\nimport sys,time\n"
            'if "--list-devices" in sys.argv: print("CUDA0: test")\n'
            "else: time.sleep(30)\n"
        )
        with patch.object(server, "STARTUP_TIMEOUT", 0.3):
            with self.assertRaisesRegex(RuntimeError, "startup timed out"):
                server.main("start")
        self.assertFalse((self.state / "server.json").exists())

    def test_agent_cannot_use_server_controller(self):
        with patch.dict(os.environ, {"OSINT_SANDBOX": "1"}):
            with self.assertRaisesRegex(RuntimeError, "outside Pi"):
                server.main("start")

    def test_startup_crash_removes_pidfile(self):
        self.binary.write_text(
            '#!/bin/sh\nif [ "$1" = --list-devices ]; then echo "CUDA0: test"; else exit 7; fi\n'
        )
        with self.assertRaisesRegex(RuntimeError, "Server exited"):
            server.main("start")
        self.assertFalse((self.state / "server.json").exists())


if __name__ == "__main__":
    unittest.main()
