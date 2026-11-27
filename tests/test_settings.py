"""Public Settings/configuration boundaries using isolated existing-project fixtures."""
import contextlib
import copy
import http.client
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from html.parser import HTMLParser
from unittest.mock import patch

from foundation_config_cases import ConfigurationCases
from foundation_flight_cases import FlightCases

PRODUCT = Path(os.environ.get("FLIGHTCHECK_PRODUCT_ROOT", Path(__file__).resolve().parents[1])).resolve()


class SettingsTests(unittest.TestCase):
    config_fixture = ConfigurationCases.config_fixture
    config_module = ConfigurationCases.config_module
    config_git = ConfigurationCases.config_git
    config_cli = ConfigurationCases.config_cli
    flight_modules = FlightCases.flight_modules
    flight_record = FlightCases.flight_record
    flight_git = FlightCases.flight_git
    flight_snapshot = FlightCases.flight_snapshot

    def service(self, engine, root, registry=None):
        from flightcheck_cli.settings import Settings
        return Settings(engine, root, "settings-flight", "settings-session", registry, reference="Owner local Settings session", project_scope=True)

    def save(self, service, changes):
        before = service.read()
        plan = service.preview({"changes": changes, "expected_revision": before["revision"], "reference": "Owner future defaults decision"})
        return service.apply({"plan_id": plan["plan_id"]})

    def registry(self, area, root, engine):
        associations, _ = self.flight_modules()
        registry = associations.Registry(area / "registry")
        record = self.flight_record(associations, root, root, flight="settings-flight", repository="fixture-owner/fixture-repo")
        record["configuration"] = engine.project_model(root).snapshot(root)
        record["grants"] = {"delivery": {"scope": "preserve exact original"}, "cleanup": [], "tracker_status": {"scope": "none"}}
        record["status_sync"] = {"pending": {"owner_reference": "Retained reconciliation", "attempts": 2}, "history": ["preserve"]}
        registry.save(record)
        return registry, record

    def test_common_model_and_entrypoints(self):
        with self.config_fixture() as (area, root, engine, installed, cli, supplied):
            service = self.service(engine, root)
            initial = service.read()
            self.assertEqual(initial["values"], self.config_cli("read", root)["values"])
            self.assertEqual(engine.inspect_project(root)["configuration"]["revision"], initial["revision"])
            self.save(service, {"review_client": "Separate read-only reviewer", "resources": {"runbook": "docs/runbook.md"}})
            direct = engine.project_model(root).snapshot(root)
            self.assertEqual(service.read()["values"], direct["values"])
            self.assertEqual(self.config_cli("read", root)["values"], direct["values"])
            self.assertEqual(engine.inspect_project(root)["configuration"]["values"], direct["values"])
            args = [sys.executable, "-B", str(root / ".flightcheck/install.py"), "config", "read", str(root), "--json"]
            read = subprocess.run(args, env=self.config_env, capture_output=True, text=True, timeout=30)
            self.assertEqual(read.returncode, 0, read.stdout + read.stderr)
            self.assertEqual(json.loads(read.stdout)["values"], direct["values"])
            bare = area / "unconfigured"; bare.mkdir()
            self.config_git(bare, "init", "-q", "-b", "trunk")
            self.assertEqual(self.service(engine, bare).read()["status"], "unconfigured")
            self.assertEqual(engine.inspect_project(bare)["configuration"]["status"], "unconfigured")
            self.assertFalse((bare / ".flightcheck").exists())
            # Two exact existing-install dependencies: reviewed111 and its prior
            # acceptedmain without the synchronization schema. Not an environment campaign.
            for prior_tag, prior_commit, archive_variable in [
                ("a4d", "a4d67a32e697015d6047cd561c0d917716925e6a", "FLIGHTCHECK_SETTINGS_PRIOR_ARCHIVE"),
                ("494", "494186816ca7021dab6bcac5e3e47e82cf1361cd", "FLIGHTCHECK_SETTINGS_PRIOR_ARCHIVE_494")]:
                previous = area / ("prior-source-" + prior_tag); previous.mkdir()
                raw = Path(os.environ[archive_variable]).read_bytes() if archive_variable in os.environ else subprocess.check_output(["git", "archive", prior_commit], cwd=PRODUCT)
                import tarfile
                with tarfile.open(fileobj=io.BytesIO(raw)) as stream:
                    for member in stream.getmembers():
                        self.assertFalse(Path(member.name).is_absolute() or ".." in Path(member.name).parts)
                        path = previous / member.name
                        if member.isdir(): path.mkdir(parents=True, exist_ok=True)
                        else:
                            self.assertTrue(member.isfile()); path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_bytes(stream.extractfile(member).read()); path.chmod(member.mode & 0o777)
                for command in [("init", "-q", "-b", "trunk"), ("config", "core.hooksPath", os.devnull), ("add", "."),
                                ("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "Actual prior source fixture")]:
                    self.config_git(previous, *command)
                old = self.config_module(previous / "setup/install.py", "prior_adapter_fixture")
                adopter = area / ("prior-project-" + prior_tag); adopter.mkdir(); self.config_git(adopter, "init", "-q", "-b", "trunk")
                (adopter / "owner.txt").write_text("Owner bytes\n"); self.config_git(adopter, "add", "."); self.config_git(adopter, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "Owner fixture")
                result, config, ops = old.plan_installation(previous, adopter, old.load_manifest(), "codex", {**supplied, "default_branch": "trunk"})
                old.apply_plan(adopter, ops)
                (adopter / cli.PIN).write_bytes(cli.encoded({"schema": 1, "source_revision": result["source"]["revision"], "runtime": cli.runtime_identity(config)}))
                before_state = json.loads((adopter / old.STATE).read_bytes()); pin = (adopter / cli.PIN).read_bytes(); canonical = (adopter / old.CONFIG).read_bytes()
                prior_service = self.service(engine, adopter)
                self.assertEqual(prior_service.read()["status"], "incompatible")
                with self.assertRaisesRegex(ValueError, "adapter"):
                    prior_service.preview({"changes": {"review_client": "new"}, "expected_revision": cli.sha(canonical), "reference": "Owner"})
                # Use the clean current fixture source, not an uncommitted control tree.
                adapter_engine = self.config_module(area / "source/setup/install.py", "new_adapter_fixture")
                plan, _ = cli.configuration_adapter_plan(adapter_engine, adopter, cli.sha(canonical), "Explicit owner adapter update")
                touched = adopter / ".flightcheck/scripts/project_config.py"; mode = stat.S_IMODE(touched.stat().st_mode)
                touched.chmod(mode ^ 0o100)
                with self.assertRaisesRegex(ValueError, "stale"): cli.configuration_adapter_apply(adapter_engine, adopter, plan)
                self.assertEqual(stat.S_IMODE(touched.stat().st_mode), mode ^ 0o100)
                touched.chmod(mode)
                original_apply = adapter_engine.apply_plan
                def interrupted(target, operations, **kwargs):
                    original_apply(target, operations[:1], **kwargs)
                    raise OSError("Controlled adapter interruption")
                prior_bytes = {p: (adopter / p).read_bytes() for p in before_state["files"]}
                with patch.object(adapter_engine, "apply_plan", side_effect=interrupted), self.assertRaisesRegex(ValueError, "original project restored"):
                    cli.configuration_adapter_apply(adapter_engine, adopter, plan)
                for p, value in prior_bytes.items(): self.assertEqual((adopter / p).read_bytes(), value, p)
                self.assertEqual((adopter / cli.PIN).read_bytes(), pin)
                self.assertEqual(prior_service.read()["status"], "incompatible")
                protected = {p: (adopter / p).read_bytes() for p in before_state["files"] if p not in {op["path"] for op in plan["operations"]}}
                applied = cli.configuration_adapter_apply(adapter_engine, adopter, plan)
                self.assertEqual(applied["status"], "configuration_adapter_updated")
                self.assertEqual((adopter / cli.PIN).read_bytes(), pin)
                self.assertEqual((adopter / old.CONFIG).read_bytes(), canonical)
                after = json.loads((adopter / old.STATE).read_bytes())
                self.assertEqual(after["source"], before_state["source"])
                for p, value in protected.items(): self.assertEqual((adopter / p).read_bytes(), value, p)
                self.assertEqual(prior_service.read()["status"], "configuration")
                self.save(prior_service, {"cleanup_policy": {"local_branches": True}, "resources": {"logs": {"unavailable": "No approved route"}}})
                self.assertEqual(cli.configuration_model(engine, adopter).snapshot(adopter)["values"], prior_service.read()["values"])

                neutral = area / ("neutral-" + prior_tag); neutral.mkdir()
                independent_env = dict(self.config_env, PYTHONPATH="")
                for arguments in [("config", "read", str(adopter), "--json"), ("settings", "--help")]:
                    copied = subprocess.run([sys.executable, "-B", str(adopter / ".flightcheck/install.py"), *arguments], cwd=neutral, env=independent_env, capture_output=True, text=True, timeout=30)
                    self.assertEqual(copied.returncode, 0, copied.stdout + copied.stderr)
                self.assertTrue((adopter / ".flightcheck/scripts/status_sync_config.py").is_file())

    def test_full_field_matrix_and_provenance(self):
        with self.config_fixture() as (area, root, engine, installed, cli, supplied):
            service = self.service(engine, root)
            suggested = engine.project_model(root).normalize(root, supplied, {"default_branch": "trunk", "resources": {"style_guide": "docs/suggested.md"}}, origin="setup")
            suggestion = suggested["_flightcheck"]["fields"]["resources.style_guide"]
            self.assertEqual(suggestion["source"], "discovered"); self.assertFalse(suggestion["confirmed"])
            self.assertEqual(service.read()["repository"]["checkout"], str(root))
            self.save(service, {"resources": {"style_guide": "docs/style.md", "logs": {"unavailable": "No approved lookup route"}}, "activation": "default-for-coding", "activation_reference": "Owner activation", "required_runtimes": ["Node from existing project"], "preview": "Existing preview command; record only", "review_client": "Codex", "reviewer_access": "Independent read-only boundary, actual probes required", "delivery": "Reviewed PR only; no grant", "nit_tracker": "Private owner notes", "policy_reference": "Existing project rules", "evidence_dir": str(area / "new-evidence")})
            read = service.read(); values = read["values"]
            for key in ("resources", "activation", "required_runtimes", "preview", "review_client", "reviewer_access", "delivery", "nit_tracker", "policy_reference", "evidence_dir"):
                metadata = values["_flightcheck"]["fields"][key]; self.assertTrue(metadata["confirmed"], key); self.assertEqual(metadata["source"], "explicit-update"); self.assertEqual(metadata["last_validation"]["status"], "valid")
            before_style = copy.deepcopy(values["_flightcheck"]["fields"]["resources.style_guide"])
            self.save(service, {"resources": {"runbook": "docs/runbook.md", "private_logs": str(area / "private-logs")}})
            self.assertEqual(service.read()["values"]["_flightcheck"]["fields"]["resources.style_guide"], before_style)
            self.assertEqual(service.read()["values"]["_flightcheck"]["fields"]["resources.private_logs"]["scope"], "host")
            self.assertIn(b"unless the owner explicitly opts out", (root / "AGENTS.md").read_bytes())
            self.assertIn(str(area / "new-evidence").encode(), (root / ".flightcheck/docs/status.md").read_bytes())
            self.assertEqual(cli.configuration_integrity(engine, root)[0]["files"]["AGENTS.md"]["sha256"], cli.sha(engine.block_from((root / "AGENTS.md").read_bytes())))
            for changes in [{"activation": "default-for-coding", "activation_reference": ""}, {"checks": [{"name": "x", "command": "shell string", "phase": "cheap"}]}, {"resources": {"logs": {"unavailable": ""}}}, {"evidence_dir": str(root / "private")}, {"provider_write_authority": True}]:
                with self.subTest(changes=changes), self.assertRaises(ValueError): self.save(service, changes)

    def test_no_execution_and_runtime_boundary(self):
        with self.config_fixture() as (area, root, engine, installed, cli, supplied):
            service = self.service(engine, root); model = engine.project_model(root)
            missing = area / "missing-runtime"; values = json.loads((root / engine.CONFIG).read_bytes()); values["python"] = str(missing)
            raw = cli.encoded(values); (root / engine.CONFIG).write_bytes(raw)
            state = json.loads((root / engine.STATE).read_bytes()); state["files"][engine.CONFIG]["sha256"] = cli.sha(raw); (root / engine.STATE).write_bytes(cli.encoded(state))
            # Model a coherent captured runtime path becoming unavailable, not
            # an unrelated corruption of generated instructions.
            status = root / ".flightcheck/docs/status.md"
            status.write_bytes(status.read_bytes().replace(supplied["python"].encode(), str(missing).encode()))
            state["files"][".flightcheck/docs/status.md"]["sha256"] = cli.sha(status.read_bytes()); (root / engine.STATE).write_bytes(cli.encoded(state))
            pin = json.loads((root / cli.PIN).read_bytes()); pin["runtime"]["requested"] = str(missing); (root / cli.PIN).write_bytes(cli.encoded(pin)); saved_pin = (root / cli.PIN).read_bytes()
            original = subprocess.Popen; commands = []
            def guarded(args, *a, **kw):
                commands.append(args)
                self.assertEqual(Path(args[0]).name, "git", "Structural Settings executed a configured runtime/command")
                return original(args, *a, **kw)
            with patch("subprocess.Popen", side_effect=guarded):
                self.assertEqual(service.read()["runtime"]["status"], "unavailable")
                self.save(service, {"checks": [{"name": "must never execute", "command": [str(missing), "-c", "raise SystemExit(81)"], "phase": "cheap"}], "required_runtimes": ["Suggested Python; not selected"]})
            self.assertEqual((root / cli.PIN).read_bytes(), saved_pin)
            self.assertTrue(commands)
            with self.assertRaises(ValueError): self.save(service, {"python": sys.executable})
            plan, _ = cli.configuration_runtime_plan(engine, root, supplied["python"], model.snapshot(root)["revision"], "Explicit trusted runtime probes")
            with self.assertRaisesRegex(ValueError, "execute-approved-runtime"): cli.configuration_apply(engine, root, plan)
            cli.configuration_apply(engine, root, plan, allow_runtime_execution=True)
            self.assertEqual(cli.configuration_model(engine, root).snapshot(root)["values"]["python"], supplied["python"])

    def test_revision_transaction_and_recovery(self):
        with self.config_fixture() as (area, root, engine, installed, cli, supplied):
            service = self.service(engine, root); initial = service.read()
            preview = service.preview({"changes": {"activation": "default-for-coding", "activation_reference": "Owner"}, "expected_revision": initial["revision"], "reference": "Owner"})
            agent = root / "AGENTS.md"; agent.write_bytes(b"Concurrent owner note\n" + agent.read_bytes()); owner = agent.read_bytes()
            with self.assertRaisesRegex(ValueError, "stale"): service.apply({"plan_id": preview["plan_id"]})
            self.assertEqual(agent.read_bytes(), owner); self.assertEqual(service.read()["revision"], initial["revision"])
            plan, operations = cli.configuration_plan(engine, root, {"review_client": "New reviewer"}, initial["revision"], "Owner")
            with cli.tx.locked(root) as state:
                journal = cli.tx.snapshot(engine, root, state, operations)
                engine.apply_plan(root, operations[:1], rollback_on_error=False)
            self.assertEqual(service.read()["status"], "recovery_required", "Observe the interrupted state before recovery")
            self.assertEqual(service.recover()["status"], "rolled_back")
            self.assertEqual(service.read()["revision"], initial["revision"])
            for name in engine.project_model(root).PRIVATE_FILES: self.assertEqual(stat.S_IMODE((root / name).stat().st_mode), 0o600)
            self.save(service, {"review_client": "Recovered update"})
            self.assertEqual(self.service(engine, root).read()["values"]["review_client"], "Recovered update")

    def test_local_capability_and_private_projection(self):
        with self.config_fixture() as (area, root, engine, installed, cli, supplied):
            from flightcheck_cli.settings import Handler
            from http.server import ThreadingHTTPServer
            service = self.service(engine, root); before = service.read()["revision"]
            with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
                server.settings, server.route, server.assets = service, "/task/settings-flight/settings/", PRODUCT / "status-card"
                thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
                try:
                    def request(headers, method="GET", action="read", data=None):
                        connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
                        connection.request(method, server.route + "api/" + action, body=None if data is None else json.dumps(data), headers=headers)
                        response = connection.getresponse(); result = response.status, response.read(); connection.close(); return result
                    headers = {"Authorization": "Bearer " + service.token, **{"X-FlightCheck-" + k.title(): v for k, v in service.context.items()}}
                    for key in [None, "Authorization", "X-FlightCheck-Project", "X-FlightCheck-Task", "X-FlightCheck-Session"]:
                        bad = dict(headers) if key else {}
                        if key: bad[key] = "different"
                        code, raw = request(bad); self.assertEqual(code, 403); self.assertNotIn(str(area).encode(), raw)
                        code, _ = request(bad, "POST", "preview", {"changes": {"delivery": "all"}, "expected_revision": before, "reference": "Owner"}); self.assertEqual(code, 403)
                    forwarded = dict(headers, Host="localhost:59493", Origin="http://localhost:54321")
                    code, raw = request(forwarded); self.assertEqual(code, 200); self.assertEqual(json.loads(raw)["revision"], before)
                    self.assertNotIn(service.token.encode(), raw)
                    self.assertEqual(request(dict(headers, Origin="https://hostile.example"))[0], 403)
                finally: server.shutdown(); thread.join()
            public = self.config_cli("read", root, "--shared"); serialized = json.dumps(public)
            for private in (str(area), supplied["python"], supplied["policy_reference"], service.token): self.assertNotIn(private, serialized)
            self.assertEqual(service.read()["revision"], before)
            serve = (PRODUCT / "status-card/serve.py").read_text(); self.assertIn('b"Read-only endpoint.', serve)
            from flightcheck_cli import settings as settings_module
            private = area / "card"; private.mkdir(mode=0o700)
            status = private / "status.json"; status.write_text(json.dumps({"task": "settings-flight"})); status.chmod(0o600)
            (private / "reply-route.json").write_text(json.dumps({"task": "settings-flight", "checkout": str(root), "execution": "remote", "user_url": "http://localhost:1/task/settings-flight/"}))
            observed = {"task": "settings-flight", "status": "unavailable", "publication": "verified", "candidate": "current", "host_url": "http://127.0.0.1:2/task/settings-flight/", "user_url": None, "guidance": "Refresh the supported connection"}
            output = io.StringIO()
            with patch.object(settings_module, "prepare_route", return_value=observed) as route, patch.object(settings_module, "ensure_settings_listener") as listener, contextlib.redirect_stdout(output):
                code = settings_module.main([str(root), "--task", "settings-flight", "--session", "settings-session", "--card-status", str(status), "--authorize-local-settings", "Owner"], engine)
            self.assertEqual(code, 1); route.assert_called_once(); listener.assert_called_once()
            unavailable = json.loads(output.getvalue()); self.assertEqual(unavailable["status"], "browser_route_unavailable")
            self.assertNotIn(":1/", unavailable["host_preview_url"]); self.assertNotIn("user_url", unavailable)
            self.assertIn("/settings/#cap=", unavailable["host_preview_url"])
            binding = json.loads((private / "settings-session.json").read_bytes()); self.assertEqual(binding["task"], "settings-flight")
            self.assertEqual(stat.S_IMODE((private / "settings-session.json").stat().st_mode), 0o600)

    def test_active_binding_and_revalidation(self):
        with self.config_fixture() as (area, root, engine, installed, cli, supplied):
            registry, record = self.registry(area, root, engine); service = self.service(engine, root, registry.directory)
            self.save(service, {"checkout_policy": {"mode": "worktree-required"}, "checks": [{"name": "new", "command": ["record-only"], "phase": "cheap"}]})
            during = registry.get(record["flight"]); self.assertEqual(during, record)
            plan = service.reconfigure_preview({"flight": record["flight"], "reference": "Owner explicit active adoption"})
            self.assertEqual(registry.get(record["flight"]), record, "A preview cannot rebind active work")
            service.reconfigure_apply({"plan_id": plan["plan_id"]})
            current = registry.get(record["flight"]); self.assertEqual(current["grants"], record["grants"]); self.assertEqual(current["status_sync"], record["status_sync"])
            self.assertEqual(current["configuration_history"], [record["configuration"]]); self.assertEqual(current["configuration"]["revision"], service.read()["revision"])
            self.assertEqual(current["reconfiguration"]["required_revalidation"], ["checkout", "checks", "evidence"])
            with self.assertRaises(ValueError): service.reconfigure_preview({"flight": "another-flight", "reference": "Owner"})

    def test_checkout_modes_and_capabilities(self):
        with self.config_fixture() as (area, root, engine, installed, cli, supplied):
            service = self.service(engine, root)
            for mode in ("native-choice", "worktree-required"):
                self.save(service, {"checkout_policy": {"mode": mode}})
                read = service.read(); self.assertEqual(read["values"]["checkout_policy"]["mode"], mode)
                self.assertIn("trunk", read["values"]["protected_branches"])
                self.assertIn("Unavailable", read["capabilities"]["native_checkout"])
                for change in [{"checkout_policy": {"protect_default": False}}, {"checkout_policy": {"git_fallback": True}}, {"protected_branches": ["bad..ref"]}]:
                    with self.assertRaises(ValueError): self.save(service, change)
            self.assertEqual(self.config_git(root, "branch", "--show-current"), "trunk")
            # The delivered verifier remains the authoritative enforcement API.
            sys.path.insert(0, str(PRODUCT / "workflow/scripts")); import checkout_guard
            self.assertIsNotNone(checkout_guard.verify)

    def test_cleanup_policy_and_frozen_grants(self):
        with self.config_fixture() as (area, root, engine, installed, cli, supplied):
            registry, record = self.registry(area, root, engine); service = self.service(engine, root, registry.directory)
            self.save(service, {"cleanup_policy": {"remote_branches": True, "temporary_worktrees": True, "retained_artifacts": [{"identity": "Unknown native reservation", "reason": "Preserve"}]}})
            before = service.read()["values"]["cleanup_policy"]
            self.save(service, {"cleanup_policy": {"local_branches": True}})
            after = service.read()["values"]["cleanup_policy"]
            for field in ("remote_branches", "temporary_worktrees", "retained_artifacts"): self.assertEqual(after[field], before[field])
            self.assertEqual(registry.get(record["flight"]), record)
            for bad in [{"cleanup_policy": {"disable_preservation": True}}, {"cleanup_policy": {"local_branches": "all"}}, {"cleanup_grant": ["old-artifact"]}]:
                with self.assertRaises(ValueError): self.save(service, bad)

    def test_audit_is_read_only(self):
        with self.config_fixture() as (area, root, engine, installed, cli, supplied):
            registry, record = self.registry(area, root, engine); service = self.service(engine, root, registry.directory)
            self.config_git(root, "remote", "add", "origin", "https://github.com/fixture-owner/fixture-repo.git")
            record["lifecycle"] = {"state": "closed", "disposition": "Retained fixture artifacts"}
            inventory = [{"id": "worker", "kind": "worktree", "identity": str(root)},
                         {"id": "remote", "kind": "remote_branch", "identity": "refs/heads/retained", "remote": "origin"}]
            record["cleanup"] = {"protocol": "required-v1", "state": "closed_retained", "inventory": inventory, "operations": [],
                                 "closure": {"artifacts": [{**r, "disposition": "retained_accepted", "operation_state": "blocked",
                                   "reason": "Preserve fixture ownership", "next_action": "Reconcile through a separately authorized current observation",
                                   "policy_reference": "Synthetic owner retention decision"} for r in inventory]}}
            registry.save(record, expected_revision=registry.read()["revision"])
            associations, audit = service.helpers()
            before = {"refs": self.config_git(root, "show-ref"), "status": self.config_git(root, "status", "--porcelain"), "registry": registry.read(), "config": (root / engine.CONFIG).read_bytes()}
            original = audit.audit; calls = []
            def bounded(checkout, registry, repository, **kwargs):
                calls.append(repository); return original(checkout, registry, repository, remote=False)
            with patch.object(audit, "audit", side_effect=bounded): report = service.audit()
            self.assertTrue(calls); self.assertIn("coverage", report); self.assertTrue(report["read_only"]); self.assertFalse(report["cleanup_authorized"])
            main = next(r for r in report["artifacts"] if r["kind"] == "worktree" and r["identity"].get("path") == str(root))
            self.assertTrue(main["retained_obligations"]); self.assertEqual(main["recommendation"]["classification"], "preserve")
            unseen = next(r for r in report["artifacts"] if r["kind"] == "retained_artifact" and r["identity"].get("remote") == "origin")
            self.assertFalse(unseen["state"]["available"]); self.assertTrue(unseen["recommendation"]["action"])
            self.assertEqual(registry.read(), before["registry"]); self.assertEqual((root / engine.CONFIG).read_bytes(), before["config"])
            self.assertEqual(self.config_git(root, "show-ref"), before["refs"]); self.assertEqual(self.config_git(root, "status", "--porcelain"), before["status"])
            self.assertNotIn('"cleanup_authorized": true', json.dumps(report))

    def test_keyboard_ui_and_external_destinations(self):
        class Surface(HTMLParser):
            def __init__(self): super().__init__(); self.tags = []
            def handle_starttag(self, tag, attrs): self.tags.append((tag, dict(attrs)))
        surface = Surface(); surface.feed((PRODUCT / "status-card/settings.html").read_text())
        byid = {attrs["id"]: (tag, attrs) for tag, attrs in surface.tags if "id" in attrs}
        for name in ("save", "reload", "recover", "audit"):
            self.assertEqual(byid[name][0], "button"); self.assertNotEqual(byid[name][1].get("tabindex"), "-1")
        self.assertNotIn("reference", byid); self.assertNotIn("review", byid); self.assertNotIn("preview", byid)
        self.assertIn("hidden", byid["recovery"][1])
        self.assertNotIn("open", byid["advanced"][1])
        task_link = next(attrs for tag, attrs in surface.tags if tag == "a" and attrs.get("href") == "../")
        self.assertNotIn("target", task_link); self.assertEqual(task_link["id"], "task-status-link")
        js = (PRODUCT / "status-card/settings.js").read_text(); css = (PRODUCT / "status-card/card.css").read_text()
        node = shutil.which("node")
        self.assertIsNotNone(node, "Existing Node runtime is required for the focused script syntax check")
        parsed = subprocess.run([node, "--check", str(PRODUCT / "status-card/settings.js")], capture_output=True, text=True, timeout=15)
        self.assertEqual(parsed.returncode, 0, parsed.stdout + parsed.stderr)
        for required in ("caption.htmlFor", 'control.setAttribute("aria-describedby"', 'arrow.target = "_blank"', 'arrow.rel = "noopener noreferrer"', 'node("details")', 'history.replaceState', 'byId("message").focus()', 'api("preview"', 'api("apply"', 'api("recover"'):
            self.assertIn(required, js)
        self.assertNotIn('"readonly-json"', js); self.assertNotIn('"json"', js)
        self.assertIn(":focus-visible", css); self.assertNotIn("innerHTML", js)
        self.assertIn('href="settings/"', (PRODUCT / "status-card/task.html").read_text())


if __name__ == "__main__": unittest.main()
