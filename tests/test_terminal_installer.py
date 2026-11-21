"""Run built terminal artifacts against real disposable Git projects, offline."""
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile

PRODUCT = Path(os.environ.get("FLIGHTCHECK_PRODUCT_ROOT", Path(__file__).resolve().parents[1])).resolve()
BASE_PYTHON = str(Path(getattr(sys, "_base_executable", sys.executable)).resolve())


class TerminalInstallerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.area = tempfile.TemporaryDirectory(prefix="terminal-artifacts-")
        cls.addClassCleanup(cls.area.cleanup)
        cls.artifacts = Path(cls.area.name).resolve() / "artifacts"
        cls.env = dict(os.environ, FLIGHTCHECK_BUILD_DEVELOPMENT="1", PYTHONDONTWRITEBYTECODE="1",
                       GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0", PIP_NO_INDEX="1")
        cls.env.pop("PYTHONPATH", None)
        result = subprocess.run([sys.executable, "-B", "-m", "build", "--wheel", "--sdist", "--no-isolation",
                                 "--outdir", str(cls.artifacts), str(PRODUCT)], env=cls.env, capture_output=True, text=True)
        if result.returncode:
            raise AssertionError("Artifact build failed: " + result.stdout + result.stderr)
        cls.wheel = next(cls.artifacts.glob("*.whl"))
        cls.sdist = next(cls.artifacts.glob("*.tar.gz"))
        cls.tool = Path(cls.area.name).resolve() / "tool"
        cls.install_tool(cls.tool, cls.wheel)

    @classmethod
    def install_tool(cls, destination, wheel):
        subprocess.run([BASE_PYTHON, "-B", "-m", "venv", str(destination)], env=cls.env, check=True, capture_output=True)
        r = subprocess.run([str(destination / "bin/python"), "-B", "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)],
                           env=cls.env, capture_output=True, text=True)
        if r.returncode:
            raise AssertionError(r.stdout + r.stderr)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="terminal-project-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        self.environ = dict(self.env, FLIGHTCHECK_INSTALLER_STATE_DIR=str(self.root / "private-state"))
        for args in (("init", "-q", "-b", "trunk"), ("config", "user.name", "Terminal fixture"),
                     ("config", "user.email", "fixture@example.invalid")):
            self.git(*args)
        owners = {"AGENTS.md": "# Owner policy\n\nDo not replace this.\n", "CLAUDE.md": "# Independent Claude policy\n\nNo provider writes.\n",
                  ".claude/settings.json": '{"permissions":{"allow":["Read(existing/**)"]},"hooks":{}}\n',
                  ".codex/config.toml": 'sandbox_mode = "read-only"\n', "nested/AGENTS.md": "Nested owner policy\n",
                  "LICENSE": "Existing application license\n", "requirements.txt": "# Existing project dependencies\n"}
        for name, text in owners.items():
            p = self.project / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        (self.project / "AGENTS.md").chmod(0o640)
        (self.project / "CLAUDE.md").chmod(0o600)
        self.git("add", ".")
        self.git("-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "commit", "-qm", "Owner project")
        self.git("update-ref", "refs/remotes/origin/trunk", "HEAD")
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
        self.config = self.root / "choices.json"
        self.values = {"activation": "opt-in", "delivery": "No provider writes; leave edits uncommitted",
                       "evidence_dir": str(self.root / "evidence"), "python": BASE_PYTHON,
                       "default_branch": "trunk", "nit_tracker": "Private notes; no provider writes",
                       "reviewer_access": "Pending native read-only qualification; no grants",
                       "policy_reference": "Owner policy and explicit terminal fixture setup",
                       "checks": [{"name": "Must not run during setup", "command": [BASE_PYTHON, "-c", "raise SystemExit(93)"], "phase": "cheap"}]}
        self.save_config()
        self.plan_path = self.root / "reviewed-plan.json"
        self.before = self.files()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.project), *args], env=self.environ, text=True).strip()

    def save_config(self):
        self.config.write_text(json.dumps(self.values))

    def files(self):
        return {str(p.relative_to(self.project)): (p.read_bytes(), stat.S_IMODE(p.stat().st_mode))
                for p in self.project.rglob("*") if p.is_file() and ".git" not in p.relative_to(self.project).parts}

    def cli(self, *args, expected=0, tool=None):
        r = subprocess.run([str((tool or self.tool) / "bin/flightcheck"), *map(str, args), "--json"],
                           cwd=self.project, env=self.environ, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, expected, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def plan(self, agent="both", tool=None):
        return self.cli("init", self.project, "--agent", agent, "--config", self.config, "--plan", self.plan_path, tool=tool)

    def apply(self, expected=0, tool=None):
        return self.cli("init", self.project, "--apply", self.plan_path, expected=expected, tool=tool)

    def test_preview_complete_install_and_preservation(self):
        plan = self.plan()
        self.assertEqual(self.files(), self.before, "Preview must not write the project")
        self.assertTrue(plan["plan_sha256"])
        self.assertTrue(all(set(("before", "after", "action", "mode")) <= set(row) for row in plan["operations"]))
        result = self.apply()
        self.assertEqual(result["status"], "ready_for_client_probe")
        self.assertEqual(result["runtime"]["card_http"], "passed")
        self.assertIn("pending", result["client_qualification"])
        for name in ("AGENTS.md", "CLAUDE.md"):
            self.assertTrue((self.project / name).read_bytes().startswith(self.before[name][0]))
            self.assertEqual(stat.S_IMODE((self.project / name).stat().st_mode), self.before[name][1])
        for name in set(self.before) - {"AGENTS.md", "CLAUDE.md"}:
            self.assertEqual(self.files()[name], self.before[name], name)
        for path in (".agents/skills/develop-change/SKILL.md", ".claude/skills/develop-change/SKILL.md",
                     ".claude/agents/workflow-code-reviewer.md", ".claude/agents/workflow-evidence-reviewer.md",
                     ".flightcheck/status-card/reply.py", ".flightcheck/scripts/capture_check.py", ".flightcheck/LICENSE"):
            self.assertTrue((self.project / path).is_file(), path)
        installed = self.files()
        again = self.plan()
        self.assertTrue(all(row["action"] == "unchanged" for row in again["operations"]))
        self.apply()
        self.assertEqual(self.files(), installed)
        self.assertEqual(self.cli("doctor", self.project)["status"], "ready_for_client_probe")
        normal_env = dict(self.environ)
        normal_env.pop("PYTHONDONTWRITEBYTECODE", None)
        checked = subprocess.run([str(self.tool / "bin/flightcheck"), "doctor", str(self.project), "--json"],
                                 cwd=self.project, env=normal_env, capture_output=True, text=True)
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertEqual(self.files(), installed, "Doctor in a normal shell must not create project bytecode or other files")

    def test_terminal_choices_and_noninteractive_requirements(self):
        denied = self.cli("init", self.project, expected=1)
        self.assertIn("--config", denied["error"])
        self.assertEqual(self.files(), self.before)
        # Exercise the real wizard/entry point with controlled terminal answers;
        # no mutating project check or native model session is launched.
        answers = [BASE_PYTHON, "", str(self.root / "evidence"), "", "", "", BASE_PYTHON + " -c pass", "", "y"]
        code = """from unittest.mock import patch
import sys
from flightcheck_cli.cli import main
with patch('sys.stdin.isatty',return_value=True), patch('builtins.input',side_effect=ANSWERS):
    raise SystemExit(main(['init',TARGET,'--agent','claude']))
""".replace("ANSWERS", repr(answers)).replace("TARGET", repr(str(self.project)))
        r = subprocess.run([str(self.tool / "bin/python"), "-B", "-c", code], cwd=self.project, env=self.environ, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        project = json.loads((self.project / ".flightcheck/project.json").read_text())
        self.assertEqual(project["activation"], "opt-in")
        self.assertEqual(project["delivery"], "No provider writes without owner approval")
        self.assertIn("no automatic grants", project["reviewer_access"])
        self.assertFalse((self.project / ".agents").exists(), "Explicit Claude selection must not install Codex")

    def test_plan_drift_links_and_conflicts(self):
        self.plan()
        (self.project / "CLAUDE.md").write_text("Later owner edit\n")
        edited = self.files()
        self.assertIn("stale", self.apply(expected=1)["error"])
        self.assertEqual(self.files(), edited)
        (self.project / "CLAUDE.md").write_bytes(self.before["CLAUDE.md"][0])
        self.plan()
        (self.project / "AGENTS.md").chmod(0o600)
        self.assertIn("stale", self.apply(expected=1)["error"])
        (self.project / "AGENTS.md").chmod(self.before["AGENTS.md"][1])
        # A reviewed plan cannot be silently retargeted or have its config edited.
        raw = self.plan_path.read_bytes()
        changed = json.loads(raw)
        changed["configuration"]["delivery"] = "Changed grant"
        self.plan_path.write_text(json.dumps(changed))
        self.assertIn("digest", self.apply(expected=1)["error"])
        self.plan_path.write_bytes(raw)
        original = self.project / "CLAUDE.md"
        owner_copy = self.root / "owner-copy"
        owner_copy.write_bytes(original.read_bytes())
        original.unlink()
        original.symlink_to(owner_copy)
        self.assertIn("symlink", self.apply(expected=1)["error"].lower())
        self.assertEqual(owner_copy.read_bytes(), self.before["CLAUDE.md"][0])
        original.unlink()
        original.write_bytes(self.before["CLAUDE.md"][0])
        original.chmod(self.before["CLAUDE.md"][1])
        # Replace the entire CLI with another source/asset version, then apply
        # the old reviewed plan. This is an actual independent Plan challenge.
        other = self.variant_tool()
        self.assertIn("stale", self.apply(tool=other, expected=1)["error"])
        self.assertEqual(self.files(), self.before)
        self.apply()
        owned = self.project / ".flightcheck/scripts/handoff.py"
        owned.write_bytes(owned.read_bytes() + b"\n# Owner change\n")
        modified = self.files()
        self.cli("init", self.project, "--agent", "both", "--config", self.config, expected=1)
        self.assertEqual(self.files(), modified)

    def test_failed_verification_restores_bytes_and_modes(self):
        runtime = self.root / "fail-runtime"
        runtime.write_text("#!" + BASE_PYTHON + "\nimport os,sys\nif '--runtime-worker' in sys.argv: raise SystemExit(89)\nos.execv(" + repr(BASE_PYTHON) + ",[" + repr(BASE_PYTHON) + "]+sys.argv[1:])\n")
        runtime.chmod(0o700)
        self.values["python"] = str(runtime)
        self.save_config()
        self.plan()
        result = self.apply(expected=1)
        self.assertIn("original project restored", result["error"])
        self.assertEqual(self.files(), self.before)
        self.assertFalse((self.project / ".flightcheck").exists(), "New empty staging directories should be removed")
        journals = list((self.root / "private-state").rglob("transaction.json"))
        self.assertEqual(len(journals), 1)
        self.assertEqual(json.loads(journals[0].read_text())["status"], "rolled_back")
        self.assertEqual(self.cli("recover", self.project)["status"], "rolled_back")

    def test_crash_recovery_refuses_new_owner_edits(self):
        self.plan()
        code = """from contextlib import contextmanager
import os
import flightcheck_cli.cli as cli
original=cli.installer
@contextmanager
def interrupted():
    with original() as (module,*rest):
        write=module.write_file
        def crash(root,name,before,after,**kwargs):
            write(root,name,before,after,**kwargs)
            if name=='CLAUDE.md':os._exit(77)
        module.write_file=crash
        yield (module,*rest)
cli.installer=interrupted
raise SystemExit(cli.main(['init',TARGET,'--apply',PLAN,'--json']))
""".replace("TARGET", repr(str(self.project))).replace("PLAN", repr(str(self.plan_path)))
        r = subprocess.run([str(self.tool / "bin/python"), "-B", "-c", code], cwd=self.project, env=self.environ, capture_output=True)
        self.assertEqual(r.returncode, 77, r.stdout + r.stderr)
        after = self.files()
        self.assertNotEqual(after["CLAUDE.md"], self.before["CLAUDE.md"])
        self.assertIn("recover", self.cli("doctor", self.project, expected=1)["error"])
        (self.project / "CLAUDE.md").write_text("New owner work after interruption\n")
        changed = self.files()
        self.assertIn("Recovery conflict", self.cli("recover", self.project, expected=1)["error"])
        self.assertEqual(self.files(), changed, "Refused recovery must not mix in restoration of other files")
        (self.project / "CLAUDE.md").write_bytes(after["CLAUDE.md"][0])
        self.assertEqual(self.cli("recover", self.project)["status"], "rolled_back")
        self.assertEqual(self.files(), self.before)

    def test_wheel_sdist_offline_and_tool_removal(self):
        with zipfile.ZipFile(self.wheel) as archive:
            metadata = archive.read(next(n for n in archive.namelist() if n.endswith("/METADATA"))).decode()
            self.assertIn("License-Expression: FSL-1.1-MIT", metadata)
            self.assertNotIn("Requires-Dist:", metadata)
            self.assertTrue(any(n.endswith("/LICENSE") for n in archive.namelist()))
        unpacked = self.root / "sdist"
        unpacked.mkdir()
        with tarfile.open(self.sdist) as archive:
            # The artifact is built locally above; never extract untrusted input.
            archive.extractall(unpacked, filter="data")
        source = next(unpacked.iterdir())
        self.assertFalse((source / ".git").exists())
        rebuilt = self.root / "offline-wheel"
        r = subprocess.run([sys.executable, "-B", "-m", "build", "--wheel", "--no-isolation", "--outdir", str(rebuilt), str(source)],
                           cwd=self.root, env={**self.environ, "PIP_NO_INDEX": "1"}, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        tool = self.root / "offline-tool"
        self.install_tool(tool, next(rebuilt.glob("*.whl")))
        self.assertEqual(self.files(), self.before, "Installing/importing the package cannot configure a project")
        self.plan(tool=tool)
        self.apply(tool=tool)
        installed = self.files()
        shutil.rmtree(tool)
        result = subprocess.run([BASE_PYTHON, "-B", str(self.project / ".flightcheck/install.py"), "verify", "--target", str(self.project)],
                                cwd=self.root, env=self.environ, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "ready_for_client_probe")
        self.assertEqual(self.files(), installed)
        self.assertEqual(json.loads((self.project / ".flightcheck/project.json").read_text())["python"], BASE_PYTHON)

    def variant_tool(self):
        tool = self.root / "variant-tool"
        artifacts = self.root / "variant-artifacts"
        code = """from pathlib import Path
import subprocess,sys
from flightcheck_cli.source import installer
with installer() as (_,root,*rest):
    path=root/'examples/existing-project/docs/project-resources.md'
    path.write_bytes(path.read_bytes()+b'\\nChanged source resource for stale-plan control.\\n')
    pyproject=root/'pyproject.toml'
    pyproject.write_text(pyproject.read_text().replace('version = "0.1.0a1"','version = "0.1.0a2"'))
    for args in (['add','.'],['-c','user.name=Variant fixture','-c','user.email=fixture@example.invalid','-c','commit.gpgsign=false','commit','-qm','Different packaged source fixture']):
        subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True)
    subprocess.run([BUILD_PYTHON,'-B','-m','build','--wheel','--no-isolation','--outdir',ARTIFACTS,str(root)],check=True,capture_output=True)
""".replace("BUILD_PYTHON", repr(sys.executable)).replace("ARTIFACTS", repr(str(artifacts)))
        r = subprocess.run([str(self.tool / "bin/python"), "-B", "-c", code], cwd=self.root, env=self.environ, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.install_tool(tool, next(artifacts.glob("*.whl")))
        return tool

    def test_provenance_corruption_and_existing_version_refusal(self):
        self.plan()
        self.apply()
        installed = self.files()
        other = self.variant_tool()
        self.cli("init", self.project, "--agent", "both", "--config", self.config, tool=other, expected=1)
        self.assertEqual(self.files(), installed)
        self.assertEqual(self.cli("doctor", self.project, tool=other)["status"], "ready_for_client_probe")
        corrupt = self.root / "corrupt-tool"
        self.install_tool(corrupt, self.wheel)
        package = next((corrupt / "lib").glob("python*/site-packages/flightcheck_cli"))
        (package / "source.tar").write_bytes(b"corrupted")
        result = self.cli("inspect", self.project, tool=corrupt, expected=1)
        self.assertIn("hash mismatch", result["error"])
        self.assertEqual(self.files(), installed)
        # A project interpreter from the disposable CLI environment is forbidden.
        fresh = self.root / "fresh"
        fresh.mkdir()
        subprocess.run(["git", "-C", str(fresh), "init", "-q", "-b", "trunk"], env=self.environ, check=True)
        self.values["python"] = str(self.tool / "bin/python")
        self.save_config()
        error = self.cli("init", fresh, "--agent", "claude", "--config", self.config, expected=1)
        self.assertIn("tool environment", error["error"])
        self.assertFalse((fresh / ".flightcheck").exists())
        wrapper = self.root / "aliased-tool-python"
        wrapper.write_text("#!/bin/sh\nexec " + str(self.tool / "bin/python") + " \"$@\"\n")
        wrapper.chmod(0o700)
        self.values["python"] = str(wrapper)
        self.save_config()
        alias_error = self.cli("init", fresh, "--agent", "claude", "--config", self.config, expected=1)
        self.assertIn("tool environment", alias_error["error"])
        self.assertFalse((fresh / ".flightcheck").exists())

    def test_documented_terminal_entrypoint(self):
        readme = (PRODUCT / "README.md").read_text()
        self.assertNotIn("Install FlightCheck from https://github.com", readme)
        self.assertIn("pipx install", readme)
        self.assertIn("flightcheck init", readme)
        self.assertIn("flightcheck doctor", readme)
        self.assertNotIn("[PyPI distribution]", readme)
        self.assertLess(readme.index("## Get started"), readme.index("## Guides"))
        self.assertTrue(readme.rstrip().endswith("[bug reports and feature requests are welcome](CONTRIBUTING.md)."))
        guide = (PRODUCT / "setup/README.md").read_text()
        self.assertIn("flightcheck recover", guide)
        self.assertIn("--apply", guide)
        self.assertIn("#14", guide)
        result = subprocess.run([str(self.tool / "bin/flightcheck"), "--help"], env=self.environ, cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        for command in ("init", "doctor", "recover"):
            self.assertIn(command, result.stdout)


if __name__ == "__main__":
    unittest.main()
