"""Native configuration witnesses shared by the five-case foundation suite."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from unittest.mock import patch

PRODUCT = Path(os.environ.get("FLIGHTCHECK_PRODUCT_ROOT", Path(__file__).resolve().parents[1])).resolve()
BASELINE = "952aaa74fafdcf2780e263d401235aa096e4c1ac"


class ConfigurationCases:
    def config_module(self, path, name):
        spec = importlib.util.spec_from_file_location(name, path)
        value = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(value)
        return value

    def config_git(self, root, *args):
        return subprocess.check_output(["git", "--no-optional-locks", "-C", str(root), *args], env=self.config_env, text=True).strip()

    @contextlib.contextmanager
    def config_fixture(self, legacy=False):
        self.assertTrue((PRODUCT / "workflow/scripts/project_config.py").is_file(), "Shared configuration model is required")
        with tempfile.TemporaryDirectory(prefix="foundation-config-") as tmp:
            area = Path(tmp).resolve()
            source, root = area / "source", area / "project"
            source.mkdir(); root.mkdir()
            self.config_env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                                   GIT_TERMINAL_PROMPT="0", FLIGHTCHECK_INSTALLER_STATE_DIR=str(area / "state"))
            manifest = json.loads((PRODUCT / "setup/manifest.json").read_bytes())
            if legacy:
                manifest = json.loads(subprocess.check_output(["git", "show", BASELINE + ":setup/manifest.json"], cwd=PRODUCT))
            for name in {r[0] for r in manifest["files"]}:
                dest = source / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                if legacy and name == "setup/install.py":
                    dest.write_bytes(subprocess.check_output(["git", "show", BASELINE + ":setup/install.py"], cwd=PRODUCT))
                elif name == "setup/manifest.json":
                    dest.write_text(json.dumps(manifest))
                else:
                    shutil.copyfile(PRODUCT / name, dest)
            for repo in (source, root):
                self.config_git(repo, "init", "-q", "-b", "trunk")
                self.config_git(repo, "config", "user.email", "fixture@example.invalid")
                self.config_git(repo, "config", "user.name", "Foundation fixture")
                (repo / "owner.txt").write_text("Preserve owner work\n")
                self.config_git(repo, "add", ".")
                self.config_git(repo, "commit", "-qm", "Pinned fixture")
            self.config_git(root, "update-ref", "refs/remotes/origin/trunk", "HEAD")
            self.config_git(root, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
            if not legacy:
                (root / ".flightcheck").mkdir()
                (root / ".flightcheck/.gitignore").write_text("/owner-local-only\n/project.json\n!/project.json\n")
            module = self.config_module(source / "setup/install.py", "foundation_source_installer")
            project_python = str(Path(getattr(sys, "_base_executable", sys.executable)).resolve(strict=True))
            values = {"python": project_python, "evidence_dir": str(area / "private-evidence"),
                      "nit_tracker": "private-notes", "policy_reference": "fixture owner setup",
                      "checks": [{"name": "record only", "command": [sys.executable, "-c", "raise SystemExit(93)"], "phase": "cheap"}],
                      "protected_branches": ["release"]}
            result, config, ops = module.plan_installation(source, root, module.load_manifest(), "codex", values)
            module.apply_plan(root, ops)
            sys.path.insert(0, str(PRODUCT / "src"))
            from flightcheck_cli import cli
            current = self.config_module(PRODUCT / "setup/install.py", "foundation_current_installer")
            pin = {"schema": 1, "source_revision": result["source"]["revision"], "runtime": cli.runtime_identity(config)}
            (root / ".flightcheck/distribution.json").write_bytes(cli.encoded(pin))
            with patch.dict(os.environ, self.config_env):
                yield area, root, current, module, cli, values

    def config_cli(self, *args, expected=0):
        result = subprocess.run([sys.executable, "-B", str(PRODUCT / "setup/install.py"), "config", *map(str, args), "--json"],
                                env=self.config_env, text=True, capture_output=True, timeout=25)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_configuration_contract(self):
        with self.config_fixture() as (area, root, engine, installed, cli, supplied):
            model = engine.project_model()
            direct = engine.configuration(root, supplied)
            self.assertEqual(direct["checkout_policy"]["mode"], "native-choice")
            self.assertEqual(model.protected(direct), ["release", "trunk"])
            before = model.snapshot(root)
            through_cli = self.config_cli("read", root)
            self.assertEqual(through_cli["values"], before["values"])
            self.assertEqual(through_cli["values"], direct)
            self.assertEqual(before["revision"], model.revision((root / model.CONFIG).read_bytes()))
            self.assertFalse(direct[model.META]["fields"]["default_branch"]["confirmed"])
            self.assertEqual(direct[model.META]["fields"]["default_branch"]["source"], "discovered")
            public = self.config_cli("read", root, "--shared")["values"]
            serialized = json.dumps(public)
            self.assertNotIn(str(area), serialized)
            self.assertNotIn(sys.executable, serialized)
            self.assertNotIn("raise SystemExit", serialized)
            self.assertNotIn("fixture owner setup", serialized)
            self.assertNotIn("evidence_dir", public)
            self.assertEqual(public, model.shared(direct))
            for name in model.PRIVATE_FILES:
                self.assertEqual(stat.S_IMODE((root / name).stat().st_mode), 0o600)
                self.assertEqual(self.config_git(root, "check-ignore", "--", name), name)
            self.assertIn("/owner-local-only", (root / ".flightcheck/.gitignore").read_text())
            invalid = dict(supplied, protected_branches=["bad..branch"])
            with self.assertRaises(ValueError):
                engine.configuration(root, invalid)
            changes = area / "bad.json"; changes.write_text(json.dumps({"protected_branches": ["bad..branch"]}))
            denied = self.config_cli("preview", root, "--changes", changes, "--expected-revision", before["revision"], "--reference", "owner change", expected=1)
            self.assertIn("branch", denied["error"])
            required = model.normalize(root, {**supplied, "checkout_policy": {"mode": "worktree-required"}}, engine.inspect_project(root))
            self.assertEqual(required["checkout_policy"]["mode"], "worktree-required")
            with self.assertRaises(ValueError):
                model.normalize(root, {**supplied, "checkout_policy": {"mode": "native-choice", "protect_default": False}}, engine.inspect_project(root))
            forged = dict(supplied, _flightcheck={"schema": 1, "fields": {"default_branch": {"source": "forged", "confirmed": True}}})
            clean = engine.configuration(root, forged)
            self.assertFalse(clean[model.META]["fields"]["default_branch"]["confirmed"])
            self.assertEqual((root / "owner.txt").read_text(), "Preserve owner work\n")
            self.assertEqual(model.snapshot(root), before, "Reads and invalid previews cannot mutate canonical config")

    def test_revision_transactions(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy), self.config_fixture(legacy=legacy) as (area, root, engine, installed, cli, supplied):
                model = engine.project_model(); initial = model.snapshot(root)
                pins = (root / cli.PIN).read_bytes()
                state_path = root / engine.STATE
                state_bytes = state_path.read_bytes()
                incomplete = json.loads(state_bytes)
                incomplete["files"].pop(".flightcheck/scripts/handoff.py")
                state_path.write_bytes(cli.encoded(incomplete))
                with self.assertRaisesRegex(ValueError, "required components"):
                    cli.configuration_integrity(engine, root)
                state_path.write_bytes(state_bytes)
                workflow = {p: (root / p).read_bytes() for p in json.loads((root / engine.STATE).read_bytes())["files"] if p not in (model.CONFIG, ".flightcheck/.gitignore")}
                plans = []
                for number, branch in enumerate(("release-a", "release-b")):
                    change = area / (str(number) + ".json"); change.write_text(json.dumps({"protected_branches": [branch]}))
                    plans.append(self.config_cli("preview", root, "--changes", change, "--expected-revision", initial["revision"], "--reference", "owner configuration update")["plan"])
                commands = [[sys.executable, "-B", str(PRODUCT / "setup/install.py"), "config", "apply", str(root), "--apply", p, "--json"] for p in plans]
                processes = [subprocess.Popen(c, env=self.config_env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for c in commands]
                results = [(p.communicate(timeout=25), p.returncode) for p in processes]
                self.assertEqual(sorted(r[1] for r in results), [0, 1], results)
                self.assertTrue(any("Stale configuration revision" in r[0][0] for r in results), results)
                winning = model.snapshot(root)
                self.assertNotEqual(winning["revision"], initial["revision"])
                self.assertEqual(self.config_cli("read", root)["revision"], winning["revision"])
                self.assertEqual((root / cli.PIN).read_bytes(), pins)
                for p, raw in workflow.items():
                    self.assertEqual((root / p).read_bytes(), raw, p)
                # The actual pinned historical verifier accepts unchanged workflow
                # bytes and the new config/hash; isolate its unrelated runtime probe.
                with patch.object(installed, "runtime_probe", return_value={"fixture": "not invoked"}):
                    self.assertEqual(installed.verify(root, installed.load_manifest())["status"], "ready_for_client_probe")
                with self.assertRaisesRegex(ValueError, "Unsupported configuration reconciliation"):
                    cli.configuration_plan(engine, root, {"delivery": "merge everything"}, winning["revision"], "owner")
                self.config_git(root, "add", "--force", model.CONFIG)
                with self.assertRaisesRegex(ValueError, "is tracked"):
                    cli.configuration_plan(engine, root, {"protected_branches": ["release-next"]}, winning["revision"], "owner")
                self.config_git(root, "reset", "-q", "--", model.CONFIG)
                crash_plan, _ = cli.configuration_plan(engine, root, {"protected_branches": ["release-crash"]}, winning["revision"], "owner")
                saved = area / "crash-plan.json"; saved.write_bytes(cli.encoded(cli.with_digest(crash_plan)))
                script = area / "interrupt.py"
                script.write_text("import sys,os\nfrom pathlib import Path\nsys.path.insert(0," + repr(str(PRODUCT / "src")) + ")\nfrom flightcheck_cli import cli\nengine=cli.load_installer(" + repr(str(PRODUCT / "setup/install.py")) + ")\noriginal=engine.apply_plan\ndef stop(root,ops,**kw):\n original(root,ops[:1],**kw)\n os._exit(71)\nengine.apply_plan=stop\ncli.configuration_apply(engine,Path(" + repr(str(root)) + "),cli.read_plan(" + repr(str(saved)) + "))\n")
                stopped = subprocess.run([sys.executable, "-B", str(script)], env=self.config_env, capture_output=True, text=True, timeout=25)
                self.assertEqual(stopped.returncode, 71, stopped.stdout + stopped.stderr)
                self.assertIn("Interrupted update", self.config_cli("read", root, expected=1)["error"])
                self.assertEqual(self.config_cli("recover", root)["status"], "rolled_back")
                self.assertEqual(self.config_cli("read", root)["revision"], winning["revision"])
                self.assertEqual(model.snapshot(root), winning)
                self.assertEqual((root / cli.PIN).read_bytes(), pins)

    def test_discovered_default_protection(self):
        with self.config_fixture() as (area, root, engine, installed, cli, supplied):
            before = (root / engine.CONFIG).read_bytes()
            conflict = dict(supplied, default_branch="topic", protected_branches=[])
            with self.assertRaisesRegex(ValueError, "default.*(discover|reconcil)|discover.*default"):
                engine.configuration(root, conflict)
            self.assertEqual((root / engine.CONFIG).read_bytes(), before)

    def test_revision_preimage_race(self):
        with self.config_fixture() as (area, root, engine, installed, cli, supplied):
            model = engine.project_model()
            path = root / engine.CONFIG
            original = path.read_bytes()
            expected = model.revision(original)
            owner = original + b"\n "
            snapshot = model.snapshot
            def owner_edit_after_snapshot(project):
                result = snapshot(project)
                path.write_bytes(owner)
                return result
            failure = None
            plan = None
            with patch.object(engine, "project_model", return_value=model), patch.object(model, "snapshot", side_effect=owner_edit_after_snapshot):
                try:
                    plan, _ = cli.configuration_plan(engine, root, {"protected_branches": ["release-next"]}, expected, "Owner update")
                except ValueError as error:
                    failure = error
            self.assertEqual(path.read_bytes(), owner, "Planner must preserve intervening owner bytes")
            self.assertIsNotNone(failure, "Planner returned a reviewable plan with expected revision A and owner preimage B: " + repr(plan))
            self.assertRegex(str(failure), "preimage|revision|changed")

    def test_restart_during_mode_rollback(self):
        with self.config_fixture(legacy=True) as (area, root, engine, installed, cli, supplied):
            model = engine.project_model()
            initial = model.snapshot(root)
            original = {name: ((root / name).read_bytes(), stat.S_IMODE((root / name).stat().st_mode))
                        for name in (engine.CONFIG, engine.STATE, cli.PIN, ".flightcheck/docs/status.md")}
            self.assertEqual(original[engine.CONFIG][1], 0o644, "The control must exercise a legacy original mode")
            plan, _ = cli.configuration_plan(engine, root, {"protected_branches": ["release-after-crash"]}, initial["revision"], "Owner update")
            saved = area / "mode-plan.json"
            saved.write_bytes(cli.encoded(cli.with_digest(plan)))
            common = ("import sys,os\nfrom pathlib import Path\nsys.path.insert(0," + repr(str(PRODUCT / "src")) + ")\n"
                      "from flightcheck_cli import cli\nengine=cli.load_installer(" + repr(str(PRODUCT / "setup/install.py")) + ")\n")
            forward = area / "forward-crash.py"
            forward.write_text(common + "original=engine.apply_plan\ndef stop(root,ops,**kw):\n original(root,ops[:1],**kw)\n os._exit(71)\nengine.apply_plan=stop\ncli.configuration_apply(engine,Path(" + repr(str(root)) + "),cli.read_plan(" + repr(str(saved)) + "))\n")
            stopped = subprocess.run([sys.executable, "-B", str(forward)], env=self.config_env, capture_output=True, text=True, timeout=25)
            self.assertEqual(stopped.returncode, 71, stopped.stdout + stopped.stderr)
            self.assertNotEqual((root / engine.CONFIG).read_bytes(), original[engine.CONFIG][0])
            recovery = area / "rollback-crash.py"
            recovery.write_text(common + "original=engine.write_file\ndef stop(root,name,before,after,**kw):\n original(root,name,before,after,**kw)\n if name==engine.CONFIG and after==bytes.fromhex(" + repr(original[engine.CONFIG][0].hex()) + "):\n  os._exit(72)\nengine.write_file=stop\ncli.configuration_main(['recover'," + repr(str(root)) + "],engine=engine)\n")
            stopped = subprocess.run([sys.executable, "-B", str(recovery)], env=self.config_env, capture_output=True, text=True, timeout=25)
            self.assertEqual(stopped.returncode, 72, stopped.stdout + stopped.stderr)
            self.assertEqual((root / engine.CONFIG).read_bytes(), original[engine.CONFIG][0])
            self.assertEqual(self.config_cli("recover", root)["status"], "rolled_back")
            for name, expected in original.items():
                self.assertEqual(((root / name).read_bytes(), stat.S_IMODE((root / name).stat().st_mode)), expected, name)
            self.assertEqual(model.snapshot(root), initial)

    def test_canonical_snapshots_across_update(self):
        associations, _ = self.flight_modules()
        with self.config_fixture() as (area, root, engine, installed, cli, supplied):
            model = engine.project_model()
            initial = model.snapshot(root)
            checkout = self.flight_checkout(root, area / "flight", "topic")
            record = self.flight_record(associations, root, checkout)
            record["configuration"] = initial
            registry = associations.Registry(area / "registry")
            registry.save(record)
            changes = area / "binding-update.json"
            changes.write_text(json.dumps({"checkout_policy": {"mode": "worktree-required", "git_fallback": False},
                                           "checks": [{"name": "new recorded check", "command": ["changed"], "phase": "authoritative"}]}))
            preview = self.config_cli("preview", root, "--changes", changes, "--expected-revision", initial["revision"], "--reference", "Owner default update")
            self.config_cli("apply", root, "--apply", preview["plan"])
            changed = model.snapshot(root)
            self.assertNotEqual(changed["revision"], initial["revision"])
            resumed = associations.Registry(area / "registry").get(record["flight"])
            self.assertEqual(resumed["configuration"], initial)
            self.assertEqual(resumed["grants"], {"delivery": [], "cleanup": []})
            updated = associations.reconfigure(resumed, changed, "Owner explicit flight reconfiguration")
            self.assertEqual(updated["reconfiguration"]["required_revalidation"], ["checkout", "checks", "evidence"])
            registry.save(updated, expected_revision=registry.read()["revision"])
            reopened = associations.Registry(area / "registry").get(record["flight"])
            self.assertEqual(reopened["configuration"], changed)
            self.assertEqual(reopened["configuration_history"], [initial])
            self.assertEqual(reopened["grants"], {"delivery": [], "cleanup": []})

    def test_packaged_configuration_parity(self):
        build_python = os.environ.get("FLIGHTCHECK_FOUNDATION_BUILD_PYTHON") or (sys.executable if sys.version_info >= (3, 11) else None)
        self.assertTrue(build_python, "Set FLIGHTCHECK_FOUNDATION_BUILD_PYTHON to the controller-bound existing build interpreter")
        self.assertTrue(Path(build_python).is_absolute() and Path(build_python).is_file(), "Build interpreter must be an existing absolute file")
        with self.config_fixture() as (area, root, engine, installed, cli, supplied):
            build_source = area / "build-source"
            build_source.mkdir()
            names = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=PRODUCT).decode().split("\0")
            for name in set(names) - {""}:
                source = PRODUCT / name
                if source.is_file():
                    target = build_source / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                    target.chmod(stat.S_IMODE(source.stat().st_mode))
            for args in (("init", "-q", "--template="), ("config", "core.hooksPath", os.devnull),
                         ("add", "--force", "."), ("-c", "user.name=Foundation build fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false", "commit", "-qm", "Candidate package fixture")):
                self.config_git(build_source, *args)
            build_env = dict(self.config_env, PIP_NO_INDEX="1", FLIGHTCHECK_BUILD_DEVELOPMENT="1")
            artifacts = area / "artifacts"
            built = subprocess.run([build_python, "-B", "-m", "build", "--wheel", "--no-isolation", "--outdir", str(artifacts), str(build_source)], env=build_env, capture_output=True, text=True, timeout=120)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            wheels = list(artifacts.glob("*.whl"))
            self.assertEqual(len(wheels), 1)
            shutil.rmtree(build_source)
            tool = area / "tool"
            created = subprocess.run([build_python, "-B", "-m", "venv", str(tool)], env=build_env, capture_output=True, text=True, timeout=60)
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            installed_tool = subprocess.run([str(tool / "bin/python"), "-B", "-m", "pip", "install", "--no-index", "--no-deps", str(wheels[0])], env=build_env, capture_output=True, text=True, timeout=60)
            self.assertEqual(installed_tool.returncode, 0, installed_tool.stdout + installed_tool.stderr)
            package_env = dict(build_env)
            package_env.pop("PYTHONPATH", None)
            neutral = area / "neutral"
            neutral.mkdir()
            def packaged(*args, expected=0):
                result = subprocess.run([str(tool / "bin/flightcheck"), "config", *map(str, args), "--json"], cwd=neutral, env=package_env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                return json.loads(result.stdout)
            sentinel = area / "configured-command-ran"
            changes = area / "sentinel-check.json"
            changes.write_text(json.dumps({"checks": [{"name": "must remain data", "command": [sys.executable, "-c", "from pathlib import Path;Path(" + repr(str(sentinel)) + ").write_text('executed')"], "phase": "cheap"}]}))
            initial = engine.project_model().snapshot(root)
            preview = self.config_cli("preview", root, "--changes", changes, "--expected-revision", initial["revision"], "--reference", "Owner sentinel configuration")
            self.config_cli("apply", root, "--apply", preview["plan"])
            for shared in (False, True):
                options = ("--shared",) if shared else ()
                self.assertEqual(packaged("read", root, *options), self.config_cli("read", root, *options))
            current = engine.project_model().snapshot(root)
            changes.write_text(json.dumps({"checkout_policy": {"mode": "worktree-required", "git_fallback": False}}))
            args = ("preview", root, "--changes", changes, "--expected-revision", current["revision"], "--reference", "Owner policy configuration")
            source_preview = self.config_cli(*args)
            package_preview = packaged(*args)
            for key in ("configuration", "expected_revision", "operations", "source", "distribution"):
                self.assertEqual(package_preview[key], source_preview[key], key)
            changes.write_text(json.dumps({"protected_branches": ["bad..branch"]}))
            self.assertIn("branch", self.config_cli(*args, expected=1)["error"])
            self.assertIn("branch", packaged(*args, expected=1)["error"])
            self.assertFalse(sentinel.exists(), "Neither entry point may execute a stored check command")

    def test_stable_protected_branch_input(self):
        with self.config_fixture() as (area, root, engine, installed, cli, supplied):
            self.config_git(root, "checkout", "-q", "-b", "release")
            self.config_git(root, "checkout", "-q", "trunk")
            self.assertEqual(self.config_git(root, "check-ref-format", "--branch", "@{-1}"), "release",
                             "Fixture must exercise Git's history-dependent expansion")
            before = (root / engine.CONFIG).read_bytes()
            model = engine.project_model()
            initial = model.snapshot(root)
            setup_failure = None
            try:
                engine.configuration(root, dict(supplied, protected_branches=["@{-1}"]))
            except ValueError as error:
                setup_failure = error
            changes = area / "stable-branch-changes.json"
            changes.write_text(json.dumps({"protected_branches": ["@{-1}"]}))
            invalid_plan = area / "invalid-branch-plan.json"
            args = ["preview", str(root), "--changes", str(changes), "--expected-revision", initial["revision"],
                    "--reference", "Owner branch policy", "--plan", str(invalid_plan), "--json"]
            preview = subprocess.run([sys.executable, "-B", str(PRODUCT / "setup/install.py"), "config", *args],
                                     env=self.config_env, capture_output=True, text=True, timeout=25)
            self.assertEqual((root / engine.CONFIG).read_bytes(), before, "Validation and previews cannot publish configuration")
            with self.subTest(entry="setup"):
                self.assertIsNotNone(setup_failure, "Setup accepted a checkout-history expression as a stored branch")
                self.assertRegex(str(setup_failure), "branch|ref")
            with self.subTest(entry="configuration-preview"):
                self.assertEqual(preview.returncode, 1, preview.stdout + preview.stderr)
                self.assertIn("branch", json.loads(preview.stdout)["error"])
                self.assertFalse(invalid_plan.exists(), "Invalid shorthand must not produce a reviewable plan")
            literal = engine.configuration(root, dict(supplied, protected_branches=["release"]))
            self.assertEqual(model.protected(literal), ["release", "trunk"])
            changes.write_text(json.dumps({"protected_branches": ["release"]}))
            literal_preview = self.config_cli("preview", root, "--changes", changes, "--expected-revision", initial["revision"],
                                             "--reference", "Owner literal branch policy", "--plan", area / "literal-branch-plan.json")
            self.assertEqual(model.protected(literal_preview["configuration"]), ["release", "trunk"])
            self.assertEqual((root / engine.CONFIG).read_bytes(), before)
