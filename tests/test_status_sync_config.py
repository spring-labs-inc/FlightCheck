"""Public shared-model and synchronization-schema acceptance witnesses."""

import copy
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import unittest
from unittest.mock import patch

from foundation_config_cases import ConfigurationCases
from foundation_flight_cases import FlightCases


PRODUCT = Path(os.environ.get("FLIGHTCHECK_PRODUCT_ROOT", Path(__file__).resolve().parents[1])).resolve()


class StatusSyncConfigurationTests(unittest.TestCase):
    # Reuse fixture operations, without collecting a second copy of the accepted
    # foundation suite. Their bytes are included in this gate's native spec.
    config_fixture = ConfigurationCases.config_fixture
    config_module = ConfigurationCases.config_module
    config_git = ConfigurationCases.config_git
    config_cli = ConfigurationCases.config_cli
    flight_modules = FlightCases.flight_modules
    flight_record = FlightCases.flight_record
    flight_checkout = FlightCases.flight_checkout
    flight_git = FlightCases.flight_git
    flight_snapshot = FlightCases.flight_snapshot

    def schema(self):
        path = PRODUCT / "workflow/scripts/status_sync_config.py"
        self.assertTrue(path.is_file(), "Synchronization schema must be supplied through the common model")
        spec = importlib.util.spec_from_file_location("sync_configuration_witness", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def policy(self, project="project-A", mode="advisory", provider="github-projects-v2"):
        return {"schema": 1, "mode": mode, "provider": provider, "project_id": project,
                "field_id": project + "-status", "membership": "existing-only",
                "options": {key: project + "-" + str(n) for n, key in enumerate(
                    ("todo", "ready", "in_progress", "review", "done"))}}

    def grant(self, snapshot, policy=None):
        policy = policy or snapshot["values"]["status_sync"]
        return {"schema": 1, "authority": "owner", "reference": "Owner status scope only",
                "repository": "owner/repository", "provider": policy["provider"],
                "project_id": policy["project_id"], "field_id": policy["field_id"],
                "issues": [11], "configuration_revision": snapshot["revision"]}

    def update(self, root, changes, before=None):
        before = before or self.config_cli("read", root)
        source = root.parent / "changes.json"
        source.write_text(json.dumps(changes))
        preview = self.config_cli("preview", root, "--changes", source,
                                  "--expected-revision", before["revision"], "--reference", "Owner confirmed mapping")
        return self.config_cli("apply", root, "--apply", preview["plan"])

    def test_schema_defaults_and_validation(self):
        schema = self.schema()
        default = schema.normalize()
        self.assertEqual(default, {"schema": 1, "mode": "disabled", "provider": None,
                                  "project_id": None, "field_id": None, "options": {}, "membership": "existing-only"})
        for mode in ("disabled", "advisory", "required"):
            with self.subTest(mode=mode):
                policy = self.policy(mode=mode)
                self.assertEqual(schema.normalize(policy), policy)
                normalized = schema.normalize(policy)
                normalized["options"]["done"] = "changed"
                self.assertNotEqual(policy["options"]["done"], "changed")
        invalid = [False, [], "required", {"schema": True}, {"schema": 2}, {"mode": "silent"},
                   {"mode": "required"}, {"membership": "auto-add"}, {"write_authority": True},
                   {"provider": " github-projects-v2"}, {"provider": "https://service.invalid"},
                   {**self.policy(), "field_id": ""}, {**self.policy(), "project_id": "project\nother"},
                   {**self.policy(), "options": {"done": "only-one"}},
                   {**self.policy(), "options": {k: "same" for k in schema.STATES}},
                   {**self.policy(), "options": {**self.policy()["options"], "done": False}}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                schema.normalize(value)
        # Unknown trackers are configuration, not a claim that a provider exists.
        other = self.policy(provider="another-tracker")
        self.assertEqual(schema.normalize(other)["provider"], "another-tracker")

    def test_common_model_roundtrip_and_private_provenance(self):
        self.schema()
        with self.config_fixture() as (area, root, engine, installed, cli, supplied):
            model = engine.project_model()
            self.assertEqual(model.snapshot(root)["values"]["status_sync"]["mode"], "disabled")
            changed = self.update(root, {"status_sync": self.policy()})
            snapshot = model.snapshot(root)
            self.assertEqual(changed["revision"], snapshot["revision"])
            self.assertEqual(self.config_cli("read", root)["values"], snapshot["values"])
            canonical = json.loads((root / model.CONFIG).read_bytes())
            self.assertEqual(engine.configuration(root, canonical), snapshot["values"])
            self.assertEqual(snapshot["values"]["status_sync"], self.policy())
            metadata = snapshot["values"][model.META]["fields"]["status_sync"]
            self.assertEqual(metadata["scope"], "project")
            self.assertEqual(metadata["source"], "explicit-update")
            self.assertTrue(metadata["confirmed"])
            self.assertEqual(metadata["confirmation_reference"], "Owner confirmed mapping")
            public = self.config_cli("read", root, "--shared")["values"]
            self.assertNotIn("status_sync", public)
            self.assertNotIn("project-A", json.dumps(public))
            self.assertNotIn("Owner confirmed mapping", json.dumps(public))
            self.assertEqual(stat.S_IMODE((root / model.CONFIG).stat().st_mode), 0o600)
            before = (root / model.CONFIG).read_bytes()
            invalid = area / "invalid-sync.json"
            invalid.write_text(json.dumps({"status_sync": {"mode": "required"}}))
            result = self.config_cli("preview", root, "--changes", invalid, "--expected-revision",
                                     snapshot["revision"], "--reference", "Owner invalid preview", expected=1)
            self.assertIn("status_sync", result["error"])
            self.assertEqual((root / model.CONFIG).read_bytes(), before)

    def test_revision_conflict_and_rollback(self):
        self.schema()
        with self.config_fixture() as (area, root, engine, installed, cli, supplied):
            model = engine.project_model()
            initial = model.snapshot(root)
            # Two public entry points preview the same revision. The setup caller
            # uses the same transaction API as the CLI, with no second save path.
            plan_a, _ = cli.configuration_plan(engine, root, {"status_sync": self.policy()}, initial["revision"], "Setup confirms A")
            change_b = area / "B.json"
            change_b.write_text(json.dumps({"status_sync": self.policy("project-B")}))
            preview_b = self.config_cli("preview", root, "--changes", change_b,
                                       "--expected-revision", initial["revision"], "--reference", "CLI confirms B")
            cli.configuration_apply(engine, root, plan_a)
            committed = model.snapshot(root)
            stale = self.config_cli("apply", root, "--apply", preview_b["plan"], expected=1)
            self.assertIn("Stale configuration revision", stale["error"])
            self.assertEqual(self.config_cli("read", root)["values"], committed["values"])
            self.assertEqual(engine.configuration(root, json.loads((root / model.CONFIG).read_bytes())), committed["values"])
            self.assertEqual(committed["values"]["status_sync"], self.policy())
            self.assertEqual(committed["values"][model.META]["fields"]["status_sync"]["confirmation_reference"], "Setup confirms A")
            originals = {n: ((root / n).read_bytes(), stat.S_IMODE((root / n).stat().st_mode))
                         for n in (model.CONFIG, engine.STATE, cli.PIN, ".flightcheck/docs/status.md")}
            crash_plan, _ = cli.configuration_plan(engine, root, {"status_sync": self.policy("project-C")},
                                                   committed["revision"], "Owner confirms C")
            saved = area / "crash-plan.json"
            saved.write_bytes(cli.encoded(cli.with_digest(crash_plan)))
            script = area / "interrupt-sync-update.py"
            script.write_text("import sys,os\nfrom pathlib import Path\nsys.path.insert(0," + repr(str(PRODUCT / "src")) + ")\n"
                              "from flightcheck_cli import cli\nengine=cli.load_installer(" + repr(str(PRODUCT / "setup/install.py")) + ")\n"
                              "original=engine.apply_plan\ndef stop(root,ops,**kw):\n original(root,ops[:1],**kw)\n os._exit(71)\n"
                              "engine.apply_plan=stop\ncli.configuration_apply(engine,Path(" + repr(str(root)) + "),cli.read_plan(" + repr(str(saved)) + "))\n")
            stopped = subprocess.run([sys.executable, "-B", str(script)], env=self.config_env,
                                     capture_output=True, text=True, timeout=25)
            self.assertEqual(stopped.returncode, 71, stopped.stdout + stopped.stderr)
            self.assertIn("Interrupted update", self.config_cli("read", root, expected=1)["error"])
            self.assertEqual(self.config_cli("recover", root)["status"], "rolled_back")
            self.assertEqual(model.snapshot(root), committed)
            for name, original in originals.items():
                self.assertEqual(((root / name).read_bytes(), stat.S_IMODE((root / name).stat().st_mode)), original, name)

    def test_active_flight_binding_and_revalidation(self):
        schema = self.schema()
        with self.config_fixture() as (area, root, engine, installed, cli, supplied):
            model = engine.project_model()
            self.update(root, {"status_sync": self.policy()})
            initial = model.snapshot(root)
            associations, _ = self.flight_modules()
            checkout = self.flight_checkout(root, area / "flight", "owned-topic")
            record = self.flight_record(associations, root, checkout)
            record["configuration"] = initial
            record["issues"] = [11]
            record["grants"]["tracker_status"] = self.grant(initial)
            registry = associations.Registry(area / "registry")
            registry.save(record)
            self.assertTrue(schema.authorize(record["grants"]["tracker_status"], "owner/repository", initial, 11)["authorized"])
            self.update(root, {"status_sync": self.policy("project-B")})
            changed = model.snapshot(root)
            resumed = registry.get(record["flight"])
            self.assertEqual(resumed["configuration"], initial)
            self.assertEqual(resumed["grants"], record["grants"])
            self.assertEqual(changed["values"]["status_sync"]["project_id"], "project-B")
            updated = associations.reconfigure(resumed, changed, "Owner explicitly rebinds active flight")
            self.assertEqual(updated["reconfiguration"]["required_revalidation"], ["status_sync"])
            for key in ("grants", "checkout", "issues", "repository"):
                self.assertEqual(updated[key], record[key], key)
            self.assertFalse(schema.authorize(updated["grants"]["tracker_status"], "owner/repository", changed, 11)["authorized"])
            new_revision_only = {**record["grants"]["tracker_status"], "configuration_revision": changed["revision"]}
            self.assertEqual(schema.authorize(new_revision_only, "owner/repository", changed, 11)["reason"], "scope_mismatch")
            self.assertTrue(schema.authorize(self.grant(changed), "owner/repository", changed, 11)["authorized"])
            registry.save(updated, expected_revision=registry.read()["revision"])
            self.assertEqual(registry.get(record["flight"])["grants"], record["grants"])

    def test_status_grant_does_not_broaden_other_authority(self):
        schema = self.schema()
        with self.config_fixture() as (area, root, engine, installed, cli, supplied):
            self.update(root, {"status_sync": self.policy()})
            snapshot = engine.project_model().snapshot(root)
            grant = self.grant(snapshot)
            self.assertEqual(schema.normalize_grant(grant), grant)
            self.assertTrue(schema.authorize(grant, "owner/repository", snapshot, 11)["authorized"])
            for changed in (None, {}, {**grant, "issues": [True]}, {**grant, "issues": [11, 11]},
                            {**grant, "authority": "implied"}, {**grant, "membership": True},
                            {**grant, "close_issues": True}, {**grant, "merge": True}):
                with self.subTest(grant=changed):
                    self.assertFalse(schema.authorize(changed, "owner/repository", snapshot, 11)["authorized"])
            for changed in ({**grant, "repository": "other/repository"}, {**grant, "project_id": "other"},
                            {**grant, "field_id": "other"}, {**grant, "issues": [12]},
                            {**grant, "provider": "another-tracker"}, {**grant, "configuration_revision": "0" * 64}):
                with self.subTest(scope=changed):
                    self.assertFalse(schema.authorize(changed, "owner/repository", snapshot, 11)["authorized"])
            for metadata in (None, [], {"fields": None}, {"fields": {"status_sync": []}}):
                changed = copy.deepcopy(snapshot)
                changed["values"]["_flightcheck"] = metadata
                self.assertFalse(schema.authorize(grant, "owner/repository", changed, 11)["authorized"])
            forged = copy.deepcopy(snapshot)
            forged["values"]["status_sync"]["options"]["done"] = "unconfirmed-change"
            self.assertFalse(schema.authorize(grant, "owner/repository", forged, 11)["authorized"])
            self.assertFalse(schema.authorize(None, "owner/repository", snapshot, 11)["authorized"], "Configuration alone is not a grant")

    def test_installed_adapter_integrity_and_unsupported_provider(self):
        schema = self.schema()
        with self.config_fixture() as (area, root, engine, installed, cli, supplied):
            rows = engine.load_manifest()["files"]
            self.assertIn(["workflow/scripts/status_sync_config.py", ".flightcheck/scripts/status_sync_config.py", "shared"], rows)
            for source, destination, kind in rows:
                self.assertTrue((PRODUCT / source).is_file(), source)
            installed_engine = self.config_module(root / ".flightcheck/install.py", "installed_sync_engine")
            local_model = installed_engine.project_model()
            self.assertEqual(local_model.normalize(root, json.loads((root / engine.CONFIG).read_bytes()), trusted_metadata=True),
                             engine.project_model().snapshot(root)["values"])
            self.assertEqual(schema.normalize(self.policy(provider="another-tracker"))["provider"], "another-tracker")
            for entry in (PRODUCT / "setup/install.py", root / ".flightcheck/install.py"):
                result = subprocess.run([sys.executable, "-B", str(entry), "status-sync", "--help"],
                                        capture_output=True, text=True, timeout=25, env=self.config_env)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("--event", result.stdout)
                self.assertIn("--registry", result.stdout)
            self.assertIn("](status-synchronization.md)", (root / ".flightcheck/docs/development-workflow.md").read_text())
            self.assertIn("](../../../.flightcheck/docs/status-synchronization.md)",
                          (root / ".agents/skills/develop-change/SKILL.md").read_text())
            @contextlib.contextmanager
            def selected_source():
                yield engine, PRODUCT, {}, "fixture pinned source"
            with patch.object(cli, "installer", selected_source):
                self.assertEqual(cli.main(["status-sync", "--help"]), 0)
            unknown = {"values": {"status_sync": self.policy(provider="another-tracker")}}
            probe = ("import json,sys\nsys.path.insert(0," + repr(str(PRODUCT / "workflow/scripts")) + ")\n"
                     "from status_sync import resolve\nfrom status_sync_github import ProviderError\n"
                     "assert resolve('owner/repository',{'values':{}}) is None\n"
                     "try:\n resolve('owner/repository',json.loads(sys.argv[1]))\n"
                     "except ProviderError as error:\n assert error.reason=='unsupported_provider'\n print(error.reason)\n"
                     "else:\n raise AssertionError('Unsupported provider claimed resolved')\n")
            result = subprocess.run([sys.executable, "-B", "-c", probe, json.dumps(unknown)],
                                    capture_output=True, text=True, timeout=25, env=self.config_env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("unsupported_provider", result.stdout)
            # The installed model must reject modified adapter bytes before
            # executing them, including through the setup entry point.
            adapter = root / ".flightcheck/scripts/status_sync_config.py"
            adapter.write_bytes(adapter.read_bytes() + b"\nraise RuntimeError('untrusted adapter executed')\n")
            with self.assertRaisesRegex(ValueError, "Modified installed synchronization schema"):
                local_model.normalize(root, json.loads((root / engine.CONFIG).read_bytes()), trusted_metadata=True)
            denied = self.config_cli("read", root, expected=1)
            self.assertIn("Modified installed component", denied["error"])


if __name__ == "__main__":
    unittest.main()
