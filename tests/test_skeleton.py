import base64
import importlib.util
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import tempfile
import textwrap
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
WINDOWS = ROOT / "windows"


def load_module(name, directory=SCRIPTS):
    spec = importlib.util.spec_from_file_location(name, directory / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sandbox = load_module("sandbox")
server = load_module("server")
mounts = load_module("mount-workspace", WINDOWS)

# The launcher owns the sandbox paths; everything else reads them from it, so a
# rename cannot leave the guidance and the mounts disagreeing.
CHECKOUT_PATH = str(sandbox.AGENT_MOUNT)
WORKSPACE_PATH = str(sandbox.WORKSPACE_MOUNT)
SKILLS_PATH = str(sandbox.SKILLS_MOUNT)
PROGRAM_PATH = str(sandbox.PROGRAM_MOUNT)
# The launcher runs the bubblewrap this checkout's own locked environment
# installs, so that binary - not the distribution's - is what the integration
# tests have to exercise.
PINNED_BWRAP = ROOT / sandbox.BWRAP_SUBPATH
PINNED_BWRAP = PINNED_BWRAP if PINNED_BWRAP.is_file() else None


class ConfigurationTests(unittest.TestCase):
    def test_manifest(self):
        data = tomllib.loads((ROOT / "pixi.toml").read_text())
        self.assertEqual(data["workspace"]["platforms"][0]["platform"], "linux-64")
        # win-64 exists for one reason: the Windows deployment installs the inference
        # environment natively, outside WSL, so llama.cpp reaches the GPU directly.
        self.assertIn("win-64", data["workspace"]["platforms"])
        self.assertIn("pi-coding-agent", data["feature"]["pi"]["dependencies"])
        # The launcher looks the environment up by this name, and it is the only
        # environment that resolves for win-64: Pi itself never runs on Windows.
        self.assertEqual(data["environments"][sandbox.ENV_NAME]["features"], ["pi"])
        self.assertEqual(data["environments"][sandbox.ENV_NAME]["platforms"], ["linux-64-glibc234"])
        inference = data["environments"]["llamacpp-binary-vulkan"]
        self.assertTrue(inference["no-default-feature"])
        self.assertEqual(inference["platforms"], ["linux-64-glibc234", "win-64"])

    def test_extensions_are_pinned_and_built_against_the_locked_pi(self):
        """Every extension is pinned, and the locked Pi satisfies their peers.

        The manifest floats ``pi-coding-agent`` and so does the recipe
        requirement, so the lock is what decides the Pi the extensions are
        installed with. pi-subagents declares
        ``@earendil-works/pi-ai >=0.86.1``; a re-lock that resolves anything
        older silently breaks delegation, so the floor is asserted against the
        lock rather than against a version string in the manifest. The pins here
        must match the ``PLUGINS`` list in ``pixi-recipes/pi-extensions/recipe.yaml``,
        which is the only place a pin is decided.
        """
        recipe = (ROOT / "pixi-recipes/pi-extensions/recipe.yaml").read_text()
        build = re.search(r"PLUGINS: >-\n(?P<plugins>(?: {8}\S+\n)+)", recipe)
        self.assertIsNotNone(build, "PLUGINS must be a space-separated pin list")
        plugins = build.group("plugins").split()
        self.assertIn("pi-intercom@0.16.1", plugins)
        # The pins move, so this asserts the floor the tests were written against
        # rather than one exact version.
        subagents = next((p for p in plugins if p.startswith("pi-subagents@")), None)
        self.assertIsNotNone(subagents, "pi-subagents must stay pinned")
        self.assertGreaterEqual(
            tuple(int(part) for part in subagents.split("@")[1].split(".")), (0, 76, 0)
        )
        # Pi's built-in llama.cpp provider replaces pi-llama-cpp, so the extension
        # must not come back: two providers listing the same server is the bug that
        # removing it fixed (tests/test_skeleton.py:test_local_models_are_generated).
        self.assertFalse([p for p in plugins if "llama" in p], plugins)
        for plugin in plugins:
            self.assertRegex(plugin, r"^(@[\w.-]+/)?[\w.-]+@\d+\.\d+\.\d+$", plugin)
        # Extensions are installed by a recipe that needs Pi at build time.
        requirements = re.search(r"requirements:\n(?P<body>(?: {2,4}\S.*\n)+)", recipe).group("body")
        self.assertEqual(len(re.findall(r"^\s+- pi-coding-agent", requirements, re.M)), 2)
        locked = set(re.findall(r"pi-coding-agent-(\d+\.\d+\.\d+)", (ROOT / "pixi.lock").read_text()))
        self.assertEqual(len(locked), 1, "the lock must resolve exactly one Pi version")
        version = tuple(int(part) for part in locked.pop().split("."))
        self.assertGreaterEqual(
            version, (0, 86, 1), "pi-subagents requires @earendil-works/pi-ai >=0.86.1"
        )

    def test_manifest_tools_and_tasks(self):
        data = tomllib.loads((ROOT / "pixi.toml").read_text())
        for package in (
            "python",
            "bubblewrap",  # the sandbox itself, see test_bubblewrap_is_pinned
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
        self.assertEqual(tasks["osint-pi"], "bash scripts/bwrap-pi.sh --native")
        self.assertEqual(tasks["osint-pi-wsl"], "bash scripts/bwrap-pi.sh --wsl")
        # Local inference is optional and lives in its own environment, and the
        # inference tasks run *in* that environment: that is how Pixi deploys it, so
        # there is no install task to remember and no wrapper that checks whether
        # the program happens to exist.
        self.assertNotIn("install-server", tasks)
        self.assertNotIn("llamacpp", tasks["install"]["depends-on"])
        inference = data["feature"]["llamacpp-binary-vulkan"]["tasks"]["_server"]
        self.assertEqual(inference["cmd"], "python -I scripts/server.py {{ action }}")
        self.assertIn("python", data["feature"]["llamacpp-binary-vulkan"]["dependencies"])
        for name, action in (("start-server", "start"), ("restart-server", "restart")):
            dependency = tasks[name]["depends-on"][0]
            self.assertEqual(dependency["task"], "_server", name)
            self.assertEqual(dependency["environment"], "llamacpp-binary-vulkan", name)
            self.assertEqual(dependency["args"], [action], name)
        # Stopping needs no inference program, so it must not pull that environment.
        self.assertEqual(tasks["stop-server"], "python -I scripts/server.py stop")
        for task in ("install", "start-server", "stop-server", "update-project", "test"):
            self.assertIn(task, tasks)
        # `pixi r install` is the one task that makes the sandbox runnable: it
        # loads the profile Ubuntu needs for the pinned bubblewrap, then proves
        # that binary can start a sandbox.
        self.assertEqual(tasks["install"]["depends-on"], ["install-apparmor", "install-check"])
        # Every referenced script exists.
        def task_text(command):
            if isinstance(command, str):
                return command
            parts = [command["cmd"]] if "cmd" in command else []
            for dependency in command.get("depends-on", []):
                parts.append(dependency if isinstance(dependency, str) else dependency["task"])
            return " ".join(parts)

        for name, command in {**tasks, **data["feature"]["llamacpp-binary-vulkan"]["tasks"]}.items():
            for match in re.finditer(r"((?:scripts|windows)/[\w.-]+)", task_text(command)):
                self.assertTrue((ROOT / match.group(1)).is_file(), name)

    def test_bubblewrap_is_pinned_by_the_lock(self):
        """Containment is part of the product, so the lockfile decides it.

        The sandbox used to exec `/usr/bin/bwrap`: `update-project` and `pixi.lock`
        pinned Pi and every skill tool while the program that builds the agent's
        mount namespace stayed whatever the distribution shipped, and a distro that
        did not have it failed with "Install the 'bubblewrap' package".
        """
        data = tomllib.loads((ROOT / "pixi.toml").read_text())
        self.assertIn("bubblewrap", data["dependencies"])
        locked = set(re.findall(r"bubblewrap-(\d+\.\d+\.\d+)", (ROOT / "pixi.lock").read_text()))
        self.assertEqual(len(locked), 1, "the lock must resolve exactly one bubblewrap")

    def test_local_inference_is_not_a_root_owned_snapshot(self):
        """`/opt/osint-ai/server` is gone; the runtime is the checkout's own env.

        A second copy of the manifest under /opt meant a maintainer had to reinstall
        it by hand, and every message about it named a path the user had never seen.
        """
        paths = [
            *SCRIPTS.iterdir(),
            *WINDOWS.rglob("*"),
            *(ROOT / "docs").iterdir(),
            ROOT / "README.md",
            ROOT / "AGENTS.md",
            ROOT / "pixi.toml",
        ]
        for path in (p for p in paths if p.is_file() and "__pycache__" not in p.parts):
            self.assertNotIn("/opt/osint-ai/server", path.read_text(), path)

    def test_ci_workflow_runs_this_suite(self):
        """CI runs the suite that lives here, and it does not fake a platform.

        A CI file that drifts from `pixi.toml` gives a green tick for a suite
        nobody runs. The manifest resolves `linux-64` only, so CI installs its
        Pixi environment on Linux runners only, and the Windows job parses the
        installer instead of installing it.
        """
        ci = (ROOT / ".github/workflows/ci.yml").read_text()
        self.assertIn("pixi run test", ci)
        self.assertIn("tests/Test-Installer.ps1", ci)
        self.assertIn("tests/smoke_pixi_sandbox.py", ci)
        # The environment the launcher looks up, installed from the lock.
        self.assertIn("environments: default", ci)
        self.assertIn("locked: true", ci)
        # A runner that blocks the sandbox must say so instead of passing quietly.
        self.assertIn("user namespaces", ci)
        # CI no longer installs the distribution's bubblewrap: the sandbox runs the
        # one the locked environment brings, so a job that installs that environment
        # can probe the binary it will actually use.
        self.assertNotIn("apt-get install -y --no-install-recommends bubblewrap", ci)
        self.assertIn(".pixi/envs/default/bin/bwrap", ci)

    def test_local_inference_smoke_workflow_asks_a_real_assistant(self):
        """The unit suite never loads a model; this job does, and it is guarded.

        A green `pixi run test` says nothing about inference: nothing in it has
        weights or a server. `.github/workflows/llamacpp.yml` is the other half -
        the real server, the real assistant through the sandbox launcher, and real
        answers. It has to run the documented Linux installation first, because the
        AppArmor profile is what lets the pinned bubblewrap start on a hosted
        runner, and it must ask through the project launcher rather than a bare
        `pi`, so a sandbox that cannot start fails the job instead of passing
        quietly. The model it asks for is the one preset `models.ini` marks as
        unit-test only. The Windows half of the same design is a job in ci.yml.
        """
        workflow = (ROOT / ".github/workflows/llamacpp.yml").read_text()
        self.assertIn("runs-on: ubuntu-latest", workflow)
        self.assertIn("pixi r install", workflow)
        self.assertIn("environments: default llamacpp-binary-vulkan", workflow)
        self.assertIn("locked: true", workflow)
        self.assertIn("pixi r start-server", workflow)
        self.assertIn("pixi r restart-server", workflow)
        self.assertIn("pixi r stop-server", workflow)
        self.assertIn("pixi r osint-pi -- --model LFM2.5-230M", workflow)
        # Loading the preset is its own step, before the assistant asks: a cold
        # run downloads the weights, and that wait belongs to an explicit load
        # rather than to the assistant's first request.
        self.assertIn("http://127.0.0.1:8080/models/load", workflow)
        # The server loads a model when a request names it (`--models-autoload` in
        # scripts/server.py) but nothing at startup, so a load can also be asked
        # for explicitly - and the workflow polling for it must not be the thing
        # that loads it.
        controller = (SCRIPTS / "server.py").read_text()
        self.assertIn('"--models-autoload"', controller)
        self.assertNotIn("--no-models-autoload", controller)
        # Never a bare `pi`, and never a flag that would skip the sandbox: that
        # would prove the model wiring and nothing about containment.
        self.assertNotIn("run: pi ", workflow)
        self.assertNotIn("pixi run pi ", workflow)
        self.assertNotIn("--no-sandbox", workflow)
        # A failure has to be explainable: the server log is dumped either way.
        self.assertIn("if: always()", workflow)
        self.assertIn("llama-server.log", workflow)
        # Never end a step with `exit 0`. The job's shell is a *login* shell, and
        # bash then runs `~/.bash_logout` on that exit path: Ubuntu's default file
        # ends with a command that fails on a GitHub runner, so a successful step
        # is reported as "Process completed with exit code 1" with no output. Fail
        # with a nonzero command and let success fall off the end; piping needs
        # `pipefail` because the login shell does not set it.
        commands = [line.strip() for line in workflow.splitlines()]
        self.assertNotIn("exit 0", commands)
        self.assertNotIn("exit 1", commands)
        # One per assistant run, in the two steps that pipe Pi's output to a log.
        self.assertEqual(commands.count("set -o pipefail"), 2)
        # The runner limit is reported, and the case the profile is supposed to
        # fix is a failure instead of a warning.
        self.assertIn("apparmor_restrict_unprivileged_userns", workflow)
        self.assertIn("sandbox", workflow)
        self.assertIn("ok=no", workflow)
        self.assertIn("steps.sandbox.outputs.ok == 'yes'", workflow)
        manifest = tomllib.loads((ROOT / "pixi.toml").read_text())
        for environment in ("default", "llamacpp-binary-vulkan"):
            self.assertIn(environment, manifest["environments"], environment)

    def test_the_windows_native_inference_job(self):
        """The win-64 half is only real on a Windows runner.

        ci.yml installs the inference environment there - the only environment
        that resolves for win-64 - runs the native binary, and starts and stops a
        real server through the same controller the desktop icons run. None of
        that can be proved on Linux, where the recipe builds a different asset and
        the controller takes the POSIX code path.
        """
        ci = (ROOT / ".github/workflows/ci.yml").read_text()
        self.assertIn("runs-on: windows-latest", ci)
        self.assertIn("pixi install --locked -e llamacpp-binary-vulkan", ci)
        self.assertIn("_server start", ci)
        self.assertIn("_server stop", ci)
        # The assistant's own environment must never be installed on Windows: Pi
        # runs inside WSL, and `default` does not resolve for win-64 at all.
        self.assertNotIn("environments: default llamacpp-binary-vulkan", ci)

    def test_the_smoke_preset_says_what_it_is_for(self):
        """The test model is listed in `/model`, so the file has to warn.

        A compliance officer browsing models must not pick a 350M model for a
        real case, and a maintainer reading the workflow must not have to guess
        which entry it uses.
        """
        presets = (ROOT / "models.ini").read_text()
        self.assertIn("[LFM2.5-230M]", presets)
        section = presets.split("[LFM2.5-230M]", 1)[1].split("[", 1)[0]
        self.assertIn("hf = LiquidAI/LFM2.5-350M-GGUF:Q4_K_M", section)
        self.assertRegex(section, r"(?i)unit test(ing)? only")
        # The workflow asks for exactly this preset name.
        self.assertIn(
            "--model LFM2.5-230M",
            (ROOT / ".github/workflows/llamacpp.yml").read_text(),
        )

    def test_the_model_shortlist_is_a_project_file(self):
        """The models worth using change, so the list is a file, not code.

        `scripts/pi-entry.sh` merges it into the assistant's settings on every
        launch, so updating the shortlist means editing one plain JSON file and
        restarting the assistant. The file is part of the checkout and the entry
        script reads it without checking, the same way the launcher trusts the
        checkout it was started from.
        """
        shortlist = json.loads((ROOT / "model-shortlist.json").read_text())
        patterns = shortlist["enabledModels"]
        self.assertTrue(patterns)
        self.assertEqual(
            patterns,
            list(dict.fromkeys(patterns)),
            "the shortlist offers the same model twice",
        )
        for pattern in patterns:
            # Pi matches `provider/modelId`; a bare id is ambiguous across providers.
            self.assertRegex(pattern, r"^[^/\s]+/\S+$", f"{pattern} is not provider/modelId")
        # A local entry has to be a preset the server actually has, and the
        # unit-test model must never be offered to a person doing real work.
        hosted = json.loads((ROOT / "pixi-recipes/pi-home/models.json").read_text())
        presets = {f"llama.cpp/{model['id']}" for model in hosted["providers"]["llama.cpp"]["models"]}
        for pattern in patterns:
            if pattern.split("/", 1)[0] == "llama.cpp":
                self.assertIn(pattern, presets, f"{pattern} has no llama.cpp preset")
        self.assertIn("llama.cpp/MiniCPM5-2B", patterns)
        self.assertNotIn("llama.cpp/LFM2.5-230M", patterns)
        # README is where a user reads the list, so it has to name the file and
        # date the list instead of presenting it as fixed forever.
        for guide in ("AGENTS.md", "docs/development.md", "docs/security.md"):
            self.assertIn("model-shortlist.json", (ROOT / guide).read_text(), guide)
        # The launcher names the program checkout, and the entry script derives
        # the same one from the environment prefix: three levels up.
        launcher = (SCRIPTS / "sandbox.py").read_text()
        self.assertIn(
            '"OSINT_MODEL_SHORTLIST": str(program_mount / MODEL_SHORTLIST_NAME)', launcher
        )
        self.assertIn('MODEL_SHORTLIST_NAME = "model-shortlist.json"', launcher)
        entry = (SCRIPTS / "pi-entry.sh").read_text()
        self.assertIn(
            f'export OSINT_MODEL_SHORTLIST="$checkout/{sandbox.MODEL_SHORTLIST_NAME}"', entry
        )
        self.assertIn('cd -- "$CONDA_PREFIX/../../.."', entry)
        self.assertIn("os.environ['OSINT_MODEL_SHORTLIST']", entry)

    def test_the_model_cache_is_the_default_hugging_face_location(self):
        """Weights go to `~/.cache/huggingface/hub`, and nothing may redirect them.

        They used to sit in the inference state directory, because the controller
        pinned `LLAMA_CACHE` and `XDG_CACHE_HOME` to it: a user who already
        downloads models with another tool then had two copies, and a plain Linux
        checkout kept hundreds of MB under its private state. The fix is to pass
        HOME and no cache variable at all - llama.cpp's own fallback
        (`common/hf-cache.cpp`) is the standard path - and to keep the state
        directory for the pid file and the log. Asserting the absence of the
        redirect is the real test; pinning the path here would only be a second
        copy of llama.cpp's default to keep in step.
        """
        controller = (SCRIPTS / "server.py").read_text()
        for name in (
            '"LLAMA_CACHE":',
            '"HF_HUB_CACHE":',
            '"HUGGINGFACE_HUB_CACHE":',
            '"HF_HOME":',
            '"XDG_CACHE_HOME":',
        ):
            self.assertNotIn(name, controller, name)
        self.assertNotIn('STATE_ROOT / "models"', controller)
        # The smoke workflow caches that same directory, so a cold run does not
        # download the weights again.
        self.assertIn(
            "path: ~/.cache/huggingface/hub",
            (ROOT / ".github/workflows/llamacpp.yml").read_text(),
        )

    def test_installer_parse_test_survives_a_crlf_checkout(self):
        """`*.ps1` is checked out with CRLF, so the Bash check must drop the CR.

        The installer normalizes its embedded script to LF before Bash runs it,
        but the parse test read the here-string straight from the file, so on a
        real checkout Bash choked on the carriage returns and only on Linux -
        the Windows job skips that branch. Both halves are asserted here.
        """
        self.assertIn("*.ps1 text eol=crlf", (ROOT / ".gitattributes").read_text())
        parse_test = (ROOT / "tests/Test-Installer.ps1").read_text()
        self.assertIn('-replace "`r`n", "`n"', parse_test)

    def test_provisioning_installs_files_that_exist(self):
        """The Windows installer copies runtime files by name, so check the names.

        A name that no longer exists only shows up as a failed install on some-
        one else's PC, so the two install loops have to list exactly what is on
        disk, in both directions.
        """
        script = (WINDOWS / "provision-wsl.sh").read_text()
        for variable, directory in (("file", SCRIPTS), ("command", WINDOWS / "launchers")):
            match = re.search(rf"for {variable} in (.*?); do", script, re.S)
            self.assertIsNotNone(match, f"no 'for {variable} in ...' loop")
            listed = set(match.group(1).replace("\\\n", " ").split())
            self.assertEqual(
                listed, {path.name for path in directory.iterdir() if path.is_file()}, variable
            )
        self.assertIn('install -m 755 "$HERE/mount-workspace.py"', script)
        self.assertTrue((WINDOWS / "mount-workspace.py").is_file())

    def test_provisioning_creates_only_inference_state(self):
        """The Windows installer must not pre-create the assistant's state.

        Its agent home lives in the `osint` user's own `~/.local/state/osint-ai`,
        created by the launcher at 0700 like everywhere else. A root-created copy
        under `/var/lib` is how the two deployments drift apart.
        """
        script = (WINDOWS / "provision-wsl.sh").read_text()
        self.assertIn(
            "install -d -m 700 -o osint -g osint /var/lib/osint-ai/server-state", script
        )
        self.assertNotIn("agent-home", script)
        # Model weights are in the standard Hugging Face cache under the osint
        # user's home: not root-owned state under /var/lib.
        self.assertNotIn("models", script)

    def test_apparmor_profile_names_the_pinned_bubblewrap(self):
        """Ubuntu 23.10+ grants `userns` per executable path, so name ours.

        The sandbox runs `<checkout>/.pixi/envs/default/bin/bwrap`. Ubuntu's stock
        /etc/apparmor.d/bwrap covers /usr/bin/bwrap only, so without a profile for
        that path the pinned binary is refused a user namespace and the assistant
        never starts.
        """
        script = (SCRIPTS / "install-apparmor.sh").read_text()
        self.assertIn("$root/.pixi/envs/*/bin/bwrap", script)
        self.assertIn("userns,", script)
        # It elevates with the maintainer's own sudo - never passwordless, never
        # from inside the assistant - and it loads the profile instead of only
        # writing the file, so the change applies to this boot.
        self.assertIn("OSINT_SANDBOX", script)
        self.assertIn("command -v sudo", script)
        self.assertIn("apparmor_parser -r", script)

    def test_provisioning_loads_the_profile_for_the_environment_it_installed(self):
        """One profile script, used by the installer and by `pixi r install`.

        Provisioning used to write its own copy of the profile as root, covering
        /usr/bin/bwrap - the binary nothing runs - and never loaded it. It now runs
        the same script the everyday task runs, after the locked environment has
        been installed and before the acceptance check that starts a real sandbox.
        """
        script = (WINDOWS / "provision-wsl.sh").read_text()
        call = 'bash "$REPO/scripts/install-apparmor.sh"'
        self.assertIn(call, script)
        self.assertLess(script.index("pixi install --locked -e default"), script.index(call))
        self.assertLess(script.index(call), script.index("osint-pi-wsl --version"))
        self.assertNotIn("/etc/apparmor.d/bwrap", script)
        apt = re.search(r"apt-get install -y --no-install-recommends[^\n]*(?:\\\n[^\n]*)*", script)
        self.assertIsNotNone(apt)
        self.assertNotIn("bubblewrap", apt.group(0))
        self.assertIn("apparmor", apt.group(0))

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

    def test_sandbox_paths_are_the_same_in_both_deployments(self):
        """One checkout path, so one set of documented paths.

        The whole checkout is mounted at `/osint-ai` on Linux and on Windows, and
        Pi starts in its `workspace`. If the workspace were mounted on its own,
        Git - which walks up from the working directory looking for `.git` - would
        find nothing and every `git status` in the guidance would be a lie.
        """
        self.assertEqual(CHECKOUT_PATH, "/osint-ai")
        self.assertEqual(WORKSPACE_PATH, "/osint-ai/workspace")
        self.assertEqual(SKILLS_PATH, "/osint-ai/workspace/.agents/skills")
        self.assertEqual(sandbox.WORKSPACE_SUBDIR, "workspace")
        self.assertTrue(sandbox.WORKSPACE_MOUNT.is_relative_to(sandbox.AGENT_MOUNT))
        # The read-only program mount is a different tree, not inside the checkout.
        self.assertEqual(PROGRAM_PATH, "/opt/osint-ai/project")
        self.assertFalse(sandbox.PROGRAM_MOUNT.is_relative_to(sandbox.AGENT_MOUNT))

    def test_skill_discovery_and_guidance(self):
        settings = json.loads((ROOT / "pixi-recipes/pi-home/settings.json").read_text())
        self.assertEqual(settings["skills"], [SKILLS_PATH])
        # No `llamaSettings` block any more: that was pi-llama-cpp's configuration,
        # and Pi's built-in llama.cpp provider reads `LLAMA_BASE_URL` instead.
        self.assertNotIn("llamaSettings", settings)
        # The models Pi may pick from are generated at launch from a shipped
        # template, because the address of the server is a deployment detail.
        template = json.loads((ROOT / "pixi-recipes/pi-home/models.json").read_text())
        provider = template["providers"]["llama.cpp"]
        self.assertEqual(provider["baseUrl"], "http://127.0.0.1:8080/v1")
        self.assertEqual(provider["api"], "openai-completions")
        self.assertEqual(
            [model["id"] for model in provider["models"]], ["MiniCPM5-2B", "LFM2.5-230M"]
        )
        build = (ROOT / "pixi-recipes/pi-home/build.sh").read_text()
        self.assertIn('cp -a models.json "${PREFIX}/home/.pi/agent/models.json"', build)
        entry = (SCRIPTS / "pi-entry.sh").read_text()
        self.assertIn('exec pi "${pi_flags[@]}" "${PI_ARGS[@]}"', entry)
        self.assertIn('pi_flags=(--skill "$skills" --no-context-files)', entry)
        self.assertIn(f"OSINT_SKILLS_DIR:-{SKILLS_PATH}", entry)
        # The guide is named from the same mount path the launcher exports.
        self.assertIn(f"OSINT_WORKSPACE:-{WORKSPACE_PATH}", entry)
        self.assertIn('--append-system-prompt "$guide"', entry)
        # The launcher exports the same value, so the guidance and the mounts
        # cannot drift from each other.
        launcher = (SCRIPTS / "sandbox.py").read_text()
        self.assertIn(f'"OSINT_SKILLS_DIR": str(SKILLS_MOUNT)', launcher)
        for guidance, expected in [
            ("workspace/AGENTS.md", f"{SKILLS_PATH}/<skill-name>/SKILL.md"),
            ("AGENTS.md", "workspace/.agents/skills"),
        ]:
            self.assertIn(expected, (ROOT / guidance).read_text())
        # The workspace guide forbids the conventional but unreviewable locations.
        workspace_guide = (ROOT / "workspace/AGENTS.md").read_text()
        for forbidden in ("~/.pi", "~/.agents", ".pi/skills"):
            self.assertIn(forbidden, workspace_guide)
        # Reminders about uncommitted work are documented where the agent reads them.
        self.assertIn("git status", workspace_guide)
        # There is one guide, and it is in the checkout the agent works in. The
        # packaged Pi home must not carry a second copy that can drift from it,
        # and the launcher must not put one in the agent home.
        self.assertFalse((ROOT / "pixi-recipes/pi-home/AGENTS.md").exists())
        self.assertNotIn("AGENTS.md", (ROOT / "pixi-recipes/pi-home/build.sh").read_text())
        self.assertNotIn("agent/AGENTS.md", (SCRIPTS / "sandbox.py").read_text())

    def test_package_listing_guidance(self):
        """The sandbox has no `pixi` and no `conda`, so the guidance must name the
        records the environment itself leaves behind.

        `pixi list`, `pixi ls` and `conda list` are `command not found` for the
        assistant, and `pip list` reports only the Python libraries, not the
        command-line tools. `$CONDA_PREFIX` is exported by the launcher, so
        `$CONDA_PREFIX/conda-meta` is the list that actually works in both
        deployments.
        """
        guide = (ROOT / "workspace/AGENTS.md").read_text()
        self.assertIn("$CONDA_PREFIX/conda-meta", guide)
        self.assertIn("$CONDA_PREFIX/bin", guide)
        self.assertIn("importlib.metadata", guide)
        # The commands that do not work are named so the agent does not retry them.
        for broken in ("pixi list", "conda list", "pip list"):
            self.assertIn(broken, guide)
        launcher = (SCRIPTS / "sandbox.py").read_text()
        self.assertIn('"CONDA_PREFIX": str(env_prefix)', launcher)

    def test_the_workspace_guide_keeps_the_agent_on_staging(self):
        """One development branch, checked before the agent touches anything.

        The agent commits in the checkout the user publishes from, so it must
        never write to `main`. Guidance lets it switch `main` -> `staging` and
        merge the published `main` back into `staging`, and nothing else.
        """
        guide = (ROOT / "workspace/AGENTS.md").read_text()
        for needle in (
            "git status --porcelain=v1 -b",
            "git checkout staging",
            "git fetch origin",
            "git rev-list --count staging..origin/main",
            "git merge origin/main",
            "git merge --abort",
        ):
            self.assertIn(needle, guide, needle)
        # A conflict is the maintainer's call, never the agent's, and the agent
        # never publishes the development branch.
        self.assertIn("do not resolve it", guide)
        self.assertIn("Never merge `staging` into `main`", guide)
        self.assertIn("`git push`, or ask for GitHub credentials", guide)
        # The old blanket ban on branch switching would forbid the required
        # switch, so it must not come back as the only rule.
        self.assertNotIn("`git checkout <branch>`", guide)

    def test_no_document_or_skill_keeps_the_old_workspace_mount(self):
        """`/workspace` no longer exists in the sandbox; nothing may name it.

        A leftover absolute `/workspace/...` in a skill or a guide sends the
        assistant at a path that is not there, and a Linux test run would not
        notice. `/osint-ai/workspace/...` and the relative `workspace/...` are
        both fine, so only a `/workspace` that is not under the checkout fails.
        """
        stale = re.compile(r"(?<![\w./-])/workspace")
        for path in [
            ROOT / "README.md",
            ROOT / "AGENTS.md",
            ROOT / "workspace/AGENTS.md",
            ROOT / "workspace/.agents/README.md",
            ROOT / "pixi-recipes/pi-home/settings.json",
            *sorted((ROOT / "workspace/.agents/skills").glob("*/SKILL.md")),
            *sorted((ROOT / "workspace/.agents/skills").glob("*/scripts/*")),
            *sorted((ROOT / "docs").glob("*.md")),
            *SCRIPTS.iterdir(),
            *WINDOWS.iterdir(),
            *sorted((WINDOWS / "launchers").iterdir()),
        ]:
            if not path.is_file():
                continue
            with self.subTest(file=str(path.relative_to(ROOT))):
                text = path.read_text()
                match = stale.search(text)
                if match:
                    self.fail(
                        f"{path.relative_to(ROOT)} names the removed mount in "
                        f"{text[max(0, match.start() - 60):match.end() + 40]!r}"
                    )

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
        # Prose may wrap across lines without changing what the reader sees.
        readme = " ".join((ROOT / "README.md").read_text().split())
        for needle in (
            "github.com/signup",
            "desktop.github.com",
            "Commit",
            "Push",
            "Pull",
            "openrouter.ai",
            "/login",
            "Sign in with an API key",
            "/scoped-models",
            "/model",
            # Pi's built-in llama.cpp provider replaced pi-llama-cpp and its
            # `/models` command; the guide names both the model list and the
            # command that loads a model.
            "/llama",
            "Start llama.cpp",
            "/thinking",
            "/reload",
            "/quit",
            "/new",
            "/resume",
            "/tree",
            r"workspace\AGENTS.md",
            r"workspace\.agents\skills\<name>\SKILL.md",
            "skill",
        ):
            self.assertIn(needle, readme, needle)
        # A Linux user gets a short section, not a script to run.
        for needle in ("Install on Linux", "pixi install --locked -e default", "pixi r osint-pi"):
            self.assertIn(needle, readme, needle)
        # The installer moved to windows/; stale paths must not come back.
        self.assertIn(r"windows\Install.cmd", readme)
        self.assertNotIn(r"wsl\Install.cmd", readme)
        # Deliberately not taught to beginners: branches and pull requests.
        self.assertNotIn("git branch", readme.lower())
        self.assertNotIn("pull request", readme.lower())

    def test_readme_local_links_resolve(self):
        """Catch stale contents anchors and broken links to maintainer guides."""
        readme = ROOT / "README.md"
        links = re.findall(r"\[[^\]\n]+\]\(([^)\s]+)\)", readme.read_text())
        self.assertTrue(links, "the beginner guide needs navigation links")
        for link in links:
            if re.match(r"[a-z][a-z0-9+.-]*:", link):
                continue
            with self.subTest(link=link):
                path, _, fragment = link.partition("#")
                target = ROOT / path if path else readme
                self.assertTrue(target.is_file(), f"missing link target: {link}")
                if fragment:
                    # These guides use ordinary Markdown headings, without
                    # duplicate titles or custom HTML anchors.
                    text = re.sub(r"```.*?```", "", target.read_text(), flags=re.S)
                    headings = re.findall(r"^#{1,6} +(.+)$", text, re.M)
                    anchors = {
                        re.sub(r"[^\w -]", "", heading.lower()).replace(" ", "-")
                        for heading in headings
                    }
                    self.assertIn(fragment, anchors, f"missing heading: {link}")

    def test_shell_syntax(self):
        launchers = list((WINDOWS / "launchers").iterdir())
        for file in [*SCRIPTS.glob("*.sh"), *WINDOWS.glob("*.sh"), *launchers]:
            with self.subTest(file=file):
                subprocess.run(["/bin/bash", "-n", str(file)], check=True)

    def test_windows_bootstrap_is_non_destructive(self):
        script = (WINDOWS / "Install.ps1").read_text()
        self.assertNotIn("--unregister", script)
        self.assertNotIn("reset --hard", script)
        self.assertNotIn("git pull", script)
        # The checkout the assistant commits from is put on the one development
        # branch, and only ever fast-forwarded: unpublished work survives, and a
        # divergence is reported instead of resolved.
        self.assertIn("remote set-branches origin '*'", script)
        self.assertIn("checkout --quiet staging", script)
        self.assertIn("checkout --quiet -b staging origin/staging", script)
        self.assertIn("merge --ff-only origin/staging", script)
        self.assertNotIn("checkout main", script)
        self.assertNotIn("git switch", script)
        self.assertEqual(script.count("sync_staging || exit 1"), 2, "every path must sync")
        self.assertIn("--no-distribution", script)
        self.assertIn("Get-FileHash", script)
        self.assertIn("Restart Windows", script)
        self.assertIn("ConvertTo-ShellLiteral", script)
        # Third-party terminal: pinned, checksummed, optional, and never bundled.
        self.assertIn("$MobaXtermSha256", script)
        self.assertIn("$SkipMobaXterm", script)
        self.assertIn("/usr/local/bin/osint-terminal", script)
        self.assertIn("/mnt/osint-ai/windows/provision-wsl.sh", script)

    def test_the_inference_recipe_ships_the_vulkan_build(self):
        """One release asset per platform, checked against its published hash.

        The recipe used to build a CUDA-only Linux package with rattler-build
        downloading the asset; llama.cpp now runs on Vulkan, on Windows natively and
        on Linux inside the checkout, and Windows has no tar to extract a tar.gz
        with, so both asset shapes have to be handled and both hashes pinned.
        """
        recipe = (ROOT / "pixi-recipes/llama-cpp-binary/recipe.yaml").read_text()
        variants = (ROOT / "pixi-recipes/llama-cpp-binary/variants.yaml").read_text()
        self.assertIn("backend: [\"cpu\", \"vulkan\"]", variants)
        self.assertNotIn("cuda", variants)
        # The published digest of each release asset, one per platform; a wrong
        # value fails the install instead of installing something else.
        self.assertIn(
            "0056cbd32440e646bbe8e3a3f797bf2aef15c9dd5ebf77b9b19830434c1ae541", recipe
        )
        self.assertIn(
            "e1eaddcde761b1f839b9c6d5924b97f2698fba22068ca3b63f129c3caf55b88f", recipe
        )
        self.assertIn("llama-${{ version }}-bin-ubuntu-vulkan-x64.tar.gz", recipe)
        self.assertIn("llama-${{ version }}-bin-win-vulkan-x64.zip", recipe)
        self.assertIn("fork: ggml-org/llama.cpp", recipe)
        # No asset of a fork: the fork's preset options are not implemented on
        # the build this project ships (see the recipe's own comment).
        self.assertNotIn("beellama-${{ version }}", recipe)
        self.assertIn("sha256:", recipe)
        # Windows extracts a zip with build.bat; the recipe resolves the script by
        # extension-less name so one recipe covers both platforms.
        self.assertIn("file: build", recipe)
        self.assertTrue((ROOT / "pixi-recipes/llama-cpp-binary/build.bat").is_file())
        self.assertTrue((ROOT / "pixi-recipes/llama-cpp-binary/build.sh").is_file())
        manifest = tomllib.loads((ROOT / "pixi.toml").read_text())
        dependency = manifest["feature"]["llamacpp-binary-vulkan"]["dependencies"]["llama-cpp"]
        self.assertEqual(dependency["flags"], ["vulkan"])
        self.assertEqual(dependency["path"], "pixi-recipes/llama-cpp-binary")

    def test_the_model_presets_only_use_options_the_build_accepts(self):
        """An option the runtime does not know stops the server from starting.

        The router validates every preset key and refuses the whole file over an
        unknown one (`option 'kv-tail-tokens' not recognized in preset`). The
        presets therefore may not name a fork-only option: the runtime is
        upstream llama.cpp, whose KV cache types are f32/f16/bf16/q8_0/q4_0/
        q4_1/iq4_nl/q5_0/q5_1 - no q3_0, and no exact BF16 KV tail.
        """
        presets = (ROOT / "models.ini").read_text()
        self.assertNotIn("kv-tail-tokens", presets)
        self.assertNotIn("q3_0", presets)
        # Every preset quantizes K and V, and to the same supported type.
        bodies = presets.split("[*]", 1)[1]
        self.assertEqual(bodies.count("cache-type-k = "), bodies.count("cache-type-v = "))
        self.assertGreaterEqual(bodies.count("cache-type-v = q4_0"), 2)

    def test_the_generated_model_list_matches_the_server_presets(self):
        """The two lists are hand-written in two places, so they have to agree.

        `models.ini` is what the llama.cpp server serves; `models.json` is what Pi
        offers in `/model`. Declaring models in `models.json` replaces Pi's own
        discovery of the router, so the section names and the context size are
        written twice and have to be kept in step: a preset the assistant cannot
        name, or a name the server does not know, is a model that fails to load with
        a confusing message. The presets are matched whole: the template must not
        invent a model either.

        What is deliberately not written twice is sampling. The server starts every
        request from the model's own defaults and overrides only the fields the
        request names (`tools/server/server-schema.cpp`: "Sampling parameter defaults
        are loaded from the global server context"), and Pi sends no sampling field
        for a model that declares none. A copy here could only drift from the
        settings the preset already applies.
        """
        presets = (ROOT / "models.ini").read_text()
        sections = [name for name in re.findall(r"^\[([^\]]+)\]$", presets, re.M) if name != "*"]
        template = json.loads((ROOT / "pixi-recipes/pi-home/models.json").read_text())
        models = template["providers"]["llama.cpp"]["models"]
        self.assertEqual([model["id"] for model in models], sections)
        for model in models:
            section = presets.split(f"[{model['id']}]", 1)[1].split("[", 1)[0]
            context = re.search(r"^ctx-size = (\d+)$", section, re.M)
            self.assertEqual(int(context.group(1)), model["contextWindow"], model["id"])
            self.assertNotIn("samplingParams", model, model["id"])

    def test_the_installer_installs_and_checks_native_inference(self):
        """The Windows half of the inference design, in the trusted installer.

        Pixi is installed natively to build the llama.cpp environment in the Windows
        checkout; the environment is installed from the lock; WSL reaching a server
        on Windows needs a firewall rule, which is the one extra permission prompt;
        and the installer proves that path by starting the server and asking it from
        inside the distribution instead of assuming it works.
        """
        script = (WINDOWS / "Install.ps1").read_text()
        self.assertIn("pixi-x86_64-pc-windows-msvc.zip", script)
        self.assertIn("$PixiSha256", script)
        self.assertIn(
            "'install', '--locked', '-e', 'llamacpp-binary-vulkan', '--manifest-path', $manifest",
            script,
        )
        self.assertIn("'-e', 'llamacpp-binary-vulkan', '--manifest-path', $manifest, '_server'", script)
        # One rule, bound to the WSL interface and the local subnet, so the rest of
        # the network still cannot reach the model server. Removing it first keeps a
        # rerun idempotent, and an unchanged rule needs no prompt at all.
        self.assertIn("New-NetFirewallRule", script)
        self.assertIn("Remove-NetFirewallRule", script)
        self.assertIn("-Direction Inbound -Action Allow -Protocol TCP -LocalPort 8080", script)
        self.assertIn("-RemoteAddress LocalSubnet", script)
        self.assertIn("vEthernet (WSL*", script)
        self.assertIn("Get-NetFirewallInterfaceFilter", script)
        self.assertIn("-Verb RunAs", script)
        # The acceptance check asks the launcher for the address, and asks the real
        # server from inside WSL - loopback is a different machine there.
        self.assertIn("Get-InferenceReachability", script)
        self.assertIn("sandbox.py --wsl --inference-url", script)
        # Both desktop icons run the same task the Linux deployment runs.
        self.assertIn("'Start llama.cpp.lnk'", script)
        self.assertIn("'Stop llama.cpp.lnk'", script)
        self.assertIn("_server $action", script)
        # One reviewed pixi release for both sides of the installation.
        windows_pin = re.search(r"\$PixiVersion = '([\d.]+)'", script).group(1)
        wsl_pin = re.search(r"^PIXI_VERSION=([\d.]+)$", (WINDOWS / "provision-wsl.sh").read_text(), re.M)
        self.assertEqual(windows_pin, wsl_pin.group(1))

    def test_wsl_provisioning_leaves_inference_to_windows(self):
        """The Windows deployment runs llama.cpp on Windows, not inside WSL.

        The same environment still exists for a plain Linux install and can be
        installed on demand there, but provisioning does not spend hundreds of MB
        inside the distribution on a server the assistant never talks to. What the
        WSL side keeps is the ability to say whether the Windows one answers.
        """
        provision = (WINDOWS / "provision-wsl.sh").read_text()
        self.assertNotIn("pixi install", provision.split("-e default", 1)[1])
        self.assertNotIn("CONDA_OVERRIDE_CUDA", provision)
        self.assertNotIn("CONDA_OVERRIDE_CUDA", (SCRIPTS / "update-project.sh").read_text())
        check = (SCRIPTS / "install-check.sh").read_text()
        self.assertIn("--wsl --inference-url", check)
        self.assertIn("Start llama.cpp", check)
        terminal = (WINDOWS / "launchers/osint-terminal").read_text()
        self.assertIn("--wsl --inference-url", terminal)
        self.assertIn("Start llama.cpp", terminal)
        # It must not quietly run a second, useless server inside the distribution.
        self.assertNotIn("restart-server", terminal)


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
            prefix = root / ".pixi" / "envs" / sandbox.ENV_NAME
            bundled = prefix / "home/.pi/agent"
            (bundled / "npm").mkdir(parents=True)
            for name in ("settings.json", "osint-defaults.json", "keybindings.json"):
                (bundled / name).write_text("{}")
            (bundled / "models.json").write_text(json.dumps({"providers": {}}))
            (bundled.parent / "web-search.json").write_text("{}")
            self.shortlist(root, ["llama.cpp/MiniCPM5-2B"])
            skills = root / "workspace-skills"
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "AGENTS.md").write_text("workspace guide")
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
                OSINT_WORKSPACE=str(workspace),
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
            self.assertEqual(
                args,
                [
                    "--skill",
                    str(skills),
                    "--no-context-files",
                    "--append-system-prompt",
                    str(workspace / "AGENTS.md"),
                    *prompts,
                ],
            )
            self.assertTrue(skills.is_dir(), "the skills directory is created if missing")
            self.assertEqual(stdin, "terminal input")
            self.assertEqual(
                json.loads((live / "settings.json").read_text())["defaultProvider"], "openrouter"
            )
            self.assertEqual(
                json.loads((live / "auth.json").read_text()), {"preserve": "user login"}
            )

    def test_entry_loads_the_workspace_guide_and_no_other_AGENTS_md(self):
        """Pi walks up from its working directory looking for a context file, and
        nothing in Pi limits that walk, so the checkout root's own `AGENTS.md` -
        the maintainer's file - would be loaded next to the assistant's guide.

        Discovery is disabled and the workspace guide is named explicitly. The
        alternative, shadowing the root file with a read-only bind mount, makes
        `git status` report `AGENTS.md` as modified in the checkout the assistant
        is allowed to commit from, and a commit would write an empty file over
        the maintainer's instructions.
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            (home / ".pi/agent").mkdir(parents=True)
            prefix, _bundled = self.bundled_prefix(root)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "AGENTS.md").write_text("the assistant's rules")
            env = {"OSINT_WORKSPACE": str(workspace)}
            result = self.run_entry(root, prefix, home, env=env, print_argv=True)
            args = json.loads(result.stdout)
            self.assertIn("--no-context-files", args)
            self.assertEqual(args[args.index("--append-system-prompt") + 1], str(workspace / "AGENTS.md"))
            # Nothing else is handed to Pi as instructions, and the maintainer's
            # file is not named or shadowed anywhere.
            self.assertEqual(args.count("--append-system-prompt"), 1)
            self.assertNotIn(str(root / "AGENTS.md"), args)

            # A checkout without the guide still gets no ancestor context file,
            # and the absence is reported instead of silently steering the agent
            # with the maintainer's rules.
            (workspace / "AGENTS.md").unlink()
            quiet = self.run_entry(root, prefix, home, env=env)
            self.assertIn("without its instructions", quiet.stderr)

    def run_entry(self, root: Path, prefix: Path, home: Path, env=None, print_argv=False):
        bindir = root / "bin"
        bindir.mkdir(parents=True, exist_ok=True)
        fake = bindir / "pi"
        if print_argv:
            fake.write_text("#!/usr/bin/python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n")
        else:
            fake.write_text("#!/bin/sh\nexit 0\n")
        fake.chmod(0o755)
        merged = dict(
            os.environ,
            HOME=str(home),
            CONDA_PREFIX=str(prefix),
            PATH=str(bindir) + ":/usr/bin:/bin",
            OSINT_SANDBOX="1",
            OSINT_SKILLS_DIR=str(root / "workspace-skills"),
            **(env or {}),
        )
        return subprocess.run(
            ["/bin/bash", str(SCRIPTS / "pi-entry.sh")],
            capture_output=True,
            text=True,
            env=merged,
            check=True,
        )

    def bundled_prefix(self, root: Path, prefix=None):
        """A stand-in for the installed environment, with the checkout above it.

        `pi-entry.sh` finds the checkout that owns `model-shortlist.json` by going
        three levels up from the environment prefix, so the default prefix is the
        real layout - `<checkout>/.pixi/envs/<name>` - and the checkout holds the
        shortlist the entry script expects to find.
        """
        prefix = Path(prefix) if prefix else root / ".pixi" / "envs" / sandbox.ENV_NAME
        bundled = prefix / "home/.pi/agent"
        (bundled / "npm").mkdir(parents=True)
        (bundled / "keybindings.json").write_text("{}")
        (bundled / "settings.json").write_text(json.dumps({"packages": ["pi-example@1.0.0"]}))
        (bundled / "osint-defaults.json").write_text(json.dumps({"skills": [SKILLS_PATH]}))
        # The template the launcher rewrites the server address into on every start.
        (bundled / "models.json").write_text(
            json.dumps(
                {
                    "providers": {
                        "llama.cpp": {
                            "baseUrl": "http://127.0.0.1:8080/v1",
                            "api": "openai-completions",
                            "apiKey": "local",
                            "models": [{"id": "MiniCPM5-2B"}],
                        }
                    }
                }
            )
        )
        (bundled.parent / "web-search.json").write_text("{}")
        self.shortlist(root, ["llama.cpp/MiniCPM5-2B"])
        return prefix, bundled

    def shortlist(self, root: Path, patterns):
        """Write the checkout's `model-shortlist.json`.

        The file is part of the checkout, so the entry script reads it without
        asking whether it is there.
        """
        file = root / sandbox.MODEL_SHORTLIST_NAME
        file.write_text(json.dumps({"enabledModels": patterns}))
        return file

    def test_entry_points_the_models_at_the_deployment_server(self):
        """The model list is generated, because the address of the server moves.

        Plain Linux serves on loopback; the Windows deployment serves on the
        Windows host, outside WSL, and WSL hands that address out anew every time
        it restarts. A generated file is the only one that cannot go stale.
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            home.mkdir()
            prefix, _ = self.bundled_prefix(root)
            self.run_entry(
                root, prefix, home, env={"OSINT_INFERENCE_URL": "http://172.30.96.1:8080"}
            )
            live = home / ".pi/agent/models.json"
            models = json.loads(live.read_text())
            self.assertEqual(
                models["providers"]["llama.cpp"]["baseUrl"], "http://172.30.96.1:8080/v1"
            )
            self.assertEqual(
                models["providers"]["llama.cpp"]["models"], [{"id": "MiniCPM5-2B"}]
            )
            self.assertEqual(stat.S_IMODE(live.stat().st_mode), 0o600)
            # Without the launcher's variable - a direct run, or a plain Linux
            # checkout - the address is loopback rather than nothing.
            self.run_entry(root, prefix, home)
            models = json.loads(live.read_text())
            self.assertEqual(
                models["providers"]["llama.cpp"]["baseUrl"], "http://127.0.0.1:8080/v1"
            )

    def test_entry_adds_the_shortlist_and_keeps_the_models_the_user_saved(self):
        """The shortlist is an offer, not a replacement.

        Pi keeps the models the person picked with `/model` in the same
        `enabledModels` list, so a launcher that rewrote it would silently throw
        away their choice - and a launcher that ran a second time over the
        settings it had just written would add the same model twice.
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            live = home / ".pi/agent"
            live.mkdir(parents=True)
            (live / "settings.json").write_text(
                json.dumps(
                    {
                        "enabledModels": [
                            "anthropic/claude-opus-4-8",
                            "openrouter/xiaomi/mimo-v2.6-pro",
                        ],
                        "theme": "keep me",
                    }
                )
            )
            prefix, _bundled = self.bundled_prefix(root)
            self.shortlist(
                root,
                [
                    "openrouter/deepseek/deepseek-v4.1-flash",
                    "openrouter/xiaomi/mimo-v2.6-pro",
                    "llama.cpp/MiniCPM5-2B",
                ],
            )
            self.run_entry(root, prefix, home)
            settings = json.loads((live / "settings.json").read_text())
            self.assertEqual(
                settings["enabledModels"],
                [
                    # What the user had stays first, in the user's own spelling.
                    "anthropic/claude-opus-4-8",
                    "openrouter/xiaomi/mimo-v2.6-pro",
                    "openrouter/deepseek/deepseek-v4.1-flash",
                    "llama.cpp/MiniCPM5-2B",
                ],
            )
            self.assertEqual(settings["theme"], "keep me", "a user setting was overwritten")
            # A second launch adds nothing: the list it wrote is already complete.
            self.run_entry(root, prefix, home)
            self.assertEqual(
                json.loads((live / "settings.json").read_text())["enabledModels"],
                settings["enabledModels"],
                "the shortlist was appended again",
            )
            self.assertEqual(stat.S_IMODE((live / "settings.json").stat().st_mode), 0o600)

    def test_entry_reads_the_shortlist_from_the_checkout_that_owns_the_environment(self):
        """The file belongs to the checkout, and the environment prefix names it.

        The prefix is always `<checkout>/.pixi/envs/<name>`, so the checkout that
        carries `model-shortlist.json` is three levels above it: the read-only
        program mount in WSL, the checkout itself on plain Linux. The entry script
        needs nothing else passed in, and it does not ask whether the file exists -
        a checkout is expected to have it, like `pixi.toml`.
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            home.mkdir()
            prefix, _bundled = self.bundled_prefix(root)
            self.assertEqual(prefix, root / ".pixi" / "envs" / sandbox.ENV_NAME)
            self.shortlist(root, ["openrouter/z-ai/glm-5.3-flash", "llama.cpp/MiniCPM5-2B"])
            self.run_entry(root, prefix, home)
            settings = json.loads((home / ".pi/agent/settings.json").read_text())
            self.assertEqual(
                settings["enabledModels"],
                ["openrouter/z-ai/glm-5.3-flash", "llama.cpp/MiniCPM5-2B"],
            )

    def test_entry_repairs_a_stale_npm_link_and_stale_paths(self):
        """The agent home outlives the mount layout, so leftovers must be repaired.

        An earlier launcher linked `~/.pi/agent/npm` at the old program mount.
        Plain Linux no longer mounts that path, so the link dangles and Node
        follows it when creating the npm project: `ENOENT ... mkdir
        '/home/osint/.pi/agent/npm'`. A `skills` path saved by the old layout is
        the same kind of fossil.
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            live = home / ".pi/agent"
            live.mkdir(parents=True)
            (live / "npm").symlink_to(
                "/opt/osint-ai/project/home/.pi/agent/npm", target_is_directory=True
            )
            (live / "settings.json").write_text(
                json.dumps({"skills": ["/workspace/.agents/skills"], "theme": "keep me"})
            )
            prefix, bundled = self.bundled_prefix(root)
            self.run_entry(root, prefix, home)
            npm = live / "npm"
            self.assertTrue(npm.is_symlink(), "the stale link was not replaced")
            self.assertEqual(npm.resolve(), (bundled / "npm").resolve())
            settings = json.loads((live / "settings.json").read_text())
            self.assertEqual(settings["skills"], [SKILLS_PATH])
            self.assertEqual(settings["packages"], ["pi-example@1.0.0"])
            self.assertEqual(settings["theme"], "keep me", "user settings were overwritten")

    def test_entry_leaves_a_real_npm_directory_alone(self):
        """A user who installed packages into the home keeps them."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            live = home / ".pi/agent"
            (live / "npm").mkdir(parents=True)
            (live / "npm" / "package.json").write_text('{"preserved": true}')
            prefix, bundled = self.bundled_prefix(root)
            self.run_entry(root, prefix, home)
            npm = live / "npm"
            self.assertFalse(npm.is_symlink())
            self.assertEqual((npm / "package.json").read_text(), '{"preserved": true}')

    def test_entry_moves_aside_a_stale_agent_home_AGENTS_md(self):
        """The guidance is `workspace/AGENTS.md`, so an old copy must not steer Pi.

        Pi reads `~/.pi/agent/AGENTS.md` as user instructions. The package no
        longer ships one and the launcher no longer mounts one, so a copy left by
        an older version - or the 0-byte placeholder bubblewrap left when its
        mount source disappeared - would keep naming paths that no longer exist.
        It is moved aside, not deleted: the home is the user's directory.
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            live = home / ".pi/agent"
            live.mkdir(parents=True)
            fossil = live / "AGENTS.md"
            fossil.write_text("skills live in /workspace/.agents/skills")
            prefix, _bundled = self.bundled_prefix(root)
            self.run_entry(root, prefix, home)
            self.assertFalse(fossil.exists(), "the stale guidance is still loaded by Pi")
            self.assertEqual(
                (live / "AGENTS.md.stale").read_text(),
                "skills live in /workspace/.agents/skills",
                "the leftover was deleted instead of kept",
            )
            # A later launch removes what it left in the home, and keeps the copy.
            fossil.write_text("")
            self.run_entry(root, prefix, home)
            self.assertFalse(fossil.exists())
            self.assertEqual(
                (live / "AGENTS.md.stale").read_text(),
                "skills live in /workspace/.agents/skills",
            )

    def test_entry_keeps_the_pi_directories_private(self):
        """`~/.pi/agent/auth.json` is written by Pi into these directories."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            home.mkdir()
            prefix, _bundled = self.bundled_prefix(root)
            self.run_entry(root, prefix, home)
            for directory in (home / ".pi", home / ".pi" / "agent"):
                self.assertEqual(
                    stat.S_IMODE(directory.stat().st_mode), 0o700, f"{directory} is not private"
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


class InstallCheckTests(unittest.TestCase):
    """`pixi r install` has to prove the pinned bubblewrap may run a sandbox."""

    def fixture(self):
        temp = tempfile.TemporaryDirectory(prefix="osint install-check ")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        shutil.copytree(SCRIPTS, root / "scripts")
        (root / ".git").mkdir()
        (root / "workspace/.agents/skills").mkdir(parents=True)
        bindir = root / f".pixi/envs/{sandbox.ENV_NAME}/bin"
        bindir.mkdir(parents=True)
        (bindir / "pi").write_text("#!/bin/sh\n")
        return root

    def run_check(self, root):
        return subprocess.run(
            ["/bin/bash", str(root / "scripts/install-check.sh")],
            capture_output=True,
            text=True,
            check=False,
            env={key: value for key, value in os.environ.items() if key != "OSINT_SANDBOX"}
            | {"OSINT_PROJECT_ROOT": str(root)},
        )

    def test_a_checkout_without_the_pinned_bubblewrap_is_reported(self):
        root = self.fixture()
        result = self.run_check(root)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("MISSING", result.stdout)
        # It names the binary the launcher would run, not a package to guess at.
        self.assertIn(str(root / sandbox.BWRAP_SUBPATH), result.stdout)

    def test_a_bubblewrap_that_cannot_start_a_sandbox_points_at_the_fix(self):
        """Present and executable is not enough: it has to be allowed to unshare."""
        root = self.fixture()
        bwrap = root / sandbox.BWRAP_SUBPATH
        bwrap.write_text("#!/bin/sh\necho 'bwrap: Operation not permitted' >&2\nexit 1\n")
        bwrap.chmod(0o755)
        result = self.run_check(root)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("bwrap: Operation not permitted", result.stdout)
        # The check names the binary's own failure and the fix for this machine:
        # the AppArmor profile where Ubuntu restricts user namespaces, and the
        # honest "this machine cannot sandbox" everywhere else.
        self.assertIn("user namespace", result.stdout)
        check = (SCRIPTS / "install-check.sh").read_text()
        self.assertIn("pixi r install-apparmor", check)
        self.assertIn("refuses unprivileged user namespaces outright", check)

    def test_local_inference_is_reported_as_optional(self):
        """A checkout without llama.cpp is a working checkout, not a broken one."""
        root = self.fixture()
        result = self.run_check(root)
        self.assertIn("Local inference (optional)", result.stdout)
        lines = [line for line in result.stdout.splitlines() if "llama.cpp is not installed" in line]
        self.assertTrue(lines, result.stdout)
        for line in lines:
            self.assertNotIn("MISSING", line)
            self.assertIn("pixi r start-server", line)

    def test_an_installed_inference_environment_is_reported_with_its_port(self):
        root = self.fixture()
        binary = root / ".pixi/envs/llamacpp-binary-vulkan/bin/llama-server"
        binary.parent.mkdir(parents=True)
        binary.write_text("#!/bin/sh\n")
        binary.chmod(0o755)
        result = self.run_check(root)
        self.assertIn(str(binary), result.stdout)
        self.assertIn("127.0.0.1:8080", result.stdout)

    def test_it_refuses_to_run_inside_the_assistant(self):
        result = subprocess.run(
            ["/bin/bash", str(SCRIPTS / "install-check.sh")],
            capture_output=True,
            text=True,
            check=False,
            env=os.environ | {"OSINT_SANDBOX": "1"},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("terminal", result.stderr)

    def test_a_ready_checkout_is_reported_ready(self):
        """Run the real check against this checkout, where a sandbox is possible."""
        if PINNED_BWRAP is None:
            self.skipTest(
                f"bubblewrap is not installed in {ROOT}; run: "
                f"pixi install --locked -e {sandbox.ENV_NAME}"
            )
        result = self.run_check(ROOT)
        if result.returncode:
            self.skipTest("unprivileged bubblewrap unavailable here: " + result.stdout.strip())
        self.assertIn("pinned by pixi.lock", result.stdout)
        self.assertNotIn("MISSING", result.stdout)


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
        # The launcher runs the bubblewrap of the checkout's own environment, so the
        # fixture points at the real one rather than inventing a binary: the
        # integration tests then exercise the same executable a session would use.
        bwrap = self.project / sandbox.BWRAP_SUBPATH
        if PINNED_BWRAP is None:
            bwrap.write_text("#!/bin/sh\nexit 127\n")
            bwrap.chmod(0o755)
        else:
            bwrap.symlink_to(PINNED_BWRAP)
            # bubblewrap finds its own libraries next to the binary it was started
            # from, so a symlinked one needs that directory too.
            (self.project / f".pixi/envs/{sandbox.ENV_NAME}/lib").symlink_to(
                PINNED_BWRAP.parent.parent / "lib"
            )
        bundled_home = self.project / f".pixi/envs/{sandbox.ENV_NAME}/home/.pi"
        (bundled_home / "agent").mkdir(parents=True)
        (bundled_home / "agent/keybindings.json").write_text('{"bundled": true}')
        (bundled_home / "web-search.json").write_text('{"bundled": true}')
        (self.workspace / ".agents/skills").mkdir(parents=True)
        (self.project / "scripts").mkdir(parents=True)
        (self.state / "agent-home").mkdir(parents=True)
        (self.project / ".git/config").write_text("private git configuration")
        (self.project / "scripts/protected").write_text("original")
        (self.project / "pixi.toml").write_text("project manifest")
        (self.workspace / "AGENTS.md").write_text("workspace instructions")
        self.secret = self.root / "host-secret"
        self.secret.write_text("not accessible")
        patcher = patch.object(sandbox, "filesystem", return_value="ext4")
        patcher.start()
        self.addCleanup(patcher.stop)

    def argv(self, command=None, *, mode="native", windows=None, **kwargs):
        return sandbox.build_command(
            self.project,
            self.state,
            mode=mode,
            windows=windows,
            command=command,
            **kwargs,
        )

    def binds(self, args, flag="--bind"):
        return [(args[i + 1], args[i + 2]) for i, a in enumerate(args) if a == flag]

    def mounts(self, args):
        """Every (flag, target) pair, so overlays can be checked in mount order."""
        return [(args[i], args[i + 1]) for i, a in enumerate(args) if a.startswith("--")]

    def windows_checkout(self):
        """A stand-in for the Windows checkout the boot hook mounts at /mnt/osint-ai."""
        mount = self.root / "mnt-osint-ai"
        (mount / ".git").mkdir(parents=True)
        (mount / ".git" / "config").write_text("windows repository")
        (mount / "AGENTS.md").write_text("windows instructions")
        (mount / "workspace").mkdir(parents=True)
        # The real checkout has its guide here, so the repository tracks something
        # inside `workspace/`. Git collapses a wholly untracked directory into a
        # single `?? workspace/` line, which is not what GitHub Desktop shows.
        (mount / "workspace" / "AGENTS.md").write_text("workspace instructions")
        return mount

    def git(self, *args, checkout=None):
        subprocess.run(
            [
                "git",
                "-C",
                str(self.project if checkout is None else checkout),
                "-c",
                "core.fsmonitor=false",
                "-c",
                "user.name=fixture",
                "-c",
                "user.email=fixture@example.com",
                "-c",
                "commit.gpgsign=false",
                *args,
            ],
            check=True,
            capture_output=True,
        )

    def make_real_repo(self, checkout=None):
        """Replace the fixture's placeholder `.git` with a repository Git accepts."""
        if not shutil.which("git"):
            self.skipTest("git is not installed")
        checkout = self.project if checkout is None else checkout
        git = checkout / ".git"
        if git.is_dir():
            shutil.rmtree(git)
        elif git.exists() or git.is_symlink():
            git.unlink()
        self.git("init", "-q", "-b", "main", checkout=checkout)
        self.git("add", "-A", checkout=checkout)
        self.git("commit", "-qm", "fixture commit", checkout=checkout)
        return checkout

    def require_bwrap(self):
        if PINNED_BWRAP is None:
            self.skipTest(
                f"bubblewrap is not installed in {ROOT}; run: "
                f"pixi install --locked -e {sandbox.ENV_NAME}"
            )
        probe = subprocess.run(self.argv(["/bin/true"]), capture_output=True, text=True, check=False)
        if probe.returncode:
            self.skipTest("unprivileged bubblewrap unavailable: " + probe.stderr.strip())


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
        self.assertIn((str(self.project), CHECKOUT_PATH), self.binds(args))
        self.assertEqual(args[args.index("--chdir") + 1], WORKSPACE_PATH)

    def test_the_sandbox_binary_is_the_one_the_lockfile_pins(self):
        """`update-project` updates the containment too, not only the tools.

        The bubblewrap that builds the namespace comes from the same locked
        environment as Pi and the skill tools, in both deployments: in WSL that is
        the Linux program checkout, whose `.pixi` the agent cannot write.
        """
        source = (SCRIPTS / "sandbox.py").read_text()
        self.assertNotIn('"/usr/bin/bwrap"', source)
        self.assertEqual(self.argv(["/bin/true"])[0], str(self.project / sandbox.BWRAP_SUBPATH))
        mount = self.windows_checkout()
        self.assertEqual(
            self.argv(["/bin/true"], mode="wsl", windows=mount)[0],
            str(self.project / sandbox.BWRAP_SUBPATH),
        )

    def test_missing_bubblewrap_is_reported_before_the_sandbox_starts(self):
        (self.project / sandbox.BWRAP_SUBPATH).unlink()
        with self.assertRaisesRegex(RuntimeError, "bubblewrap"):
            sandbox.check_storage("native", self.project, sandbox.WINDOWS_HOST_MOUNT, self.state)

    def test_the_checkout_is_mounted_whole_never_as_a_bare_workspace(self):
        """The flaw this layout fixes.

        Git finds its repository by walking up from the working directory. An
        earlier revision bound `workspace/` alone at `/workspace`, so there was no
        `.git` above it and every `git status` the guidance promises failed. The
        workspace may only be reachable as a directory inside the checkout mount.
        """
        for mode, windows in (("native", None), ("wsl", self.windows_checkout())):
            with self.subTest(mode=mode):
                args = self.argv(mode=mode, windows=windows)
                targets = [target for _, target in self.binds(args) + self.binds(args, "--ro-bind")]
                self.assertIn(CHECKOUT_PATH, targets)
                self.assertNotIn(WORKSPACE_PATH, targets)
                self.assertEqual(args[args.index("--chdir") + 1], WORKSPACE_PATH)
                self.assertTrue(WORKSPACE_PATH.startswith(CHECKOUT_PATH + "/"))

    def test_etc_alternatives_are_bound(self):
        """`which`, `awk` and `pager` are symlinks into /etc/alternatives on Debian.

        `/etc` is a fresh directory in the sandbox with only the allowlisted files,
        so without this bind those commands sit on PATH as dangling symlinks and
        the assistant sees `/bin/bash: line 1: which: command not found`.
        """
        self.assertIn('"/etc/alternatives"', (SCRIPTS / "sandbox.py").read_text())
        if not Path("/etc/alternatives").exists():
            self.skipTest("this distribution has no /etc/alternatives")
        args = self.argv()
        self.assertIn(("/etc/alternatives", "/etc/alternatives"), self.binds(args, "--ro-bind"))

    def test_the_agents_git_repository_is_reachable(self):
        """The agent must be able to run Git itself, in a real repository.

        It is allowed to see `.git` and to write to it; `workspace/AGENTS.md` lets
        it commit and forbids pushing, and the human still reviews every change.
        What must not come back is a read-only view that makes `git status` fail,
        or a hidden `.git` that silently breaks every reminder.
        """
        args = self.argv()
        overlays = self.mounts(args)
        # Plain Linux: nothing is layered over `.git`, so Git works in place.
        self.assertNotIn(("--tmpfs", f"{CHECKOUT_PATH}/.git"), overlays)
        self.assertNotIn(("--ro-bind", f"{CHECKOUT_PATH}/.git"), overlays)
        self.assertNotIn("--remount-ro", args)
        # The environment the agent runs on is the one thing in the writable
        # tree it must not be able to replace.
        self.assertIn(
            (str(self.project / ".pixi"), f"{CHECKOUT_PATH}/.pixi"),
            self.binds(args, "--ro-bind"),
        )
        self.assertEqual((self.project / ".git" / "config").read_text(), "private git configuration")

    def test_wsl_mode_gives_the_agent_the_windows_checkout(self):
        """WSL has two checkouts: the Windows one is the agent's, the Linux one is not.

        The Windows checkout is mounted read-write, `.git` included, at the same
        sandbox path the plain Linux agent uses, so `git status` describes the
        files the user commits from GitHub Desktop. The Linux checkout keeps the
        code that starts Pi out of reach, `.git` included.
        """
        mount = self.windows_checkout()
        args = self.argv(mode="wsl", windows=mount)
        self.assertIn((str(mount), CHECKOUT_PATH), self.binds(args))
        self.assertIn((str(self.project), PROGRAM_PATH), self.binds(args, "--ro-bind"))
        overlays = self.mounts(args)
        # The agent's checkout is writable, with no read-only or empty overlay
        # on top of its repository.
        self.assertNotIn(("--tmpfs", f"{CHECKOUT_PATH}/.git"), overlays)
        self.assertNotIn(("--ro-bind", f"{CHECKOUT_PATH}/.git"), overlays)
        # The Linux checkout's history stays hidden behind the program mount.
        self.assertIn(("--tmpfs", f"{PROGRAM_PATH}/.git"), overlays)
        self.assertIn(("--remount-ro", f"{PROGRAM_PATH}/.git"), overlays)
        # The host path is not mirrored inside: the agent has one checkout path.
        self.assertNotIn(str(sandbox.WINDOWS_HOST_MOUNT), [t for _, t in self.binds(args)])
        self.assertEqual(args[args.index("--chdir") + 1], WORKSPACE_PATH)

    def test_intercom_state_is_a_private_tmpfs(self):
        """pi-intercom's broker state must not land in the persistent home.

        A shared home would let a second sandbox unlink the live broker's socket
        and would redeliver mail queued for a closed session. The mount must come
        after the agent home so it shadows only that subdirectory, and it must be
        a tmpfs, not a bind.
        """
        args = self.argv()
        overlays = self.mounts(args)
        self.assertIn(("--tmpfs", sandbox.INTERCOM_DIR), overlays)
        self.assertNotIn(("--bind", sandbox.INTERCOM_DIR), overlays)
        self.assertNotIn(("--ro-bind", sandbox.INTERCOM_DIR), overlays)
        home_index = args.index("/home/osint")
        self.assertEqual(args[home_index - 2 : home_index], ["--bind", str(self.state / "agent-home")])
        self.assertGreater(args.index(sandbox.INTERCOM_DIR), home_index)
        self.assertEqual(args[args.index(sandbox.INTERCOM_DIR) - 1], "--tmpfs")
        # Only the intercom subdirectory is private: the rest of the home, the
        # checkout and the read-only program stay as the boundary requires.
        self.assertTrue(sandbox.INTERCOM_DIR.startswith("/home/osint/.pi/agent/"))

    def test_environment_points_at_read_only_tools(self):
        args = self.argv()
        env = {args[i + 1]: args[i + 2] for i, a in enumerate(args) if a == "--setenv"}
        self.assertEqual(env["CONDA_PREFIX"], f"{CHECKOUT_PATH}/.pixi/envs/{sandbox.ENV_NAME}")
        self.assertTrue(
            env["PATH"].startswith(f"{CHECKOUT_PATH}/.pixi/envs/{sandbox.ENV_NAME}/bin:")
        )
        self.assertEqual(env["HOME"], "/home/osint")
        self.assertEqual(env["OSINT_SANDBOX"], "1")
        self.assertEqual(env["OSINT_MODE"], "native")
        self.assertEqual(env["OSINT_CHECKOUT"], CHECKOUT_PATH)
        self.assertEqual(env["OSINT_WORKSPACE"], WORKSPACE_PATH)
        self.assertEqual(env["OSINT_SKILLS_DIR"], SKILLS_PATH)
        # The model shortlist comes from the program checkout, which is read-only
        # here: the assistant cannot widen its own model list.
        self.assertEqual(
            env["OSINT_MODEL_SHORTLIST"],
            f"{CHECKOUT_PATH}/{sandbox.MODEL_SHORTLIST_NAME}",
        )
        self.assertEqual(json.loads(base64.b64decode(env["OSINT_PI_ARGS"])), [])

    def test_git_commits_are_given_an_identity(self):
        """`git commit` needs an author, and the sandbox home has no ~/.gitconfig.

        The Windows user's Git identity lives on the Windows side and is not
        mounted into the agent home, so a commit from inside the sandbox would
        fail with "Author identity unknown" - which would silently break the
        `git add` and `git commit` the guidance promises. A fixed name also tells
        the reviewer in GitHub Desktop which commits the assistant wrote.
        """
        args = self.argv()
        env = {args[i + 1]: args[i + 2] for i, a in enumerate(args) if a == "--setenv"}
        for role in ("AUTHOR", "COMMITTER"):
            self.assertEqual(env[f"GIT_{role}_NAME"], sandbox.GIT_IDENTITY_NAME)
            self.assertRegex(
                env[f"GIT_{role}_EMAIL"],
                r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
                f"GIT_{role}_EMAIL is not a usable address",
            )

    def test_both_modes_share_the_agent_paths_and_swap_only_the_program(self):
        mount = self.windows_checkout()
        native = self.argv()
        wsl = self.argv(mode="wsl", windows=mount)
        self.assertIn((str(mount), CHECKOUT_PATH), self.binds(wsl))
        self.assertNotIn(str(self.workspace), wsl)
        # The working directory and the checkout the agent sees are identical,
        # which is what lets one set of skills and guidance serve both platforms.
        self.assertEqual(native[native.index("--chdir") + 1], wsl[wsl.index("--chdir") + 1])
        env = {wsl[i + 1]: wsl[i + 2] for i, a in enumerate(wsl) if a == "--setenv"}
        self.assertEqual(env["OSINT_MODE"], "wsl")
        self.assertEqual(env["OSINT_CHECKOUT"], CHECKOUT_PATH)
        self.assertEqual(env["OSINT_WORKSPACE"], WORKSPACE_PATH)
        self.assertEqual(env["OSINT_SKILLS_DIR"], SKILLS_PATH)
        self.assertEqual(env["CONDA_PREFIX"], f"{PROGRAM_PATH}/.pixi/envs/{sandbox.ENV_NAME}")
        # ... and the shortlist is read from that read-only checkout, not from the
        # Windows checkout the agent works in and can write.
        self.assertEqual(
            env["OSINT_MODEL_SHORTLIST"],
            f"{PROGRAM_PATH}/{sandbox.MODEL_SHORTLIST_NAME}",
        )

    def test_wsl_talks_to_the_windows_host_not_to_loopback(self):
        """llama.cpp runs on Windows, outside the virtual machine.

        `127.0.0.1` inside WSL is the distribution itself, so the address has to be
        the Windows host: the default gateway of the guest, resolved at every
        launch because WSL can hand out a different subnet, and exported twice -
        Pi's built-in llama.cpp provider reads `LLAMA_BASE_URL`, and the launcher
        rewrites the same address into the generated models.json.
        """
        mount = self.windows_checkout()
        with patch.object(sandbox, "default_gateway", return_value="172.30.96.1"):
            wsl = self.argv(mode="wsl", windows=mount)
        env = {wsl[i + 1]: wsl[i + 2] for i, a in enumerate(wsl) if a == "--setenv"}
        self.assertEqual(env["LLAMA_BASE_URL"], "http://172.30.96.1:8080")
        self.assertEqual(env["OSINT_INFERENCE_URL"], "http://172.30.96.1:8080")
        # A guest that cannot name a gateway falls back to loopback rather than
        # exporting an address that is empty; plain Linux always uses loopback,
        # because there the server runs in this very checkout.
        with patch.object(sandbox, "default_gateway", return_value=None):
            stranded = self.argv(mode="wsl", windows=mount)
        env = {stranded[i + 1]: stranded[i + 2] for i, a in enumerate(stranded) if a == "--setenv"}
        self.assertEqual(env["LLAMA_BASE_URL"], "http://127.0.0.1:8080")
        native = self.argv()
        env = {native[i + 1]: native[i + 2] for i, a in enumerate(native) if a == "--setenv"}
        self.assertEqual(env["LLAMA_BASE_URL"], "http://127.0.0.1:8080")

    def test_the_default_gateway_comes_from_proc_without_iproute2(self):
        """`ip route` is not installed in the private distribution, and is not needed.

        This is the machine the containerless case is about: the Windows host as seen
        from inside WSL. The destination and gateway fields are little-endian hex, so
        `0101A8C0` is 192.168.1.1 and not 192.168.1.100.
        """
        table = (
            "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
            "eth0\t00000000\t01001CAC\t0003\t0\t0\t0\t00000000\t0\t0\t0\n"
            "eth0\t0001A8C0\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0\n"
        )
        with patch.object(sandbox.Path, "read_text", return_value=table):
            self.assertEqual(sandbox.default_gateway(), "172.28.0.1")
        with patch.object(sandbox.Path, "read_text", side_effect=FileNotFoundError):
            self.assertIsNone(sandbox.default_gateway())

    def test_entry_prefers_installed_copy(self):
        with patch("pathlib.Path.is_file", return_value=True):
            args = self.argv()
        self.assertEqual(args[-2:], ["/bin/bash", "/usr/local/lib/osint-ai/pi-entry.sh"])
        # Without a root-owned installation: the agent's own (developer-editable)
        # copy in plain Linux, the read-only program checkout in WSL.
        self.assertEqual(self.argv()[-2:], ["/bin/bash", f"{CHECKOUT_PATH}/scripts/pi-entry.sh"])
        mount = self.windows_checkout()
        self.assertEqual(
            self.argv(mode="wsl", windows=mount)[-2:],
            ["/bin/bash", f"{PROGRAM_PATH}/scripts/pi-entry.sh"],
        )

    def test_protected_symlink_rejected(self):
        link = self.project / "workspace"
        shutil.rmtree(link)
        link.symlink_to(self.root, target_is_directory=True)
        # The launcher never builds a namespace for it.
        with self.assertRaisesRegex(RuntimeError, "symlink"):
            self.argv(["/bin/true"])

    def test_native_mode_requires_a_real_git_checkout(self):
        shutil.rmtree(self.project / ".git")
        with self.assertRaisesRegex(RuntimeError, "not a Git checkout"):
            sandbox.check_storage("native", self.project, sandbox.WINDOWS_HOST_MOUNT, self.state)

    def test_missing_environment_is_reported(self):
        (self.project / f".pixi/envs/{sandbox.ENV_NAME}/bin/pi").unlink()
        with self.assertRaisesRegex(RuntimeError, "environment is not installed"):
            sandbox.check_storage("native", self.project, sandbox.WINDOWS_HOST_MOUNT, self.state)

    def test_windows_filesystem_rejected(self):
        with patch.object(sandbox, "filesystem", return_value="ntfs"):
            with self.assertRaisesRegex(RuntimeError, "Refusing"):
                sandbox.check_storage("native", self.project, sandbox.WINDOWS_HOST_MOUNT, self.state)

    def test_wsl_mode_requires_the_windows_mount(self):
        mount = self.windows_checkout()
        with (
            patch.object(sandbox, "WINDOWS_HOST_MOUNT", mount),
            patch.object(sandbox.os.path, "ismount", return_value=False),
        ):
            with self.assertRaisesRegex(RuntimeError, "not mounted"):
                sandbox.check_storage("wsl", self.project, mount, self.state)

    def test_wsl_mode_accepts_the_mounted_checkout(self):
        mount = self.windows_checkout()
        with (
            patch.object(sandbox, "WINDOWS_HOST_MOUNT", mount),
            patch.object(sandbox.os.path, "ismount", return_value=True),
        ):
            sandbox.check_storage("wsl", self.project, mount, self.state)

    def test_wsl_mode_requires_a_real_git_checkout(self):
        mount = self.root / "mnt-osint-ai"
        (mount / "workspace").mkdir(parents=True)
        with (
            patch.object(sandbox, "WINDOWS_HOST_MOUNT", mount),
            patch.object(sandbox.os.path, "ismount", return_value=True),
        ):
            with self.assertRaisesRegex(RuntimeError, "not a Git checkout"):
                sandbox.check_storage("wsl", self.project, mount, self.state)

    def test_worktree_git_file_rejected(self):
        """A `.git` that is a gitdir pointer is refused, not followed."""
        shutil.rmtree(self.project / ".git")
        (self.project / ".git").write_text("gitdir: /elsewhere")
        with self.assertRaisesRegex(RuntimeError, "not a Git checkout"):
            sandbox.check_storage("native", self.project, sandbox.WINDOWS_HOST_MOUNT, self.state)
        # In WSL the same checkout is the masked program copy: still refused.
        with self.assertRaisesRegex(RuntimeError, "real directory"):
            self.argv(["/bin/true"], mode="wsl", windows=self.windows_checkout())

    def test_mount_helper_rejects_symlink(self):
        link = self.root / "link"
        link.symlink_to(self.state / "agent-home", target_is_directory=True)
        with self.assertRaises(OSError):
            mounts.directory_fd(link)

    def test_launcher_wrappers_exec_trusted_commands(self):
        """One launcher, two modes, and the installed shims pick the mode."""
        script = (SCRIPTS / "bwrap-pi.sh").read_text()
        self.assertIn("sandbox.py", script)
        self.assertIn("/usr/local/lib/osint-ai/sandbox.py", script)
        self.assertIn("--native", (WINDOWS / "launchers/osint-pi").read_text())
        self.assertIn("--wsl", (WINDOWS / "launchers/osint-pi-wsl").read_text())

    def test_bundled_pi_home_files_are_mounted_not_copied(self):
        """Program-owned Pi home files are read-only binds out of the environment.

        A copy written once into the persistent home outlives the layout and keeps
        telling the agent paths that no longer exist, and nothing refreshes it. A
        bind always shows what the installed environment contains, and the agent
        cannot rewrite its own guidance.
        """
        args = self.argv()
        bundled = self.project / sandbox.BUNDLED_HOME_SUBPATH
        expected = [
            (str(bundled / "agent/keybindings.json"), "/home/osint/.pi/agent/keybindings.json"),
            (str(bundled / "web-search.json"), "/home/osint/.pi/web-search.json"),
        ]
        read_only = self.binds(args, "--ro-bind")
        for pair in expected:
            self.assertIn(pair, read_only)
        # They must come after the agent home, or the home would shadow them.
        home_index = args.index("/home/osint")
        for _, target in expected:
            self.assertGreater(args.index(target), home_index)
        # settings.json is the opposite case: Pi writes it, so it stays in the home.
        self.assertNotIn(("--ro-bind", "/home/osint/.pi/agent/settings.json"), self.mounts(args))
        # The agent's instructions are not a program file: they are the checkout's
        # own `workspace/AGENTS.md`, so nothing binds an AGENTS.md into the home.
        self.assertNotIn("/home/osint/.pi/agent/AGENTS.md", args)
        # And nothing shadows the checkout root's `AGENTS.md` either: a read-only
        # empty file there would make `git status` report a modified AGENTS.md in
        # the checkout the agent may commit from. `pi-entry.sh` turns Pi's context
        # discovery off instead.
        self.assertFalse(
            [pair for pair in self.binds(args) + self.binds(args, "--ro-bind") if pair[1].endswith("/AGENTS.md")],
            "the checkout root's AGENTS.md must not be shadowed: git would report it modified",
        )

    def test_missing_bundled_pi_home_is_reported(self):
        (self.project / sandbox.BUNDLED_HOME_SUBPATH / "agent/keybindings.json").unlink()
        with self.assertRaisesRegex(RuntimeError, "bundled Pi home is missing"):
            sandbox.check_storage("native", self.project, sandbox.WINDOWS_HOST_MOUNT, self.state)

    def test_state_directory_is_the_same_in_both_deployments(self):
        """Only the workspace differs between deployments; state does not.

        A WSL-specific state directory is how the two deployments drift apart: a
        credential, a session or a setting ends up somewhere the other one never
        looks at. There is no longer a constant for one.
        """
        self.assertEqual(sandbox.STATE_SUBPATH, Path(".local") / "state" / "osint-ai")
        self.assertFalse(
            hasattr(sandbox, "DEFAULT_STATE"),
            "a WSL-specific default state directory has come back",
        )
        with patch.dict(os.environ, {}, clear=True), patch.object(
            Path, "home", return_value=Path("/home/osint")
        ):
            self.assertEqual(sandbox.default_state(), Path("/home/osint/.local/state/osint-ai"))
        with patch.dict(os.environ, {"OSINT_STATE_DIR": "/srv/osint-state"}, clear=True):
            self.assertEqual(sandbox.default_state(), Path("/srv/osint-state"))

    def test_agent_home_is_private(self):
        """`auth.json` holds provider keys, so its directory may not be open.

        mkdir inherits the umask, so a shared PC ends up with a group-readable
        credential store. The launcher enforces 0700 on every launch, which also
        repairs a home created by an older version.
        """
        state = self.root / "shared state"
        state.mkdir()
        os.chmod(state, 0o775)
        (state / "agent-home").mkdir()
        os.chmod(state / "agent-home", 0o755)
        sandbox.prepare_state(state)
        for path in (state, state / "agent-home"):
            self.assertEqual(
                stat.S_IMODE(path.stat().st_mode), 0o700, f"{path} is not private"
            )
        # Idempotent: a second launch must not fail on the existing directory.
        sandbox.prepare_state(state)

    def test_parse_args_defaults_and_overrides(self):
        """The CLI keeps `--root` and `--windows` usable, and Pi arguments separate."""
        with patch.object(sandbox, "WINDOWS_HOST_MOUNT", self.root / "mnt-osint-ai"):
            options = sandbox.parse_args(
                ["--wsl", "--root", str(self.project), "--state", str(self.state), "--version"]
            )
        self.assertEqual(options["mode"], "wsl")
        self.assertEqual(options["project"], self.project)
        self.assertEqual(options["windows"], self.root / "mnt-osint-ai")
        self.assertEqual(options["pi_args"], ["--version"])
        # `--windows` is a real override, for diagnostics on a development machine.
        options = sandbox.parse_args(
            ["--wsl", "--root", str(self.project), "--windows", str(self.project),
             "--state", str(self.state)]
        )
        self.assertEqual(options["windows"], self.project)
        options = sandbox.parse_args(["--native", "--root", str(self.project), "--state", str(self.state)])
        self.assertEqual(options["mode"], "native")
        self.assertEqual(options["windows"], sandbox.WINDOWS_HOST_MOUNT)

    def test_the_launcher_takes_only_a_mode_and_pi_arguments(self):
        result = subprocess.run(
            ["/bin/bash", str(SCRIPTS / "bwrap-pi.sh"), "not-a-mode"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--native|--wsl", result.stderr)

    def test_the_launcher_names_the_checkout_that_holds_pixi_toml(self):
        """`bwrap-pi.sh` sits in `<checkout>/scripts`, so the root is one level up.

        Comparing against `$here/pixi.toml` is never true, which left the project
        root to whatever directory Pixi happened to be invoked from.
        """
        script = (SCRIPTS / "bwrap-pi.sh").read_text()
        self.assertIn('"$here/../pixi.toml"', script)
        self.assertIn('OSINT_PROJECT_ROOT:-$(cd -- "$here/.." && pwd)', script)


class AgentGitTests(SandboxFixture):
    """The agent runs Git in the checkout it works in; this is what it sees."""

    def sandbox_run(self, *command, mode="native", windows=None):
        self.require_bwrap()
        return subprocess.run(
            self.argv(list(command), mode=mode, windows=windows),
            capture_output=True,
            text=True,
            check=False,
        )

    def test_git_status_works_from_the_working_directory(self):
        self.make_real_repo()
        result = self.sandbox_run("git", "status", "--porcelain=v1", "-b")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("## main", result.stdout)

    def test_a_clean_and_a_dirty_checkout_are_both_reported(self):
        self.make_real_repo()
        clean = self.sandbox_run("git", "status", "--porcelain=v1", "-b")
        self.assertEqual(clean.returncode, 0, clean.stderr)
        self.assertEqual(clean.stdout.splitlines()[1:], [], "the fixture left changes behind")
        (self.workspace / "AGENTS.md").write_text("changed rule")
        (self.workspace / "new-skill.txt").write_text("new")
        status = self.sandbox_run("git", "status", "--porcelain=v1", "-b").stdout
        self.assertIn("## main", status)
        self.assertIn("workspace/AGENTS.md", status)
        self.assertIn("?? workspace/new-skill.txt", status)
        # The change is the real file on the host, not a sandbox-local copy.
        self.assertEqual((self.workspace / "AGENTS.md").read_text(), "changed rule")

    def test_the_agent_can_commit_from_its_working_directory(self):
        """Documents the consequence of a writable `.git` on purpose.

        `workspace/AGENTS.md` allows `git add` and `git commit` and forbids
        pushing, and the human reviews the result. The sandbox does not stop a
        commit, a `reset --hard` of the user's uncommitted work, a history
        rewrite, or a push if this machine ever held a credential. This test
        exists so that permission stays a decision instead of an accident.
        """
        self.make_real_repo()
        (self.workspace / "AGENTS.md").write_text("a rule the assistant wrote")
        # Git commands run from `/osint-ai/workspace`, so their path arguments are
        # relative to it even though `git status` reports them from the root.
        staged = self.sandbox_run("git", "add", "AGENTS.md")
        self.assertEqual(staged.returncode, 0, staged.stderr)
        committed = self.sandbox_run("git", "commit", "-qm", "written from inside the sandbox")
        self.assertEqual(committed.returncode, 0, committed.stderr)
        log = subprocess.run(
            ["git", "-C", str(self.project), "log", "--oneline", "-1"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("written from inside the sandbox", log.stdout)
        # The launcher supplies the identity: this home has no ~/.gitconfig, and
        # without it Git refuses with "Author identity unknown".
        author = subprocess.run(
            ["git", "-C", str(self.project), "log", "-1", "--format=%an <%ae>"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(
            author.stdout.strip(),
            f"{sandbox.GIT_IDENTITY_NAME} <{sandbox.GIT_IDENTITY_EMAIL}>",
        )
        after = self.sandbox_run("git", "status", "--porcelain=v1")
        self.assertEqual(after.stdout.strip(), "")

    def test_wsl_git_status_describes_the_windows_checkout(self):
        """`git status` in WSL must match what GitHub Desktop shows the user."""
        mount = self.make_real_repo(self.windows_checkout())
        (mount / "workspace" / "note.md").write_text("unsaved research")
        result = self.sandbox_run("git", "status", "--porcelain=v1", "-b", mode="wsl", windows=mount)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("?? workspace/note.md", result.stdout)
        # The Linux checkout's own repository is not the one being reported.
        self.assertNotIn("pixi.toml", result.stdout)


class SandboxBoundaryTests(SandboxFixture):
    def test_real_filesystem_boundary(self):
        self.require_bwrap()
        self.make_real_repo()
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
            assert not Path('/workspace').exists(), 'the workspace is not a separate mount'
            assert Path('/osint-ai/pixi.toml').read_text() == 'project manifest'
            # The agent's own repository is reachable and writable in plain Linux,
            # and Git finds it by walking up from the working directory.
            assert Path('/osint-ai/.git/HEAD').exists(), '.git is not masked'
            git = subprocess.run(['git', 'status', '--porcelain'], cwd='/osint-ai/workspace')
            assert git.returncode == 0, 'git status failed in the working directory'
            # Debian and Ubuntu resolve these names through /etc/alternatives.
            assert subprocess.run(['which', 'awk'], capture_output=True).returncode == 0, 'which is broken'
            assert subprocess.run(['awk', '--version'], capture_output=True).returncode == 0, 'awk is broken'
            assert not os.environ.get('AWS_SECRET_ACCESS_KEY')
            for p in ['/etc/hosts']:
                try:
                    Path(p).write_text('should fail')
                except OSError:
                    pass
                else:
                    raise AssertionError('unexpected write: ' + p)
            Path('/osint-ai/workspace/AGENTS.md').write_text('updated instructions')
            Path('/osint-ai/workspace/.agents/skills/new-skill').mkdir()
            Path('/osint-ai/workspace/.agents/skills/new-skill/SKILL.md').write_text('new skill')
            link = Path('/osint-ai/workspace/escape')
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

    def test_native_program_files_are_writable_by_design(self):
        """Plain Linux has one checkout, so `git commit` needs the root writable.

        Only `.pixi` is read-only there: the tools the assistant runs on must not
        be replaceable from inside a session.
        """
        self.require_bwrap()
        code = textwrap.dedent("""
            from pathlib import Path
            Path('/osint-ai/notes-for-the-developer.md').write_text('a request')
            for p in ['/osint-ai/.pixi/envs/default/bin/pi']:
                try:
                    Path(p).write_text('should fail')
                except OSError:
                    pass
                else:
                    raise AssertionError('unexpected write: ' + p)
        """)
        result = subprocess.run(
            self.argv(["/usr/bin/python3", "-c", code]), capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.project / "notes-for-the-developer.md").read_text(), "a request")
        self.assertEqual(
            (self.project / f".pixi/envs/{sandbox.ENV_NAME}/bin/pi").read_text(), "#!/bin/sh\n"
        )

    def test_wsl_filesystem_boundary(self):
        """In WSL the program checkout stays read-only; the agent's does not."""
        mount = self.make_real_repo(self.windows_checkout())
        self.require_bwrap()
        code = textwrap.dedent("""
            from pathlib import Path
            import subprocess
            # The agent works here, and this is the repository it reports on.
            assert Path('/osint-ai/AGENTS.md').read_text() == 'windows instructions'
            assert Path('/osint-ai/.git/HEAD').exists(), '.git is not masked'
            Path('/osint-ai/AGENTS.md').write_text('edited by the agent')
            git = subprocess.run(['git', 'status', '--porcelain'], cwd='/osint-ai/workspace')
            assert git.returncode == 0, 'git status failed in the working directory'
            # The host mount path is not mirrored inside the sandbox.
            assert not Path('/mnt/osint-ai').exists(), 'the host path leaked in'
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
        args = self.argv(["/usr/bin/python3", "-c", code], mode="wsl", windows=mount)
        result = subprocess.run(args, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((mount / "AGENTS.md").read_text(), "edited by the agent")
        self.assertEqual((self.project / "pixi.toml").read_text(), "project manifest")

    def test_bundled_pi_home_files_shadow_a_stale_agent_home(self):
        """A fossil in the persistent home must not win against the environment."""
        self.require_bwrap()
        fossil = self.state / "agent-home/.pi/agent/keybindings.json"
        fossil.parent.mkdir(parents=True, exist_ok=True)
        # The probe launch above left a 0-byte, non-writable mount point here:
        # bubblewrap has to create the target of a file bind before it can shadow
        # it. Replace it with the stale file an older version would have left.
        fossil.unlink(missing_ok=True)
        fossil.write_text('{"stale": "from an older version"}')
        code = textwrap.dedent("""
            from pathlib import Path
            bindings = Path('/home/osint/.pi/agent/keybindings.json')
            assert bindings.read_text() == '{"bundled": true}', bindings.read_text()
            assert Path('/home/osint/.pi/web-search.json').read_text() == '{"bundled": true}'
            try:
                bindings.write_text('{"rewritten": true}')
            except OSError:
                pass
            else:
                raise AssertionError('the agent could rewrite a program-owned file')
        """)
        result = subprocess.run(
            self.argv(["/usr/bin/python3", "-c", code]), capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        # Shadowed by a mount, not deleted: the home is the user's directory.
        self.assertEqual(fossil.read_text(), '{"stale": "from an older version"}')

    def test_cwd_is_the_workspace_inside_the_checkout(self):
        self.require_bwrap()
        result = subprocess.run(
            self.argv(["/usr/bin/python3", "-c", "import os; print(os.getcwd())"]),
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(result.stdout.strip(), WORKSPACE_PATH)

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
import os
import sys
from pathlib import Path
Path({argv_log!r}).write_text(json.dumps(sys.argv[1:]))
Path({env_log!r}).write_text(json.dumps(dict(os.environ)))
if '--list-devices' in sys.argv:
    if {has_gpu}:
        print('Available devices:\\n  Vulkan0: fake test GPU')
        sys.exit(0)
    print('failed to initialize Vulkan', file=sys.stderr)
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
        self.env_log = root / "env.json"
        runtime = root / "runtime"
        (runtime / "bin").mkdir(parents=True)
        (root / "models.ini").write_text("version = 1\n")
        self.binary = runtime / "bin/llama-server"
        self.has_gpu = True
        self.write_fake()
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        for name, value in [
            ("RUNTIME", runtime),
            ("STATE_ROOT", root),
            ("STATE", self.state),
            ("PRESETS", root / "models.ini"),
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
        self.binary.write_text(
            self.FAKE.format(
                argv_log=str(self.argv_log), env_log=str(self.env_log), has_gpu=self.has_gpu
            )
        )
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
        self.assertEqual(record["backend"], "vulkan")
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

    def test_weights_live_in_the_default_hugging_face_cache(self):
        """Weights land in `~/.cache/huggingface/hub`, not in private state.

        The child environment is scrubbed and passes HOME alone: no
        `LLAMA_CACHE`, `HF_HUB_CACHE`, `HUGGINGFACE_HUB_CACHE`, `HF_HOME` or
        `XDG_CACHE_HOME` may appear there, because each of them outranks HOME in
        llama.cpp's resolution and would move the weights somewhere the user will
        not look. The state directory keeps the pid file and the log.
        """
        server.main("start")
        env = json.loads(self.env_log.read_text())
        for name in ("LLAMA_CACHE", "HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE", "HF_HOME", "XDG_CACHE_HOME"):
            self.assertNotIn(name, env, name)
        # HOME is what makes llama.cpp pick the standard path; without it there is
        # no cache location at all and the load fails.
        home = env.get("HOME")
        self.assertTrue(home, "the inference environment must pass HOME")
        self.assertTrue((Path(home) / ".cache").is_absolute())
        self.assertFalse((server.STATE_ROOT / "models").exists())

    def test_restart_replaces_the_running_server(self):
        server.main("start")
        first = self.record()["pid"]
        server.main("restart")
        second = self.record()["pid"]
        self.assertNotEqual(first, second)
        self.assertTrue(server.healthy())
        os.waitpid(first, 0)

    def test_no_vulkan_device_falls_back_to_cpu(self):
        """Detection asks the binary, so a plain Linux PC is judged the same way."""
        self.write_fake(has_gpu=False)
        server.main("start")
        self.assertEqual(self.record()["backend"], "cpu")
        argv = self.recorded_argv()
        self.assertEqual(argv[argv.index("--n-gpu-layers") + 1], "0")
        self.assertTrue(server.healthy())

    def test_vulkan_build_without_a_device_falls_back_to_cpu(self):
        """A device probe that succeeds and names no Vulkan device is still CPU."""
        self.binary.write_text(
            "#!/usr/bin/python3\nimport sys\n"
            'if "--list-devices" in sys.argv:\n'
            '    print("Available devices:\\n  CPU")\n    sys.exit(0)\n'
            "import http.server, json\n"
            "class H(http.server.BaseHTTPRequestHandler):\n"
            "    def do_GET(self):\n"
            "        self.send_response(200); self.end_headers()\n"
            '        self.wfile.write(b\'{"status":"ok"}\')\n'
            "    def log_message(self, *a): pass\n"
            "port = int(sys.argv[sys.argv.index('--port') + 1])\n"
            "http.server.HTTPServer(('127.0.0.1', port), H).serve_forever()\n"
        )
        self.binary.chmod(0o755)
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
            'if "--list-devices" in sys.argv: print("Vulkan0: test")\n'
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
            '#!/bin/sh\nif [ "$1" = --list-devices ]; then echo "Vulkan0: test"; else exit 7; fi\n'
        )
        with self.assertRaisesRegex(RuntimeError, "Server exited"):
            server.main("start")
        self.assertFalse((self.state / "server.json").exists())

    def test_stop_without_any_state_says_so(self):
        """`stop-server` works on a PC that never had local inference."""
        with patch.object(server, "STATE", Path(self.temp.name) / "no-state"):
            server.main("stop")
        self.assertFalse((Path(self.temp.name) / "no-state").exists())

    def test_missing_presets_are_named(self):
        with patch.object(server, "PRESETS", Path(self.temp.name) / "gone.ini"):
            with self.assertRaisesRegex(RuntimeError, "Model presets are missing"):
                server.main("start")

    def test_the_runtime_is_the_checkout_environment(self):
        """Local inference is one optional Pixi environment in the project root."""
        self.assertEqual(
            server.RUNTIME_SUBPATH,
            Path(".pixi") / "envs" / "llamacpp-binary-vulkan",
        )
        self.assertEqual(server.server_binary(), server.RUNTIME / "bin" / server.SERVER_NAME)
        self.assertEqual(server.SERVER_NAME, "llama-server")
        with patch.dict(os.environ, {"PIXI_PROJECT_ROOT": "/srv/osint-ai"}, clear=True):
            self.assertEqual(
                server.project_root() / server.RUNTIME_SUBPATH / "bin/llama-server",
                Path("/srv/osint-ai/.pixi/envs/llamacpp-binary-vulkan/bin/llama-server"),
            )

    def test_the_installed_deployment_names_the_linux_checkout(self):
        """Never the Windows checkout: that is the one the assistant may edit."""
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "osint-ai.json"
            config.write_text(
                json.dumps(
                    {"windows_project": "/mnt/osint-ai", "linux_project": "/home/osint/osint-ai"}
                )
            )
            with patch.object(server, "PROJECT_CONFIG", config), patch.dict(
                os.environ, {}, clear=True
            ):
                self.assertEqual(server.project_root(), Path("/home/osint/osint-ai"))

    def test_state_follows_the_user_state_directory_without_var_lib(self):
        """A plain Linux checkout needs no root-created /var/lib directory."""
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "var-lib-osint-ai"
            with patch.object(server, "SYSTEM_STATE", missing), patch.dict(
                os.environ, {"OSINT_STATE_DIR": str(Path(temporary) / "state")}, clear=True
            ):
                self.assertEqual(server.state_root(), Path(temporary) / "state")

    def test_a_missing_inference_environment_names_the_install(self):
        """Optional means the answer is a command, not 'complete the installation'."""
        with patch.object(server, "RUNTIME", Path(self.temp.name) / "not-installed"):
            with self.assertRaisesRegex(RuntimeError, "llamacpp-binary-vulkan"):
                server.main("start")
        with patch.object(server, "RUNTIME", Path(self.temp.name) / "not-installed"):
            with self.assertRaisesRegex(RuntimeError, "optional"):
                server.main("start")


if __name__ == "__main__":
    unittest.main()
