import base64
import importlib.util
import json
import os
import re
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
SCRIPTS = ROOT / "wsl" / "scripts"


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sandbox = load_module("sandbox")
server = load_module("server")
mounts = load_module("mount-workspace")

SKILLS_PATH = "/workspace/.agents/skills"


class ConfigurationTests(unittest.TestCase):
    def test_manifest(self):
        data = tomllib.loads((ROOT / "pixi.toml").read_text())
        self.assertEqual(data["workspace"]["platforms"][0]["platform"], "linux-64")
        self.assertIn("pi-coding-agent", data["feature"]["pi"]["dependencies"])
        # The launcher looks the environment up by this name.
        self.assertEqual(data["environments"][sandbox.ENV_NAME], ["pi"])
        self.assertTrue(data["environments"]["llamacpp-binary-cuda"]["no-default-feature"])

    def test_extensions_are_pinned_and_built_against_the_locked_pi(self):
        """Every extension is pinned, and the locked Pi satisfies their peers.

        The manifest floats ``pi-coding-agent`` and so does the recipe
        requirement, so the lock is what decides the Pi the extensions are
        installed with. pi-subagents 0.71.0 declares
        ``@earendil-works/pi-ai >=0.86.1``; a re-lock that resolves anything
        older silently breaks delegation, so the floor is asserted against the
        lock rather than against a version string in the manifest.
        """
        recipe = (ROOT / "pixi-recipes/pi-extensions/recipe.yaml").read_text()
        build = re.search(r"PLUGINS: >-\n(?P<plugins>(?: {8}\S+\n)+)", recipe)
        self.assertIsNotNone(build, "PLUGINS must be a space-separated pin list")
        plugins = build.group("plugins").split()
        self.assertIn("pi-intercom@0.14.0", plugins)
        self.assertIn("pi-subagents@0.71.0", plugins)
        for plugin in plugins:
            self.assertRegex(plugin, r"^(@[\w.-]+/)?[\w.-]+@\d+\.\d+\.\d+$", plugin)
        # Extensions are installed by a recipe that needs Pi at build time.
        requirements = re.search(r"requirements:\n(?P<body>(?: {2,4}\S.*\n)+)", recipe).group("body")
        self.assertEqual(len(re.findall(r"^\s+- pi-coding-agent", requirements, re.M)), 2)
        locked = set(re.findall(r"pi-coding-agent-(\d+\.\d+\.\d+)", (ROOT / "pixi.lock").read_text()))
        self.assertEqual(len(locked), 1, "the lock must resolve exactly one Pi version")
        version = tuple(int(part) for part in locked.pop().split("."))
        self.assertGreaterEqual(
            version, (0, 86, 1), "pi-subagents@0.71.0 requires @earendil-works/pi-ai >=0.86.1"
        )

    def test_manifest_tools_and_tasks(self):
        data = tomllib.loads((ROOT / "pixi.toml").read_text())
        for package in (
            "python",
            "pandas",  # spreadsheet analysis
            "xlrd",  # legacy .xls
            "openpyxl",  # .xlsx
            "pyxlsb",  # .xlsb
            "pandoc",  # Markdown authoring
            "weasyprint",  # Markdown -> PDF engine
            "poppler",  # PDF -> text
        ):
            self.assertIn(package, data["dependencies"])
        tasks = data["tasks"]
        self.assertEqual(tasks["osint-pi"], "bash wsl/scripts/launch-pi.sh native")
        self.assertEqual(tasks["osint-pi-wsl"], "bash wsl/scripts/launch-pi.sh wsl")
        self.assertEqual(
            tasks["restart-server"], "bash wsl/scripts/launch-server.sh restart"
        )
        for task in ("install", "start-server", "stop-server", "update-project", "test"):
            self.assertIn(task, tasks)
        # Every referenced script exists.
        for task, command in tasks.items():
            match = re.search(r"(wsl/scripts/[\w.-]+)", command)
            if match:
                self.assertTrue((ROOT / match.group(1)).is_file(), task)

    def test_subagent_discovery_never_reads_skill_files(self):
        """Delegation scans the legacy ``.agents`` tree; skills must stay skills.

        pi-subagents reads sub-agent definitions from ``<project>/.agents/**``,
        which is where this project keeps its skills. It must skip
        ``.agents/skills/**`` itself; if a future version stops doing that, a
        SKILL.md is offered to the model as a sub-agent with the skill body as
        its system prompt. The check uses the extension's own discovery, so it
        tracks the installed version instead of re-implementing its rules.
        """
        environment = ROOT / f".pixi/envs/{sandbox.ENV_NAME}"
        node = environment / "bin/node"
        package = environment / "home/.pi/agent/npm/node_modules/pi-subagents/src/agents/agents.js"
        if not node.is_file() or not package.is_file():
            self.skipTest("the agents environment with pi-subagents is not installed")
        with tempfile.TemporaryDirectory() as temporary:
            probe = Path(temporary) / "discovery.mjs"
            probe.write_text(
                f'import {{ discoverAgentsAll }} from "{package}";\n'
                f'const all = discoverAgentsAll({str(ROOT / "workspace")!r}, "openrouter");\n'
                "const list = Array.isArray(all) ? all : Object.values(all).flat();\n"
                'console.log(JSON.stringify(list.filter((a) => a && a.name).map((a) => a.name)));\n'
            )
            result = subprocess.run(
                [str(node), str(probe)],
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
                env=dict(os.environ, HOME=temporary, PI_OFFLINE="1"),
            )
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        names = set(json.loads(result.stdout.strip().splitlines()[-1]))
        skills = {path.parent.name for path in (ROOT / "workspace/.agents/skills").glob("*/SKILL.md")}
        self.assertTrue(skills, "the workspace must still contain skills")
        self.assertEqual(names & skills, set(), "a skill file was loaded as a sub-agent")
        # The extension's own agents are still discovered, so the probe is real.
        self.assertIn("researcher", names)

    def test_packaged_intercom_can_start_its_broker_offline(self):
        """pi-intercom's entry point is TypeScript, so the broker needs a runner.

        The broker spawn resolves ``tsx`` next to the extension and only falls
        back to ``npx --no-install tsx``, which needs an npm cache. Both files
        must be part of the packaged extension tree, or starting the broker
        inside the sandbox would try to reach the network.
        """
        modules = ROOT / f".pixi/envs/{sandbox.ENV_NAME}/home/.pi/agent/npm/node_modules"
        if not modules.is_dir():
            self.skipTest(f"the {sandbox.ENV_NAME} environment is not installed")
        self.assertTrue((modules / "pi-intercom/index.ts").is_file(), "TypeScript entry point")
        self.assertTrue((modules / "tsx/dist/cli.mjs").is_file(), "bundled tsx runner")

    def test_skill_discovery_and_guidance(self):
        settings = json.loads((ROOT / "pixi-recipes/pi-home/settings.json").read_text())
        self.assertEqual(settings["skills"], [SKILLS_PATH])
        self.assertEqual(settings["llamaSettings"]["servers"][0]["url"], "http://127.0.0.1:8080")
        entry = (SCRIPTS / "pi-entry.sh").read_text()
        self.assertIn(f'exec pi --skill "$skills"', entry)
        self.assertIn(f"OSINT_SKILLS_DIR:-{SKILLS_PATH}", entry)
        for guidance, expected in [
            ("workspace/AGENTS.md", f"{SKILLS_PATH}/<skill-name>/SKILL.md"),
            ("pixi-recipes/pi-home/AGENTS.md", f"{SKILLS_PATH}/<skill-name>/SKILL.md"),
            ("AGENTS.md", "workspace/.agents/skills"),
        ]:
            self.assertIn(expected, (ROOT / guidance).read_text())
        # The workspace guide forbids the conventional but unreviewable locations.
        workspace_guide = (ROOT / "workspace/AGENTS.md").read_text()
        for forbidden in ("~/.pi", "~/.agents", ".pi/skills"):
            self.assertIn(forbidden, workspace_guide)
        # Reminders about uncommitted work are documented where the agent reads them.
        self.assertIn("git status", workspace_guide)
        self.assertIn("git status", (ROOT / "pixi-recipes/pi-home/AGENTS.md").read_text())

    def test_bundled_skills_are_valid(self):
        skills = ROOT / "workspace/.agents/skills"
        names = sorted(path.parent.name for path in skills.glob("*/SKILL.md"))
        self.assertIn("spreadsheet-reader", names)
        self.assertIn("markdown-pdf", names)
        self.assertIn("compliance-report", names)
        for name in names:
            text = (skills / name / "SKILL.md").read_text()
            frontmatter = re.match(r"---\n(.*?)\n---\n", text, re.S)
            self.assertIsNotNone(frontmatter, name)
            fields = dict(
                line.split(":", 1) for line in frontmatter.group(1).splitlines() if ":" in line
            )
            self.assertEqual(fields.get("name", "").strip(), name)
            self.assertGreater(len(fields.get("description", "").strip()), 40, name)
        # Every documented workflow points at helpers that exist.
        reader = (skills / "spreadsheet-reader/SKILL.md").read_text()
        self.assertIn("scripts/sheet.py", reader)
        self.assertTrue((skills / "spreadsheet-reader/scripts/sheet.py").is_file())
        converter = (skills / "markdown-pdf/SKILL.md").read_text()
        self.assertIn("scripts/build-pdf.sh", converter)
        self.assertIn("pdftotext", converter)
        self.assertTrue((skills / "markdown-pdf/scripts/build-pdf.sh").is_file())
        self.assertTrue((skills / "markdown-pdf/assets/report.css").is_file())
        self.assertTrue((skills / "markdown-pdf/assets/template.html").is_file())

    def test_report_and_conversion_skills_are_separate(self):
        """Report authorship and PDF conversion must not drift back together."""
        skills = ROOT / "workspace/.agents/skills"
        report = (skills / "compliance-report/SKILL.md").read_text()
        converter = (skills / "markdown-pdf/SKILL.md").read_text()
        # The report skill owns the content and hands the file over.
        for section in ("Executive summary", "Scope and method", "Sources", "confidence"):
            self.assertIn(section, report, section)
        self.assertIn("markdown-pdf", report)
        self.assertIn("build-pdf.sh", report)
        # The conversion skill owns the bytes and sends authorship elsewhere.
        for tool in ("pandoc", "pdfinfo", "pdftotext", "pdftoppm"):
            self.assertIn(tool, converter, tool)
        self.assertIn("compliance-report", converter)
        for section in ("## Executive summary", "## Scope and method", "## Sources"):
            self.assertNotIn(section, converter, section)

    def test_skill_scripts_only_use_available_programs(self):
        """Skill scripts run on the sandbox PATH: coreutils, or a pixi dependency."""
        # Programs that exist on any Linux, in the shell scripts' PATH.
        always_available = {
            "awk", "basename", "bash", "cat", "cd", "chmod", "cp", "cut", "date",
            "dirname", "echo", "exit", "find", "grep", "head", "mkdir", "mv", "mktemp",
            "printf", "pwd", "read", "rm", "sed", "sleep", "sort", "tail", "tee", "test",
            "touch", "tr", "trap", "true", "uniq", "wc", "xargs",
        }
        # Shell keywords, builtins and trap signals are part of bash itself.
        bash_keywords = {
            "!", "[[", "]]", "case", "do", "done", "elif", "else", "esac", "export", "fi",
            "for", "function", "if", "in", "local", "return", "set", "shift", "then", "unset",
            "until", "while", "command", "source",
            "DEBUG", "ERR", "EXIT", "INT", "PIPE", "RETURN", "TERM",
        }
        # Programs that are NOT part of a base Linux system: each must be
        # delivered by pixi.toml, mapping program -> conda/pypi package.
        pixi_provided = {
            "pandoc": "pandoc",
            "weasyprint": "weasyprint",
            "pdfinfo": "poppler",
            "pdftotext": "poppler",
            "pdftoppm": "poppler",
            "python3": "python",
        }
        dependencies = tomllib.loads((ROOT / "pixi.toml").read_text())["dependencies"]
        skills = ROOT / "workspace/.agents/skills"
        scripts = sorted(skills.glob("*/scripts/*.sh"))
        self.assertTrue(scripts)
        for script in scripts:
            found = self.shell_commands(script.read_text())
            unknown = found - always_available - bash_keywords - set(pixi_provided)
            for word in sorted(unknown):
                self.fail(
                    f"{script.relative_to(ROOT)} runs {word!r}: not a base Linux "
                    f"program, a bash builtin, or a pixi dependency"
                )
        for program, package in pixi_provided.items():
            with self.subTest(program=program):
                self.assertIn(package, dependencies)

    @staticmethod
    def shell_commands(text):
        """Names run by a bash script, minus the functions it defines itself.

        Not a bash parser: comments, quoted text and leading variable
        assignments are dropped, then the text is cut at the separators that
        start a new command. Enough to find a program that is not installed.
        """
        functions = set(re.findall(r"^\s*([\w.-]+)\s*\(\)\s*\{", text, re.M))
        text = re.sub(r"\\\n", " ", text)  # a continued line is one command
        text = re.sub(r"#.*", "", text)
        text = re.sub(r"'[^']*'", " ", text)
        text = re.sub(r'"[^"]*"', " ", text)
        text = re.sub(r"`[^`]*`", " ", text)
        text = text.replace("$(", " ( ").replace("${", " $ {")
        commands = set()
        for segment in re.split(r"[;|&()\n]+", text):
            words = segment.split()
            # A simple command may be preceded by NAME=value assignments.
            while words and re.fullmatch(r"[A-Za-z_]\w*=\S*", words[0]):
                words.pop(0)
            # Anything that cannot start a program name is a flag, a
            # redirection or an expansion, not a command.
            if words and re.fullmatch(r"[A-Za-z_][\w.+-]*", words[0]):
                commands.add(words[0])
        return commands - functions

    def test_beginner_readme_covers_the_basics(self):
        readme = (ROOT / "README.md").read_text()
        for needle in (
            "github.com/signup",
            "desktop.github.com",
            "Commit",
            "Push",
            "Pull",
            "openrouter.ai",
            "/login",
            "/scoped-models",
            "/model",
            "/thinking",
            "/new",
            "/resume",
            "/tree",
            "AGENTS.md",
            "skill",
        ):
            self.assertIn(needle, readme, needle)
        # Deliberately not taught to beginners: branches and pull requests.
        self.assertNotIn("git branch", readme.lower())
        self.assertNotIn("pull request", readme.lower())

    def test_shell_syntax(self):
        for file in [*SCRIPTS.rglob("*.sh"), *(SCRIPTS / "install").iterdir()]:
            with self.subTest(file=file):
                subprocess.run(["/bin/bash", "-n", str(file)], check=True)

    def test_windows_bootstrap_is_non_destructive(self):
        script = (ROOT / "wsl/Install.ps1").read_text()
        self.assertNotIn("--unregister", script)
        self.assertNotIn("reset --hard", script)
        self.assertNotIn("git pull", script)
        self.assertIn("--no-distribution", script)
        self.assertIn("Get-FileHash", script)
        self.assertIn("Restart Windows", script)
        self.assertIn("ConvertTo-ShellLiteral", script)
        # Third-party terminal: pinned, checksummed, optional, and never bundled.
        self.assertIn("$MobaXtermSha256", script)
        self.assertIn("$SkipMobaXterm", script)
        self.assertIn("/usr/local/bin/osint-terminal", script)
        self.assertIn("/mnt/osint-ai/wsl/scripts/provision-wsl.sh", script)


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
            target = root / "mnt-osint-ai"
            target.mkdir()
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
                self.assertEqual(os.fstat(target_fd).st_ino, target.stat().st_ino)

            with (
                patch.object(mounts, "WINDOWS_TARGET", target),
                patch.object(mounts.tempfile, "mkdtemp", return_value=str(temporary)),
                patch.object(mounts, "run", side_effect=run),
                patch.object(mounts, "bind_fds", side_effect=bind) as bind_mock,
                patch.object(mounts.os.path, "ismount", side_effect=lambda _: mounted),
            ):
                mounts.mount_windows_checkout(r"C:\Users\Alice\Skills")
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
            (bundled / "AGENTS.md").write_text("use /workspace/.agents/skills")
            (bundled.parent / "web-search.json").write_text("{}")
            skills = root / "workspace-skills"
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
                OSINT_SKILLS_DIR=str(skills),
                OSINT_PI_ARGS=base64.b64encode(json.dumps(prompts).encode()).decode(),
            )
            result = subprocess.run(
                ["/bin/bash", str(SCRIPTS / "pi-entry.sh")],
                input="terminal input",
                capture_output=True,
                text=True,
                env=env,
                check=True,
            )
            args, stdin = json.loads(result.stdout)
            self.assertEqual(args, ["--skill", str(skills), *prompts])
            self.assertTrue(skills.is_dir(), "the skills directory is created if missing")
            self.assertEqual(stdin, "terminal input")
            self.assertEqual(
                json.loads((live / "settings.json").read_text())["defaultProvider"], "openrouter"
            )
            self.assertEqual(
                json.loads((live / "auth.json").read_text()), {"preserve": "user login"}
            )

    def test_entry_refuses_to_run_unsandboxed(self):
        env = {key: value for key, value in os.environ.items() if key != "OSINT_SANDBOX"}
        result = subprocess.run(
            ["/bin/bash", str(SCRIPTS / "pi-entry.sh")],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sandbox", result.stderr.lower())


class SandboxFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="osint test ' spaces ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "linux checkout"
        self.workspace = self.project / "workspace"
        self.state = self.root / "linux state"
        (self.project / ".git").mkdir(parents=True)
        (self.project / f".pixi/envs/{sandbox.ENV_NAME}/bin").mkdir(parents=True)
        (self.project / f".pixi/envs/{sandbox.ENV_NAME}/bin/pi").write_text("#!/bin/sh\n")
        (self.workspace / ".agents/skills").mkdir(parents=True)
        (self.project / "wsl/scripts").mkdir(parents=True)
        (self.state / "agent-home").mkdir(parents=True)
        (self.project / ".git/config").write_text("private git configuration")
        (self.project / "wsl/scripts/protected").write_text("original")
        (self.project / "pixi.toml").write_text("project manifest")
        (self.workspace / "AGENTS.md").write_text("workspace instructions")
        self.secret = self.root / "host-secret"
        self.secret.write_text("not accessible")
        patcher = patch.object(sandbox, "filesystem", return_value="ext4")
        patcher.start()
        self.addCleanup(patcher.stop)

    def argv(self, command=None, *, workspace=None, mode="native", **kwargs):
        return sandbox.build_command(
            self.project,
            self.workspace if workspace is None else workspace,
            self.state,
            mode=mode,
            command=command,
            **kwargs,
        )


class SandboxArgumentTests(SandboxFixture):
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
        # Plain Linux has one checkout: the agent works in it, so it is writable.
        self.assertIn(
            (str(self.project), "/opt/osint-ai/project"),
            [(args[i + 1], args[i + 2]) for i, a in enumerate(args) if a == "--bind"],
        )
        self.assertIn(
            (str(self.workspace), "/workspace"),
            [(args[i + 1], args[i + 2]) for i, a in enumerate(args) if a == "--bind"],
        )
        self.assertEqual(args[args.index("--chdir") + 1], "/workspace")

    def test_the_agents_git_repository_is_reachable(self):
        """The agent must be able to run Git itself, in a real repository.

        It is allowed to see `.git` and to write to it; the human still reviews
        every change, which `AGENTS.md` states. What must not come back is a
        read-only view that makes `git status` fail, or a hidden `.git` that
        silently breaks every reminder.
        """
        args = self.argv()
        pairs = [(args[i], args[i + 1]) for i, a in enumerate(args) if a.startswith("--")]
        # Plain Linux: nothing is layered over `.git`, so Git works in place.
        self.assertNotIn(("--tmpfs", "/opt/osint-ai/project/.git"), pairs)
        self.assertNotIn(("--ro-bind", "/opt/osint-ai/project/.git"), pairs)
        self.assertNotIn("--remount-ro", args)
        # The environment the agent runs on is the one thing in the writable
        # tree it must not be able to replace.
        self.assertIn(
            (str(self.project / ".pixi"), "/opt/osint-ai/project/.pixi"),
            [(args[i + 1], args[i + 2]) for i, a in enumerate(args) if a == "--ro-bind"],
        )
        self.assertEqual(
            (self.project / ".git" / "config").read_text(), "private git configuration"
        )

    def test_wsl_mode_gives_the_agent_the_windows_checkout(self):
        """WSL has two checkouts: the Windows one is the agent's, the Linux one is not.

        The Windows checkout is bound read-write, `.git` included, so `git
        status` describes the files the user commits from GitHub Desktop. The
        Linux checkout keeps the code that starts Pi out of reach, `.git`
        included.
        """
        mount = self.root / "mnt-osint-ai"
        windows = mount / "workspace"
        (mount / ".git").mkdir(parents=True)
        windows.mkdir()
        with patch.object(sandbox, "WINDOWS_MOUNT", mount):
            args = self.argv(workspace=windows, mode="wsl")
        binds = [(args[i + 1], args[i + 2]) for i, a in enumerate(args) if a == "--bind"]
        ro_binds = [(args[i + 1], args[i + 2]) for i, a in enumerate(args) if a == "--ro-bind"]
        self.assertIn((str(mount), str(mount)), binds)
        self.assertIn((str(windows), "/workspace"), binds)
        self.assertIn((str(self.project), "/opt/osint-ai/project"), ro_binds)
        # The Windows checkout is writable through its own path, with no
        # read-only or empty overlay on top of its repository.
        pairs = [(args[i], args[i + 1]) for i, a in enumerate(args) if a.startswith("--")]
        self.assertNotIn(("--tmpfs", str(mount / ".git")), pairs)
        self.assertNotIn(("--ro-bind", str(mount / ".git")), pairs)
        # The Linux checkout's history stays hidden behind the program mount.
        self.assertIn(("--tmpfs", "/opt/osint-ai/project/.git"), pairs)
        self.assertEqual(args[args.index("--chdir") + 1], "/workspace")

    def test_intercom_state_is_a_private_tmpfs(self):
        """pi-intercom's broker state must not land in the persistent home.

        A shared home would let a second sandbox unlink the live broker's
        socket and would redeliver mail queued for a closed session. The mount
        must come after the agent home so it shadows only that subdirectory,
        and it must be a tmpfs, not a bind.
        """
        args = self.argv()
        mounts = [(args[i], args[i + 1]) for i, a in enumerate(args) if a.startswith("--")]
        self.assertIn(("--tmpfs", sandbox.INTERCOM_DIR), mounts)
        self.assertNotIn(("--bind", sandbox.INTERCOM_DIR), mounts)
        self.assertNotIn(("--ro-bind", sandbox.INTERCOM_DIR), mounts)
        home_index = args.index("/home/osint")
        self.assertEqual(args[home_index - 2 : home_index], ["--bind", str(self.state / "agent-home")])
        self.assertGreater(args.index(sandbox.INTERCOM_DIR), home_index)
        self.assertEqual(args[args.index(sandbox.INTERCOM_DIR) - 1], "--tmpfs")
        # Only the intercom subdirectory is private: the rest of the home, the
        # workspace and the read-only project stay as the boundary requires.
        self.assertTrue(sandbox.INTERCOM_DIR.startswith("/home/osint/.pi/agent/"))

    def test_environment_points_at_read_only_tools(self):
        args = self.argv()
        env = {args[i + 1]: args[i + 2] for i, a in enumerate(args) if a == "--setenv"}
        self.assertEqual(
            env["CONDA_PREFIX"], f"/opt/osint-ai/project/.pixi/envs/{sandbox.ENV_NAME}"
        )
        self.assertTrue(
            env["PATH"].startswith(f"/opt/osint-ai/project/.pixi/envs/{sandbox.ENV_NAME}/bin:")
        )
        self.assertEqual(env["HOME"], "/home/osint")
        self.assertEqual(env["OSINT_SANDBOX"], "1")
        self.assertEqual(json.loads(base64.b64decode(env["OSINT_PI_ARGS"])), [])

    def test_wsl_mode_also_swaps_the_workspace(self):
        windows = self.root / "mnt-osint-ai/workspace"
        (windows.parent / ".git").mkdir(parents=True)
        windows.mkdir(parents=True)
        native = self.argv()
        wsl = self.argv(workspace=windows, mode="wsl")
        self.assertIn(
            (str(windows), "/workspace"),
            [(wsl[i + 1], wsl[i + 2]) for i, a in enumerate(wsl) if a == "--bind"],
        )
        self.assertNotIn(str(self.workspace), wsl)
        # The entry point, the environment and the working directory are the same.
        self.assertIn("/opt/osint-ai/project", native)
        self.assertEqual(native[native.index("--chdir") :], wsl[wsl.index("--chdir") :])

    def test_entry_prefers_installed_copy(self):
        with patch("pathlib.Path.is_file", return_value=True):
            args = self.argv()
        self.assertEqual(args[-2:], ["/bin/bash", "/usr/local/lib/osint-ai/pi-entry.sh"])
        # Without a root-owned installation, the (developer-editable) checkout copy.
        self.assertEqual(
            self.argv()[-2:],
            ["/bin/bash", "/opt/osint-ai/project/wsl/scripts/pi-entry.sh"],
        )

    def test_protected_symlink_rejected(self):
        shutil.rmtree(self.workspace)
        self.workspace.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "symlink"):
            sandbox.check_storage("native", self.project, self.workspace, self.state)
        # The launcher never builds a namespace for it either.
        with self.assertRaisesRegex(RuntimeError, "symlink"):
            self.argv(["/bin/true"])

    def test_workspace_must_not_be_the_project_root(self):
        with self.assertRaisesRegex(RuntimeError, "subdirectory"):
            sandbox.check_storage("native", self.project, self.project, self.state)

    def test_missing_environment_is_reported(self):
        (self.project / f".pixi/envs/{sandbox.ENV_NAME}/bin/pi").unlink()
        with self.assertRaisesRegex(RuntimeError, "environment is not installed"):
            sandbox.check_storage("native", self.project, self.workspace, self.state)

    def test_windows_filesystem_rejected(self):
        with patch.object(sandbox, "filesystem", return_value="ntfs"):
            with self.assertRaisesRegex(RuntimeError, "Refusing"):
                sandbox.check_storage("native", self.project, self.workspace, self.state)

    def test_wsl_mode_requires_the_windows_mount(self):
        windows = self.root / "mnt-osint-ai/workspace"
        windows.mkdir(parents=True)
        with (
            patch.object(sandbox, "WINDOWS_MOUNT", self.root / "mnt-osint-ai"),
            patch.object(sandbox.os.path, "ismount", return_value=False),
        ):
            with self.assertRaisesRegex(RuntimeError, "not mounted"):
                sandbox.check_storage("wsl", self.project, windows, self.state)

    def test_wsl_mode_accepts_the_mounted_workspace(self):
        mount = self.root / "mnt-osint-ai"
        windows = mount / "workspace"
        (mount / ".git").mkdir(parents=True)
        windows.mkdir(parents=True)
        with (
            patch.object(sandbox, "WINDOWS_MOUNT", mount),
            patch.object(sandbox.os.path, "ismount", return_value=True),
        ):
            sandbox.check_storage("wsl", self.project, windows, self.state)

    def test_wsl_mode_requires_a_real_git_checkout(self):
        mount = self.root / "mnt-osint-ai"
        windows = mount / "workspace"
        windows.mkdir(parents=True)
        with (
            patch.object(sandbox, "WINDOWS_MOUNT", mount),
            patch.object(sandbox.os.path, "ismount", return_value=True),
        ):
            with self.assertRaisesRegex(RuntimeError, "not a Git checkout"):
                sandbox.check_storage("wsl", self.project, windows, self.state)

    def test_worktree_git_file_rejected(self):
        """A `.git` that is a gitdir pointer is refused, not followed."""
        shutil.rmtree(self.project / ".git")
        (self.project / ".git").write_text("gitdir: /elsewhere")
        mount = self.root / "mnt-osint-ai"
        (mount / ".git").mkdir(parents=True)
        windows = mount / "workspace"
        windows.mkdir(parents=True)
        with (
            patch.object(sandbox, "WINDOWS_MOUNT", mount),
            patch.object(sandbox.os.path, "ismount", return_value=True),
        ):
            with self.assertRaisesRegex(RuntimeError, "real directory"):
                self.argv(["/bin/true"], workspace=windows, mode="wsl")

    def test_mount_helper_rejects_symlink(self):
        link = self.root / "link"
        link.symlink_to(self.state / "agent-home", target_is_directory=True)
        with self.assertRaises(OSError):
            mounts.directory_fd(link)

    def test_launcher_wrappers_exec_trusted_commands(self):
        script = (SCRIPTS / "launch-pi.sh").read_text()
        self.assertIn("/usr/local/bin/osint-pi-wsl", script)
        self.assertIn("sandbox.py", script)
        self.assertIn("--native", (SCRIPTS / "install/osint-pi").read_text())
        self.assertIn("--wsl", (SCRIPTS / "install/osint-pi-wsl").read_text())


