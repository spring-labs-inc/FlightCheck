"""Black-box checks of built/installed wheels, using disposable targets only."""

import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import venv
import zipfile
from urllib.request import urlopen

ROOT = Path(os.environ.get("FC_PROTOTYPE_ROOT", Path(__file__).resolve().parents[3]))
EXPERIMENT = ROOT / "experiments/pypi-installer"
MARKER_TEXT = "Disposable FlightCheck distribution sandbox\n"


def snapshot(root):
    return {str(p.relative_to(root)): (p.read_bytes(), stat.S_IMODE(p.stat().st_mode))
            for p in sorted(root.rglob("*")) if p.is_file() and not p.is_symlink()}


def tree_snapshot(root):
    return {str(p.relative_to(root)): (("symlink", os.readlink(p), stat.S_IMODE(p.lstat().st_mode)) if p.is_symlink() else ("directory" if p.is_dir() else p.read_bytes(), stat.S_IMODE(p.stat().st_mode)))
            for p in [root, *sorted(root.rglob("*"))]}


class PyPIPrototypeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="flightcheck-pypi-tests-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.scratch = Path(cls.temporary.name).resolve()
        cls.env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PIP_NO_INDEX="1",
                       PIP_DISABLE_PIP_VERSION_CHECK="1", HOME=str(cls.scratch / "home"))
        Path(cls.env["HOME"]).mkdir()
        if os.environ.get("FC_MANUAL_CONTROL") == "1":
            return
        cls.wheels = cls.scratch / "wheels"
        for version in ["0.0.0.dev58", "0.0.0.dev59"]:
            result = subprocess.run([sys.executable, "-B", str(EXPERIMENT / "build_wheel.py"),
                                     "--output", str(cls.wheels), "--version", version],
                                    env=cls.env, capture_output=True, text=True)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
        cls.environment = cls.scratch / "cli"
        venv.EnvBuilder(with_pip=True).create(cls.environment)
        cls.python = cls.environment / "bin/python"
        cls.cli = cls.environment / "bin/flightcheck-prototype"

    def setUp(self):
        self.project = Path(tempfile.mkdtemp(dir=self.scratch))
        (self.project / ".flightcheck-prototype-sandbox").write_text(MARKER_TEXT)
        for name in ["AGENTS.md", "CLAUDE.md", "nested/AGENTS.md", ".codex/config.toml",
                     ".codex/hooks.json", ".codex/rules/project.rules", ".claude/settings.json",
                     "requirements.txt", "LICENSE"]:
            path = self.project / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("Existing project policy: " + name + "\n")
            path.chmod(0o640)
        self.original = snapshot(self.project)
        if os.environ.get("FC_MANUAL_CONTROL") != "1":
            self.install_cli("0.0.0.dev58")

    def install_cli(self, version):
        wheel = self.wheels / ("flightcheck_distribution_prototype-" + version + "-py3-none-any.whl")
        result = subprocess.run([str(self.python), "-B", "-m", "pip", "install", "--no-index",
                                 "--no-deps", "--force-reinstall", str(wheel)],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def call(self, command, *options, expected=0):
        result = subprocess.run([str(self.cli), command, "--sandbox", str(self.project), *options],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout if expected == 0 else result.stderr)

    def initialized(self):
        return self.call("init", "--apply")["bundle"]

    def assert_original(self):
        current = snapshot(self.project)
        for name, original in self.original.items():
            self.assertEqual(current[name], original, name)

    def test_wheel_inventory_and_install_isolation(self):
        wheel = next(self.wheels.glob("*dev58*.whl"))
        with zipfile.ZipFile(wheel) as archive:
            manifest = json.loads(archive.read("flightcheck_prototype/manifest.json"))
            expected = json.loads((EXPERIMENT / "assets.json").read_text())
            self.assertEqual(set(manifest["assets"]), set(expected))
            self.assertEqual(set(n.removeprefix("flightcheck_prototype/assets/") for n in archive.namelist()
                                 if n.startswith("flightcheck_prototype/assets/")), set(expected))
            # Assert complete canonical directories independently of the inventory.
            canonical = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
            self.assertTrue(set(n for n in canonical if n.startswith(("status-card/", "examples/existing-project/")))
                            <= set(expected))
            for name in expected:
                data = archive.read("flightcheck_prototype/assets/" + name)
                self.assertEqual(data, (ROOT / name).read_bytes(), name)
                self.assertEqual(hashlib.sha256(data).hexdigest(), manifest["assets"][name])
            metadata = archive.read("flightcheck_distribution_prototype-0.0.0.dev58.dist-info/METADATA").decode()
            self.assertIn("License-Expression: FSL-1.1-MIT", metadata)
            self.assertEqual(archive.read("flightcheck_distribution_prototype-0.0.0.dev58.dist-info/licenses/LICENSE"),
                             (ROOT / "LICENSE").read_bytes())
            self.assertIn("examples/existing-project/scripts/handoff.py", expected)
            self.assertIn("experiments/pypi-installer/lock.schema.json", expected)
        # Installing the wheel happened in setUp; import and --help remain inert.
        before = snapshot(Path(self.env["HOME"]))
        result = subprocess.run([str(self.python), "-B", "-c", "import flightcheck_prototype.cli"],
                                env=self.env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(snapshot(self.project), self.original)
        self.assertEqual(snapshot(Path(self.env["HOME"])), before)
        # Run actual bundled public runtime, without source checkout on sys.path.
        installed = self.initialized()
        root = self.project / ".flightcheck/versions" / installed
        result = subprocess.run([str(self.python), "-B", str(root / "examples/existing-project/scripts/handoff.py"),
                                 "--help"], cwd=self.project, env=self.env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([str(self.python), "-B", str(root / "status-card/serve.py"), "--help"],
                                cwd=self.project, env=self.env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        # Exercise the packaged browser assets through the actual loopback server.
        process = subprocess.Popen([str(self.python), "-B", str(root / "status-card/serve.py"), "--port", "0"],
                                   cwd=self.project, env=self.env, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        try:
            self.assertTrue(select.select([process.stdout], [], [], 5)[0], "No card startup line")
            line = process.stdout.readline().decode().strip()
            self.assertTrue(line.startswith("FlightCheck status card at http://127.0.0.1:"), line)
            url = line.removeprefix("FlightCheck status card at ")
            with urlopen(url, timeout=5) as response:
                self.assertIn(b"FlightCheck", response.read())
            with urlopen(url + "status.json", timeout=5) as response:
                self.assertEqual(json.load(response)["snapshot"], "historical")
            with urlopen(url + "card.js", timeout=5) as response:
                self.assertEqual(response.read(), (ROOT / "status-card/card.js").read_bytes())
        finally:
            process.terminate()
            process.communicate(timeout=5)

    def test_init_dry_run_idempotence_and_preservation(self):
        plan = self.call("init")
        self.assertEqual(plan["action"], "dry-run")
        self.assertTrue(plan["writes"])
        self.assertEqual(snapshot(self.project), self.original)
        installed = self.initialized()
        self.assertEqual(installed, plan["bundle"])
        self.assert_original()
        before = snapshot(self.project)
        self.assertEqual(self.call("init", "--apply")["action"], "unchanged")
        self.assertEqual(snapshot(self.project), before)
        self.assertEqual(self.call("doctor")["prototype_integrity"], "verified")
        self.assertEqual(self.call("status")["client_configuration"], "not implemented")

    def test_global_upgrade_and_active_flight(self):
        installed = self.initialized()
        state = self.project / ".flightcheck"
        lock = json.loads((state / "lock.json").read_text())
        (state / "active").mkdir()
        flight = {"id": "in-progress", "bundle": installed, "runtime": lock["runtime"]}
        (state / "active/flight.json").write_text(json.dumps(flight))
        before = snapshot(self.project)
        self.install_cli("0.0.0.dev59")
        self.assertEqual(snapshot(self.project), before)
        self.assertEqual(self.call("status")["bundle"], installed)
        refusal = self.call("upgrade", "--from", installed, "--apply", expected=1)
        self.assertIn("ongoing flight", refusal["error"])
        self.assertEqual(snapshot(self.project), before)
        self.assertEqual(json.loads((state / "active/flight.json").read_text()), flight)
        (state / "active/flight.json").unlink()
        before = snapshot(self.project)
        self.assertEqual(self.call("upgrade", "--from", installed)["action"], "dry-run")
        self.assertEqual(snapshot(self.project), before)
        upgraded = self.call("upgrade", "--from", installed, "--apply")["bundle"]
        self.assertNotEqual(upgraded, installed)
        self.assertTrue((state / "versions" / installed).is_dir())
        self.assertEqual(self.call("doctor")["version"], "0.0.0.dev59")
        for name, value in before.items():
            if name.startswith(".flightcheck/versions/"):
                self.assertEqual(snapshot(self.project)[name], value)
        self.assert_original()

    def test_conflicts_and_upgrade_fail_without_changes(self):
        installed = self.initialized()
        self.install_cli("0.0.0.dev59")
        before = snapshot(self.project)
        self.assertIn("--from", self.call("upgrade", "--from", "stale", "--apply", expected=1)["error"])
        self.assertEqual(snapshot(self.project), before)
        self.assertIn("explicit upgrade", self.call("init", "--apply", expected=1)["error"])
        self.assertEqual(snapshot(self.project), before)
        asset = self.project / ".flightcheck/versions" / installed / "status-card/task.js"
        original = asset.read_bytes()
        asset.write_text("local edit\n")
        before = snapshot(self.project)
        self.assertIn("Modified installed asset", self.call("doctor", expected=1)["error"])
        self.call("upgrade", "--from", installed, "--apply", expected=1)
        self.assertEqual(snapshot(self.project), before)
        asset.unlink()
        self.assertIn("inventory", self.call("doctor", expected=1)["error"])
        asset.symlink_to(self.project / "AGENTS.md")
        self.assertIn("Symlink", self.call("upgrade", "--from", installed, "--apply", expected=1)["error"])
        self.assert_original()
        asset.unlink()
        asset.write_bytes(original)
        self.call("doctor")
        lock_path = self.project / ".flightcheck/lock.json"
        lock = json.loads(lock_path.read_text())
        lock["bundle"] = "../outside"
        lock_path.write_text(json.dumps(lock))
        before = snapshot(self.project)
        self.assertIn("Invalid prototype lock", self.call("upgrade", "--from", installed, "--apply", expected=1)["error"])
        self.assertEqual(snapshot(self.project), before)

    def test_challenge_policy_preservation(self):
        # Baseline compatibility control uses the documented pinned Git/manual
        # channel, whose explicit adaptation merges selected files without
        # replacing existing project policy. Current witness uses the wheel CLI.
        if os.environ.get("FC_MANUAL_CONTROL") == "1":
            source = Path(os.environ["FC_MANUAL_SOURCE"]) / "examples/existing-project"
            for _ in range(2):
                for name in ["docs/development-workflow.md", "scripts/capture_check.py",
                             "scripts/handoff.py", "scripts/proof.py", "scripts/recovery.py",
                             "scripts/behavior.py", "scripts/disposition.py"]:
                    target = self.project / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source / name, target)
                self.assert_original()
        else:
            self.initialized()
            self.assert_original()
            before = snapshot(self.project)
            self.call("init", "--apply")
            self.assertEqual(snapshot(self.project), before)
        self.assert_original()

    def test_requested_destination_conflicts_and_reuse(self):
        installed = self.initialized()
        state = self.project / ".flightcheck"
        old_lock = (state / "lock.json").read_bytes()
        self.install_cli("0.0.0.dev59")
        incoming = self.call("upgrade", "--from", installed)["bundle"]
        self.call("upgrade", "--from", installed, "--apply")
        destination = state / "versions" / incoming
        saved = self.scratch / (self.project.name + "-saved-bundle")
        shutil.copytree(destination, saved)
        (state / "lock.json").write_bytes(old_lock)
        for variant in ["file", "incomplete", "modified"]:
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink()
            if variant == "file":
                destination.write_text("Unmanaged collision\n")
            elif variant == "incomplete":
                destination.mkdir()
            else:
                shutil.copytree(saved, destination)
                (destination / "status-card/task.js").write_text("Local edit\n")
            before = tree_snapshot(self.project)
            for apply in [[], ["--apply"]]:
                self.call("upgrade", "--from", installed, *apply, expected=1)
                self.assertEqual(tree_snapshot(self.project), before)
        shutil.rmtree(destination)
        shutil.copytree(saved, destination)
        before = tree_snapshot(self.project)
        plan = self.call("upgrade", "--from", installed)
        self.assertTrue(plan["reused_bundle"])
        self.assertEqual(plan["writes"], [".flightcheck/lock.json"])
        self.assertEqual(tree_snapshot(self.project), before)
        applied = self.call("upgrade", "--from", installed, "--apply")
        self.assertTrue(applied["reused_bundle"])
        self.assertEqual(applied["writes"], plan["writes"])
        self.assertEqual(self.call("doctor")["bundle"], incoming)
        self.assert_original()

    def test_requested_io_failure_rollback(self):
        def injected(command, fault, *options):
            if fault == "population":
                patch = ("original=cli.populate\n"
                         "def fail(*args):\n original(*args)\n raise OSError('Injected population failure')\n"
                         "cli.populate=fail\n")
            else:
                patch = ("original=cli.os.replace\n"
                         "def fail(src,dst):\n"
                         " if Path(dst).name=='lock.json': raise OSError('Injected lock replacement failure')\n"
                         " return original(src,dst)\ncli.os.replace=fail\n")
            code = "from pathlib import Path\nimport sys\nfrom flightcheck_prototype import cli\n" + patch
            code += "sys.argv=" + repr(["flightcheck-prototype", command, "--sandbox", str(self.project),
                                         "--apply", *options]) + "\nraise SystemExit(cli.main())\n"
            result = subprocess.run([str(self.python), "-B", "-c", code], env=self.env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("Injected", json.loads(result.stderr)["error"])
        before = tree_snapshot(self.project)
        injected("init", "population")
        self.assertEqual(tree_snapshot(self.project), before)
        installed = self.initialized()
        self.install_cli("0.0.0.dev59")
        before = tree_snapshot(self.project)
        injected("upgrade", "lock", "--from", installed)
        self.assertEqual(tree_snapshot(self.project), before)
        self.assertEqual(self.call("doctor")["bundle"], installed)

    def test_complete_workflow_configuration(self):
        self.initialized()
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.project)], check=True, env=self.env)
        settings = {name: (self.project / name).read_bytes() for name in
                    [".codex/config.toml", ".claude/settings.json", "nested/AGENTS.md", "LICENSE"]}
        evidence = self.scratch / (self.project.name + "-evidence")
        config = self.scratch / (self.project.name + "-choices.json")
        config.write_text(json.dumps({"activation": "opt-in", "delivery": "No provider writes",
            "evidence_dir": str(evidence), "python": sys.executable, "default_branch": "main",
            "nit_tracker": "Private rehearsal observations", "policy_reference": "Owner's installed-flight rehearsal",
            "checks": [{"name": "Native checks", "command": [sys.executable, "-B", "-m", "unittest", "discover"], "phase": "cheap"}]}))
        before = tree_snapshot(self.project)
        plan = self.call("configure", "--agent", "both", "--config", str(config))
        self.assertEqual(plan["workflow"]["status"], "planned")
        self.assertEqual(tree_snapshot(self.project), before)
        applied = self.call("configure", "--agent", "both", "--config", str(config), "--apply")
        self.assertEqual(applied["workflow"]["status"], "ready_for_client_probe")
        self.assertEqual(applied["workflow"]["runtime"]["card_http"], "passed")
        state = json.loads((self.project / ".flightcheck/installation.json").read_text())
        self.assertEqual(state["source"]["revision"], subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip())
        self.assertEqual(state["source"]["tree"], subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip())
        for name in ["capture_check", "handoff", "proof", "recovery", "behavior", "disposition"]:
            self.assertEqual((self.project / (".flightcheck/scripts/" + name + ".py")).read_bytes(),
                             (ROOT / ("examples/existing-project/scripts/" + name + ".py")).read_bytes())
        for name in [".agents/skills/develop-change/SKILL.md", ".codex/agents/workflow-code-reviewer.toml",
                     ".codex/agents/workflow-evidence-reviewer.toml", ".claude/skills/develop-change/SKILL.md",
                     ".claude/agents/workflow-code-reviewer.md", ".flightcheck/status-card/task.js"]:
            self.assertTrue((self.project / name).is_file(), name)
        for name in ["AGENTS.md", "CLAUDE.md"]:
            self.assertTrue((self.project / name).read_bytes().startswith(self.original[name][0]))
            self.assertEqual(stat.S_IMODE((self.project / name).stat().st_mode), self.original[name][1])
        for name, data in settings.items():
            self.assertEqual((self.project / name).read_bytes(), data)
        before = tree_snapshot(self.project)
        self.call("configure", "--agent", "both", "--config", str(config), "--apply")
        self.assertEqual(tree_snapshot(self.project), before)
        # The canonical source materialization is gone. Deny access to the original
        # checkout as well, then execute the installed public verifier.
        guard = self.scratch / (self.project.name + "-source-read-guard")
        guard.mkdir()
        (guard / "sitecustomize.py").write_text(
            "from pathlib import Path\nimport os,sys\nROOT=Path(" + repr(str(ROOT)) + ")\n"
            "def deny_source(event,args):\n"
            " if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):\n"
            "  p=Path(os.fsdecode(args[0])).absolute()\n"
            "  if p==ROOT or ROOT in p.parents: raise PermissionError('Original source access denied')\n"
            "sys.addaudithook(deny_source)\n")
        isolated = dict(self.env, PYTHONPATH=str(guard))
        denied = subprocess.run([str(self.python), "-B", "-c",
                                 "from pathlib import Path;Path(" + repr(str(ROOT / "README.md")) + ").read_bytes()"],
                                cwd=self.project, env=isolated, capture_output=True, text=True)
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("Original source access denied", denied.stderr)
        result = subprocess.run([str(self.python), "-B",
                                 str(self.project / ".flightcheck/install.py"), "verify", "--target", str(self.project)],
                                cwd=self.project, env=isolated, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "ready_for_client_probe")
        modified = self.project / ".flightcheck/status-card/task.js"
        modified.write_text("Owner's local change\n")
        before = tree_snapshot(self.project)
        self.call("configure", "--agent", "both", "--config", str(config), "--apply", expected=1)
        self.assertEqual(tree_snapshot(self.project), before)
        modified.write_bytes((ROOT / "status-card/task.js").read_bytes())
        sentinel = self.scratch / (self.project.name + "-external-sentinel")
        sentinel.write_text("External owner bytes\n")
        sentinel.chmod(0o600)
        external = (sentinel.read_bytes(), stat.S_IMODE(sentinel.stat().st_mode))
        modified.unlink()
        modified.symlink_to(sentinel)
        before = tree_snapshot(self.project)
        for options in [[], ["--apply"]]:
            self.call("configure", "--agent", "both", "--config", str(config), *options, expected=1)
            self.assertEqual(tree_snapshot(self.project), before)
            self.assertEqual((sentinel.read_bytes(), stat.S_IMODE(sentinel.stat().st_mode)), external)
        modified.unlink()
        modified.write_bytes((ROOT / "status-card/task.js").read_bytes())
        parent = modified.parent
        backup = self.scratch / (self.project.name + "-external-card-directory")
        shutil.move(parent, backup)
        parent.symlink_to(backup, target_is_directory=True)
        before = tree_snapshot(self.project)
        external = tree_snapshot(backup)
        for options in [[], ["--apply"]]:
            self.call("configure", "--agent", "both", "--config", str(config), *options, expected=1)
            self.assertEqual(tree_snapshot(self.project), before)
            self.assertEqual(tree_snapshot(backup), external)
        parent.unlink()
        shutil.move(backup, parent)
        self.call("configure", "--agent", "both", "--config", str(config))


if __name__ == "__main__":
    unittest.main()
