"""Exercise complete installation through its public CLI in disposable repositories."""

import importlib.util
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

PRODUCT = Path(os.environ.get("FLIGHTCHECK_PRODUCT_ROOT", Path(__file__).resolve().parents[1]))


class InstallationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.target = self.root / "project"
        self.source.mkdir()
        self.target.mkdir()
        self.env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_TERMINAL_PROMPT="0", PYTHONDONTWRITEBYTECODE="1")
        manifest = json.loads((PRODUCT / "setup/manifest.json").read_text())
        for name in {row[0] for row in manifest["files"]}:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PRODUCT / name, path)
        for repo in (self.source, self.target):
            self.git(repo, "init", "-q", "-b", "trunk")
            self.git(repo, "config", "user.email", "fixture@example.invalid")
            self.git(repo, "config", "user.name", "Installation fixture")
        self.git(self.source, "add", ".")
        self.git(self.source, "commit", "-qm", "Pinned fixture source")
        self.owner_agents = b"# Local model policy\n\nKeep this exact owner text.\n"
        self.owner_claude = b"# Claude policy\n\nThis file has independent instructions.\n"
        (self.target / "AGENTS.md").write_bytes(self.owner_agents)
        (self.target / "CLAUDE.md").write_bytes(self.owner_claude)
        for name, text in [(".claude/settings.json", '{"permissions":{"allow":["Read(existing/**)"]},"hooks":{}}\n'),
                           (".codex/config.toml", 'sandbox_mode = "read-only"\n'),
                           ("nested/AGENTS.md", "Nested policy stays separate.\n")]:
            path = self.target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        self.git(self.target, "add", ".")
        self.git(self.target, "commit", "-qm", "Existing project")
        self.git(self.target, "update-ref", "refs/remotes/origin/trunk", "HEAD")
        self.git(self.target, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
        self.config = self.root / "choices.json"
        self.choices = {"evidence_dir": str(self.root / "evidence"), "python": sys.executable,
                        "nit_tracker": "Existing project tracker; permission required",
                        "policy_reference": "Fixture owner's setup decision",
                        "checks": [{"name": "Native fixture check", "command": [sys.executable, "-B", "-c", "pass"], "phase": "cheap"}]}
        self.save_choices()
        self.installer = self.source / "setup/install.py"

    def git(self, root, *args):
        return subprocess.check_output(["git", "-C", str(root), *args], env=self.env, text=True).strip()

    def save_choices(self):
        self.config.write_text(json.dumps(self.choices))

    def cli(self, command, expected=0, agent="both", installed=False):
        entry = self.target / ".flightcheck/install.py" if installed else self.installer
        args = [sys.executable, "-B", str(entry), command, "--target", str(self.target)]
        if command in ("plan", "apply"):
            args += ["--agent", agent, "--config", str(self.config)]
        result = subprocess.run(args, capture_output=True, text=True, env=self.env, timeout=25)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        value = json.loads(result.stdout)
        if expected:
            self.assertEqual(value["status"], "incomplete")
        return value

    def files(self):
        return {str(p.relative_to(self.target)): p.read_bytes() for p in self.target.rglob("*")
                if p.is_file() and ".git" not in p.relative_to(self.target).parts}

    def test_complete_install_both_agents(self):
        before = self.files()
        preview = self.cli("plan")
        self.assertEqual(preview["status"], "planned")
        self.assertEqual(before, self.files(), "Plan must not mutate the target")
        result = self.cli("apply")
        self.assertEqual(result["status"], "ready_for_client_probe")
        self.assertEqual(result["runtime"]["card_http"], "passed")
        self.assertIn("pending", result["client_qualification"])
        state = json.loads((self.target / ".flightcheck/installation.json").read_text())
        self.assertEqual(state["source"]["revision"], self.git(self.source, "rev-parse", "HEAD"))
        for name in ("capture_check", "handoff", "proof", "recovery", "behavior", "disposition"):
            self.assertEqual((self.target / (".flightcheck/scripts/" + name + ".py")).read_bytes(),
                             (self.source / ("examples/existing-project/scripts/" + name + ".py")).read_bytes())
        for name in ("serve.py", "task_status.py", "maintainer.py", "task_details.py", "task.js", "task.html", "card.css"):
            self.assertEqual((self.target / (".flightcheck/status-card/" + name)).read_bytes(),
                             (self.source / ("status-card/" + name)).read_bytes())
        for client in (".agents", ".claude"):
            skill = (self.target / client / "skills/develop-change/SKILL.md").read_text()
            self.assertIn("../../../.flightcheck/docs/development-workflow.md", skill)
        for role in ("code", "evidence"):
            native = (self.target / (".claude/agents/workflow-" + role + "-reviewer.md")).read_text()
            self.assertIn("tools: Read, Grep, Glob\n", native)
            self.assertIn("test_requests", native)
            self.assertTrue((self.target / (".codex/agents/workflow-" + role + "-reviewer.toml")).is_file())
        shutil.rmtree(self.source)
        self.assertEqual(self.cli("verify", installed=True)["status"], "ready_for_client_probe")

    def test_reinstall_preserves_policy_and_reports_conflicts(self):
        original_settings = {name: (self.target / name).read_bytes() for name in (
            ".claude/settings.json", ".codex/config.toml", "nested/AGENTS.md")}
        self.cli("apply")
        first = self.files()
        self.cli("apply")
        self.assertEqual(first, self.files())
        self.assertTrue((self.target / "AGENTS.md").read_bytes().startswith(self.owner_agents))
        self.assertTrue((self.target / "CLAUDE.md").read_bytes().startswith(self.owner_claude))
        for name, data in original_settings.items():
            self.assertEqual((self.target / name).read_bytes(), data)
        self.assertEqual((self.target / "CLAUDE.md").read_text().count("<!-- FlightCheck:begin -->"), 1)
        script = self.target / ".flightcheck/scripts/handoff.py"
        script.write_bytes(script.read_bytes() + b"\n# Owner modification\n")
        missing = self.target / ".flightcheck/status-card/card.js"
        missing.unlink()
        modified = self.files()
        error = self.cli("apply", expected=1)
        self.assertIn("handoff.py", error["error"])
        self.assertEqual(modified, self.files(), "Conflict must precede unrelated repair writes")
        self.assertFalse(missing.exists())

    def test_verify_rejects_missing_or_modified_components(self):
        self.cli("apply")
        script = self.target / ".flightcheck/scripts/handoff.py"
        data = script.read_bytes()
        script.unlink()
        self.assertIn("handoff.py", self.cli("verify", expected=1, installed=True)["error"])
        script.write_bytes(data)
        asset = self.target / ".flightcheck/status-card/card.css"
        css = asset.read_bytes()
        asset.write_bytes(css + b"\n/* changed */\n")
        self.assertIn("card.css", self.cli("verify", expected=1, installed=True)["error"])
        asset.write_bytes(css)
        settings = self.target / ".flightcheck/project.json"
        original = settings.read_bytes()
        configured = json.loads(original)
        configured["python"] = str(self.root / "missing-interpreter")
        settings.write_text(json.dumps(configured))
        self.assertIn("missing-interpreter", self.cli("verify", expected=1, installed=True)["error"])
        settings.write_bytes(original)
        self.assertEqual(self.cli("verify", installed=True)["runtime"]["card_http"], "passed")
        # A new, internally consistent pinned source can still contain a runtime
        # failure. Hash checks alone must not establish card readiness.
        server = self.source / "status-card/serve.py"
        server.write_text("raise SystemExit('synthetic card runtime failure')\n")
        self.git(self.source, "add", ".")
        self.git(self.source, "commit", "-qm", "Runtime failure fixture")
        error = self.cli("apply", expected=1)
        self.assertIn("synthetic card runtime failure", error["error"])
        self.assertIn("synthetic card runtime failure", self.cli("verify", expected=1, installed=True)["error"])

    def test_detect_and_require_explicit_decisions(self):
        before = self.files()
        detected = self.cli("inspect")
        self.assertEqual(detected["default_branch"], "trunk")
        self.assertIn("CLAUDE.md", detected["existing_configuration"])
        self.assertEqual(detected["defaults"]["activation"], "opt-in")
        self.assertEqual(before, self.files())
        self.choices.pop("checks")
        self.save_choices()
        self.assertIn("checks", self.cli("apply", expected=1)["error"])
        self.assertEqual(before, self.files())
        self.choices["checks"] = [{"name": "Fixture", "command": [sys.executable, "-B", "-c", "pass"], "phase": "cheap"}]
        self.choices["activation"] = "default-for-coding"
        self.save_choices()
        self.assertIn("activation_reference", self.cli("apply", expected=1)["error"])
        self.assertEqual(before, self.files())
        self.choices["activation_reference"] = "Explicit fixture owner decision"
        self.save_choices()
        self.cli("apply", agent="claude")
        self.assertIn("Use FlightCheck for coding tasks", (self.target / "CLAUDE.md").read_text())
        self.assertIn("Ordinary questions", (self.target / "CLAUDE.md").read_text())
        self.assertNotIn("disable-model-invocation: true", (self.target / ".claude/skills/develop-change/SKILL.md").read_text())
        self.assertEqual((self.target / "AGENTS.md").read_bytes(), self.owner_agents)

    def test_source_identity_and_paths_are_guarded(self):
        before = self.files()
        (self.source / "untracked.txt").write_text("dirty source")
        self.assertIn("clean, pinned", self.cli("apply", expected=1)["error"])
        self.assertEqual(before, self.files())
        (self.source / "untracked.txt").unlink()
        outside = self.root / "outside"
        outside.mkdir()
        (self.target / ".flightcheck").symlink_to(outside, target_is_directory=True)
        self.assertIn("symlink", self.cli("apply", expected=1)["error"])
        self.assertEqual(list(outside.iterdir()), [])
        (self.target / ".flightcheck").unlink()
        self.choices["evidence_dir"] = str(self.target / "private-evidence")
        self.save_choices()
        self.assertIn("outside", self.cli("apply", expected=1)["error"])
        self.assertEqual(before, self.files())

    def test_selected_clients_and_codex_opt_in(self):
        self.cli("apply", agent="codex")
        self.assertIn("explicitly selects", (self.target / "AGENTS.md").read_text())
        self.assertIn("$develop-change", (self.target / "AGENTS.md").read_text())
        self.assertEqual((self.target / "CLAUDE.md").read_bytes(), self.owner_claude)
        self.assertFalse((self.target / ".claude/agents").exists())
        self.assertIn("Agent selection changed", self.cli("apply", expected=1, agent="both")["error"])

    def test_verify_rejects_truncated_inventory(self):
        self.cli("apply")
        path = self.target / ".flightcheck/installation.json"
        state = json.loads(path.read_text())
        state["files"].pop(".flightcheck/status-card/serve.py")
        path.write_text(json.dumps(state))
        self.assertIn("required components", self.cli("verify", expected=1, installed=True)["error"])

    def test_unsafe_manifest_and_public_evidence_are_rejected(self):
        manifest = self.source / "setup/manifest.json"
        value = json.loads(manifest.read_text())
        value["files"][0][1] = "../escape.py"
        manifest.write_text(json.dumps(value))
        self.git(self.source, "add", ".")
        self.git(self.source, "commit", "-qm", "Unsafe manifest fixture")
        self.assertIn("Unsafe", self.cli("apply", expected=1)["error"])
        self.assertFalse((self.root / "escape.py").exists())
        self.git(self.source, "reset", "--hard", "HEAD~1")
        evidence = self.root / "evidence"
        evidence.mkdir(mode=0o755)
        self.assertIn("owner-only", self.cli("apply", expected=1)["error"])
        self.assertFalse((self.target / ".flightcheck").exists())

    def test_partial_write_rolls_back_prior_content(self):
        spec = importlib.util.spec_from_file_location("installation", self.installer)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        operations = [
            {"path": "AGENTS.md", "before": self.owner_agents, "after": b"new block\n", "action": "update"},
            {"path": "new-file.md", "before": None, "after": b"new file\n", "action": "create"},
        ]
        real_write = module.write_file
        calls = []

        def failing_write(*args):
            calls.append(args[1])
            if len(calls) == 2:
                raise OSError("Synthetic disk error")
            return real_write(*args)

        with patch.object(module, "write_file", side_effect=failing_write):
            with self.assertRaises(OSError):
                module.apply_plan(self.target, operations)
        self.assertEqual((self.target / "AGENTS.md").read_bytes(), self.owner_agents)
        self.assertFalse((self.target / "new-file.md").exists())

    def test_installed_card_reply_adapters(self):
        self.cli("apply")
        for name in ("AGENTS.md", "CLAUDE.md"):
            text = (self.target / name).read_text()
            self.assertIn("before every controller reply", text)
            self.assertIn("TUI users", text)
            self.assertIn("raw reviewer JSON", text)
        for client in (".agents", ".claude"):
            folder = self.target / client / "skills/develop-change"
            self.assertIn("every user-facing controller reply", (folder / "SKILL.md").read_text())
            reference = (folder / "references/task-status.md").read_text()
            self.assertIn(".flightcheck/status-card/reply.py prepare", reference)
            self.assertIn(".flightcheck/status-card/reply.py check", reference)
            self.assertNotIn(".flightcheck/.flightcheck/", reference)
            self.assertIn("Before the first TUI reply", reference)
            self.assertIn("intermediate or interrupted", reference)
        for role in ("code", "evidence"):
            native = (self.target / (".claude/agents/workflow-" + role + "-reviewer.md")).read_text()
            self.assertIn("without a status footer", native)
            self.assertIn("hooks must be disabled", native)
        settings = (self.target / ".claude/settings.json").read_text()
        self.assertEqual(json.loads(settings)["hooks"], {})
        self.assertEqual(json.loads(settings)["permissions"]["allow"], ["Read(existing/**)"])
        self.assertFalse((self.target / ".codex/hooks.json").exists())
        entry = self.target / ".flightcheck/status-card/reply.py"
        env = dict(self.env, FLIGHTCHECK_STATE_DIR=str(self.root / "card state"))
        listeners = set()
        try:
            prepared = subprocess.run([sys.executable, "-B", str(entry), "prepare", "--task", "first-flight", "--execution", "local"],
                                      cwd=self.target, env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
            value = json.loads(prepared.stdout)
            for p in (self.root / "card state").glob("*/tasks/*/endpoint.json"):
                listeners.add(json.loads(p.read_text())["pid"])
            self.assertIn("regular browser", value["guidance"])
            self.assertIn(value["user_url"], value["guidance"])
            reply = self.root / "first-reply.txt"
            reply.write_text("Open the card in your browser.\n\n" + value["footer"])
            checked = subprocess.run([sys.executable, "-B", str(entry), "check", "--task", "first-flight",
                                      "--phase", "start", "--reply-file", str(reply), "--execution", "local"],
                                     cwd=self.target, env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        finally:
            for pid in listeners:
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

    def test_verification_deadline_reaps_stalled_listeners(self):
        pid_file = self.root / "listener.pid"
        common = ("import os,socket,time\nfrom pathlib import Path\n"
                  + "Path(" + repr(str(pid_file)) + ").write_text(str(os.getpid()))\n")
        variants = {
            "partial-startup": "print('FlightCheck status card at ', end='', flush=True)\ntime.sleep(120)\n",
            "trickled-http": (
                "server=socket.socket();server.bind(('127.0.0.1',0));server.listen(1)\n"
                "print('FlightCheck status card at http://127.0.0.1:%s/task/setup-check/' % server.getsockname()[1],flush=True)\n"
                "client,_=server.accept();client.recv(65536)\n"
                "client.sendall(b'HTTP/1.1 200 OK\\r\\nContent-Length: 999999\\r\\n\\r\\n{')\n"
                "while True:\n time.sleep(.2)\n client.sendall(b' ')\n"),
        }
        for label, body in variants.items():
            with self.subTest(label=label):
                (self.source / "status-card/serve.py").write_text(common + body)
                self.git(self.source, "add", ".")
                self.git(self.source, "commit", "-qm", "Stalled listener fixture " + label)
                # Install an internally consistent fixture without claiming a
                # runtime pass; the witness below invokes the real public verifier.
                spec = importlib.util.spec_from_file_location("installation_fixture", self.installer)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                argv = [str(self.installer), "apply", "--target", str(self.target),
                        "--agent", "both", "--config", str(self.config)]
                with patch.object(module, "runtime_probe", return_value={"fixture_only": True}), \
                        patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(module.main(), 0)
                start = time.monotonic()
                process = subprocess.Popen([sys.executable, "-B", str(self.target / ".flightcheck/install.py"),
                                            "verify", "--target", str(self.target)],
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           text=True, env=self.env, start_new_session=True)
                timed_out = False
                try:
                    try:
                        stdout, stderr = process.communicate(timeout=22)
                    except subprocess.TimeoutExpired:
                        timed_out = True
                        os.killpg(process.pid, signal.SIGKILL)
                        stdout, stderr = process.communicate(timeout=5)
                    self.assertFalse(timed_out, "Public verification exceeded its overall deadline: " + label)
                    self.assertLess(time.monotonic() - start, 22)
                    self.assertEqual(process.returncode, 1, stdout + stderr)
                    result = json.loads(stdout)
                    self.assertEqual(result["status"], "incomplete")
                    self.assertIn("deadline", result["error"])
                    self.assertIn("loopback", result["error"])
                    listener = int(pid_file.read_text())
                    with self.assertRaises(ProcessLookupError):
                        os.kill(listener, 0)
                finally:
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.communicate(timeout=5)

    def test_unsupported_and_unusable_runtimes_preserve_target(self):
        before = self.files()
        variants = {
            "old-python": "print('{\"platform\":\"posix\",\"version_info\":[3,8],\"version\":\"3.8 fixture\"}')\n",
            "non-posix": "print('{\"platform\":\"nt\",\"version_info\":[3,13],\"version\":\"non-POSIX fixture\"}')\n",
            "malformed": "print('not JSON')\n",
            "timeout": "import time;time.sleep(60)\n",
        }
        for label, body in variants.items():
            with self.subTest(label=label):
                runtime = self.root / ("runtime-" + label)
                runtime.write_text("#!" + sys.executable + "\n" + body)
                runtime.chmod(0o700)
                self.choices["python"] = str(runtime)
                self.save_choices()
                error = self.cli("plan", expected=1)["error"]
                self.assertTrue(error)
                self.assertEqual(before, self.files())
                if label != "timeout":
                    self.cli("apply", expected=1)
                    self.assertEqual(before, self.files())
