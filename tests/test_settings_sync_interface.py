"""Affected common seams: captured status authority and pinned helper selection."""
import copy
import hashlib
import os
from pathlib import Path
import sys
import tarfile
import unittest
from unittest.mock import patch

import test_settings as fixtures


class SettingsSyncInterfaceTests(unittest.TestCase):
    config_fixture = fixtures.SettingsTests.config_fixture
    config_module = fixtures.SettingsTests.config_module
    config_git = fixtures.SettingsTests.config_git
    config_cli = fixtures.SettingsTests.config_cli
    flight_modules = fixtures.SettingsTests.flight_modules
    flight_record = fixtures.SettingsTests.flight_record
    flight_git = fixtures.SettingsTests.flight_git
    flight_snapshot = fixtures.SettingsTests.flight_snapshot
    registry = fixtures.SettingsTests.registry
    service = fixtures.SettingsTests.service
    save = fixtures.SettingsTests.save

    def policy(self):
        return {"schema": 1, "mode": "advisory", "provider": "github-projects-v2", "project_id": "fixture-project", "field_id": "fixture-status", "membership": "existing-only",
                "options": {key: "fixture-" + key for key in ("todo", "ready", "in_progress", "review", "done")}}

    def test_enabled_sync_revision_requires_authority_revalidation(self):
        with self.config_fixture() as (area, root, engine, installed, cli, supplied):
            registry, original = self.registry(area, root, engine)
            service = self.service(engine, root, registry.directory)
            self.save(service, {"status_sync": self.policy()})
            associations, _ = service.helpers()
            current = cli.configuration_model(engine, root).snapshot(root)
            registry.save(associations.reconfigure(registry.get(original["flight"]), current, "Synthetic model-only setup"), expected_revision=registry.read()["revision"])
            active = registry.get(original["flight"])
            grant = {"schema": 1, "authority": "owner", "reference": "Fixture exact status authority", "repository": original["repository"]["id"],
                     "provider": self.policy()["provider"], "project_id": self.policy()["project_id"], "field_id": self.policy()["field_id"],
                     "issues": original["issues"], "configuration_revision": active["configuration"]["revision"]}
            active["grants"]["tracker_status"] = grant; active["grant_reference"] = "Explicit fixture status scope"
            registry.save(active, expected_revision=registry.read()["revision"])
            schema = cli.configuration_model(engine, root).sync_schema()
            self.assertTrue(schema.authorize(grant, original["repository"]["id"], active["configuration"], original["issues"][0])["authorized"])
            for change in ({"review_client": "Changed reviewer preference"}, {"preview": "Changed recorded preview instructions"}):
                with self.subTest(change=change):
                    self.save(service, change)
                    before = registry.get(original["flight"])
                    current = cli.configuration_model(engine, root).snapshot(root)
                    revised = associations.reconfigure(before, current, "Synthetic common-model revalidation witness")
                    self.assertIn("status_sync", revised["reconfiguration"]["required_revalidation"], "Exact status grant binds the entire revision, including unrelated changes")
                    registry.save(revised, expected_revision=registry.read()["revision"])
                    after = registry.get(original["flight"])
                    self.assertEqual(after["grants"], before["grants"])
                    self.assertEqual(after["status_sync"], original["status_sync"])
                    denied = schema.authorize(grant, original["repository"]["id"], after["configuration"], original["issues"][0])
                    self.assertFalse(denied["authorized"])
                    self.assertEqual(denied["reason"], "configuration_changed")

    def test_pinned_common_helper_ignores_ambient_project_import(self):
        with self.config_fixture() as (area, root, engine, installed, cli, supplied):
            registry, original = self.registry(area, root, engine)
            service = self.service(engine, root, registry.directory)
            archive = Path(os.environ["FLIGHTCHECK_SETTINGS_PRIOR_ARCHIVE"])
            with tarfile.open(archive) as stream:
                raw = stream.extractfile("workflow/scripts/flight_associations.py").read()
            old_file = area / "other-project-associations.py"; old_file.write_bytes(raw)
            ambient = cli.load_installer(old_file)
            with patch.dict(sys.modules, {"flight_associations": ambient}):
                selected, audit = service.helpers()
                self.assertEqual(Path(selected.__file__), root / ".flightcheck/scripts/flight_associations.py")
                state = cli.configuration_integrity(engine, root)[0]
                self.assertEqual(hashlib.sha256(Path(selected.__file__).read_bytes()).hexdigest(), state["files"][".flightcheck/scripts/flight_associations.py"]["sha256"])
                self.assertEqual(service.read()["flights"][0]["configuration"], original["configuration"])
                self.assertIs(sys.modules["flight_associations"], ambient, "Scoped helper loading must preserve unrelated import state")
            self.assertIn("workflow/scripts/flight_associations.py", cli.ADAPTER_COMPONENTS)

    def test_board_destination_binds_one_canonical_project(self):
        with self.config_fixture() as (area, root, engine, installed, cli, supplied):
            service = self.service(engine, root)
            policy = self.policy()
            legacy = "https://github.com/orgs/fixture-owner/projects/1"
            self.save(service, {"status_sync": policy, "resources": {"project_board": legacy}})
            self.assertEqual(service.read()["values"]["resources"]["project_board"], legacy, "Retain accepted legacy pointer data rather than destroying it during adapter migration")
            bound = {"url": legacy, "provider": policy["provider"], "project_id": policy["project_id"]}
            self.save(service, {"resources": {"project_board": bound}})
            current = service.read(); self.assertEqual(current["values"]["resources"]["project_board"], bound)
            self.assertEqual(current["values"]["status_sync"], policy)
            for bad in ({**bound, "project_id": "another-project"}, {**bound, "provider": "another-provider"}, {**bound, "url": "https://credential:secret@example.invalid/board"}):
                with self.subTest(bad=bad), self.assertRaises(ValueError): self.save(service, {"resources": {"project_board": bad}})
            self.assertEqual(service.read()["values"]["resources"]["project_board"], bound)
            self.save(service, {"resources": {"approved_logs": "ssh://developer@log-host/approved-route"}})
            self.assertEqual(service.read()["values"]["_flightcheck"]["fields"]["resources.approved_logs"]["scope"], "host")


if __name__ == "__main__": unittest.main()