class AgentGitTests(SandboxFixture):
    """The agent runs Git in the checkout it works in; this is what it sees."""

    def setUp(self):
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git is not installed")
        # Replace the fixture's placeholder .git with a real repository.
        shutil.rmtree(self.project / ".git")

    def git(self, *args):
        subprocess.run(
            [
                "git",
                "-C",
                str(self.project),
                "-c",
                "core.fsmonitor=false",
                "-c",
                "user.name=test",
                "-c",
                "user.email=test@example.com",
                "-c",
                "commit.gpgsign=false",
                *args,
            ],
            check=True,
            capture_output=True,
        )

    def sandbox_git_status(self, command=None):
        """Run `git status` from the sandbox's working directory, if possible."""
        if not Path("/usr/bin/bwrap").exists():
            self.skipTest("system bubblewrap is not installed")
        self.git("init", "-q", "-b", "main")
        self.git("add", "-A")
        self.git("commit", "-qm", "initial")
        probe = subprocess.run(self.argv(["/bin/true"]), capture_output=True, text=True, check=False)
        if probe.returncode:
            self.skipTest("unprivileged bubblewrap unavailable: " + probe.stderr.strip())
        result = subprocess.run(
            self.argv(["git", "status", "--porcelain=v1", "-b"]),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_a_clean_and_a_dirty_checkout_are_both_reported(self):
        self.git("init", "-q", "-b", "main")
        self.git("add", "-A")
        self.git("commit", "-qm", "initial")
        (self.workspace / "AGENTS.md").write_text("changed rule")
        (self.workspace / "new-skill.txt").write_text("new")
        status = self.sandbox_git_status()
        self.assertIn("## main", status)
        self.assertIn("workspace/AGENTS.md", status)
        self.assertIn("?? workspace/new-skill.txt", status)
        # The change is the real file on the host, not a sandbox-local copy.
        self.assertEqual((self.workspace / "AGENTS.md").read_text(), "changed rule")

    def test_the_agent_could_write_to_git(self):
        """Documents the consequence of a writable `.git` on purpose.

        The sandbox does not stop the agent from committing; the human reviews
        the diff. This test exists so nobody removes that fact from the docs by
        accident, and so the permission is a decision rather than an accident.
        """
        if not Path("/usr/bin/bwrap").exists():
            self.skipTest("system bubblewrap is not installed")
        self.git("init", "-q", "-b", "main")
        self.git("add", "-A")
        self.git("commit", "-qm", "initial")
        probe = subprocess.run(self.argv(["/bin/true"]), capture_output=True, text=True, check=False)
        if probe.returncode:
            self.skipTest("unprivileged bubblewrap unavailable: " + probe.stderr.strip())
        result = subprocess.run(
            self.argv(
                [
                    "git",
                    "-c",
                    "user.name=agent",
                    "-c",
                    "user.email=agent@example.com",
                    "commit",
                    "-qm",
                    "written from inside the sandbox",
                ]
            ),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        log = subprocess.run(
            ["git", "-C", str(self.project), "log", "--oneline", "-1"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("written from inside the sandbox", log.stdout)


class SandboxBoundaryTests(SandboxFixture):
    def require_bwrap(self):
        if not Path("/usr/bin/bwrap").exists():
            self.skipTest("system bubblewrap is not installed")
        probe = subprocess.run(self.argv(["/bin/true"]), capture_output=True, text=True, check=False)
        if probe.returncode:
            self.skipTest("unprivileged bubblewrap unavailable: " + probe.stderr.strip())

    def test_real_filesystem_boundary(self):
        self.require_bwrap()
        code = textwrap.dedent("""
            import os
            from pathlib import Path
            import subprocess
            import sys
            assert not Path(sys.argv[1]).exists(), 'host secret exposed'
            assert not Path('/mnt/c').exists()
            assert not Path('/init').exists()
            assert not Path('/dev/dxg').exists()
            assert list(Path('/run').iterdir()) == [], '/run is an empty private tmpfs'
            assert Path('/opt/osint-ai/project/pixi.toml').read_text() == 'project manifest'
            # The agent's own repository is reachable and writable in plain Linux.
            assert Path('/opt/osint-ai/project/.git/config').read_text() == 'private git configuration'
            assert subprocess.run(['git', 'status', '--porcelain'], cwd='/opt/osint-ai/project').returncode == 0
            assert not os.environ.get('AWS_SECRET_ACCESS_KEY')
            for p in ['/etc/hosts']:
                try:
                    Path(p).write_text('should fail')
                except OSError:
                    pass
                else:
                    raise AssertionError('unexpected write: ' + p)
            Path('/workspace/AGENTS.md').write_text('updated instructions')
            Path('/workspace/.agents/skills/new-skill').mkdir()
            Path('/workspace/.agents/skills/new-skill/SKILL.md').write_text('new skill')
            link = Path('/workspace/escape')
            link.symlink_to(sys.argv[1])
            assert not link.exists(), 'symlink escaped the sandbox'
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
        self.assertEqual(
            (self.workspace / ".agents/skills/new-skill/SKILL.md").read_text(), "new skill"
        )
        self.assertEqual((self.state / "agent-home/state").read_text(), "persistent")

    def test_wsl_filesystem_boundary(self):
        """In WSL the program checkout stays read-only; the Windows one does not."""
        self.require_bwrap()
        mount = self.root / "mnt-osint-ai"
        (mount / ".git").mkdir(parents=True)
        (mount / ".git" / "config").write_text("windows repository")
        (mount / "AGENTS.md").write_text("windows instructions")
        windows = mount / "workspace"
        windows.mkdir(parents=True)
        code = textwrap.dedent("""
            from pathlib import Path
            # The agent works here, and this is the repository it reports on.
            assert Path('/mnt/osint-ai/AGENTS.md').read_text() == 'windows instructions'
            assert Path('/mnt/osint-ai/.git/config').read_text() == 'windows repository'
            Path('/mnt/osint-ai/AGENTS.md').write_text('edited by the agent')
            # The Linux checkout is code only: read-only, and no repository.
            assert Path('/opt/osint-ai/project/pixi.toml').read_text() == 'project manifest'
            assert not Path('/opt/osint-ai/project/.git/config').exists()
            for p in ['/opt/osint-ai/project/pixi.toml', '/opt/osint-ai/project/.git']:
                try:
                    Path(p).write_text('should fail')
                except OSError:
                    pass
                else:
                    raise AssertionError('unexpected write: ' + p)
        """)
        with (
            patch.object(sandbox, "WINDOWS_MOUNT", mount),
            patch.object(sandbox.os.path, "ismount", return_value=True),
        ):
            args = self.argv(["/usr/bin/python3", "-c", code], workspace=windows, mode="wsl")
            result = subprocess.run(args, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((mount / "AGENTS.md").read_text(), "edited by the agent")
        self.assertEqual((self.project / "pixi.toml").read_text(), "project manifest")

    def test_cwd_is_the_workspace(self):
        self.require_bwrap()
        result = subprocess.run(
            self.argv(["/usr/bin/python3", "-c", "import os; print(os.getcwd())"]),
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(result.stdout.strip(), "/workspace")

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
    FAKE = """#!/usr/bin/python3
import http.server
import json
import sys
from pathlib import Path
Path({argv_log!r}).write_text(json.dumps(sys.argv[1:]))
if '--list-devices' in sys.argv:
    if {has_gpu}:
        print('Available devices:\\n  CUDA0: fake test GPU')
        sys.exit(0)
    print('failed to initialize CUDA', file=sys.stderr)
    sys.exit(1)
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{{"status":"ok"}}')
    def log_message(self, *args):
        pass
port = int(sys.argv[sys.argv.index('--port') + 1])
http.server.HTTPServer(('127.0.0.1', port), Handler).serve_forever()
"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.state = root / "state"
        self.state.mkdir()
        self.argv_log = root / "argv.json"
        runtime = root / "runtime"
        (runtime / "bin").mkdir(parents=True)
        self.binary = runtime / "bin/llama-server"
        self.has_gpu = True
        self.write_fake()
        self.gpu = root / "dxg"
        self.gpu.touch()
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        for name, value in [
            ("RUNTIME", runtime),
            ("STATE", self.state),
            ("MODELS", root / "models"),
            ("PRESETS", root / "models.ini"),
            ("GPU_DEVICE", self.gpu),
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

    def write_fake(self, *, has_gpu=None):
        if has_gpu is not None:
            self.has_gpu = has_gpu
        self.binary.write_text(self.FAKE.format(argv_log=str(self.argv_log), has_gpu=self.has_gpu))
        self.binary.chmod(0o755)

    def recorded_argv(self):
        return json.loads(self.argv_log.read_text())

    def record(self):
        return json.loads((self.state / "server.json").read_text())

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
        record = self.record()
        self.assertEqual(record["backend"], "cuda")
        self.assertTrue(server.healthy())
        server.main("start")
        self.assertEqual(self.record(), record)
        server.main("stop")
        self.assertFalse((self.state / "server.json").exists())
        self.assertFalse(server.owned_process(record))
        os.waitpid(record["pid"], 0)
        # No TIME_WAIT-induced false "port occupied" after stopping.
        server.main("start")
        self.assertTrue(server.healthy())

    def test_gpu_layers_are_left_alone_on_a_gpu(self):
        server.main("start")
        self.assertNotIn("--n-gpu-layers", self.recorded_argv())

    def test_restart_replaces_the_running_server(self):
        server.main("start")
        first = self.record()["pid"]
        server.main("restart")
        second = self.record()["pid"]
        self.assertNotEqual(first, second)
        self.assertTrue(server.healthy())
        os.waitpid(first, 0)

    def test_no_gpu_device_falls_back_to_cpu(self):
        self.gpu.unlink()
        server.main("start")
        self.assertEqual(self.record()["backend"], "cpu")
        argv = self.recorded_argv()
        self.assertEqual(argv[argv.index("--n-gpu-layers") + 1], "0")
        self.assertTrue(server.healthy())

    def test_cuda_build_without_a_device_falls_back_to_cpu(self):
        self.write_fake(has_gpu=False)
        server.main("start")
        self.assertEqual(self.record()["backend"], "cpu")
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
