"""Bounded shared-foundation acceptance witnesses."""
import unittest
import contextlib
from unittest.mock import patch

from foundation_config_cases import ConfigurationCases
from foundation_flight_cases import FlightCases
from test_settings_adapter_bootstrap import current_adapter


class FoundationTests(ConfigurationCases, FlightCases, unittest.TestCase):
    """One native identity per frozen criterion; detailed assertions use subcases."""

    @contextlib.contextmanager
    def config_fixture(self, legacy=False):
        with super().config_fixture(legacy=legacy) as fixture:
            if not legacy:
                yield fixture
                return
            area, root, engine, installed, cli, supplied = fixture
            adapter = current_adapter(self, area)
            original = (root / engine.CONFIG).read_bytes()
            pins = (root / cli.PIN).read_bytes()
            state = installed.read_state(root)
            plan, _ = cli.configuration_adapter_plan(adapter, root, cli.sha(original), "Fixture owner explicitly migrates legacy adapter")
            cli.configuration_adapter_apply(adapter, root, plan)
            self.assertEqual((root / engine.CONFIG).read_bytes(), original)
            self.assertEqual((root / cli.PIN).read_bytes(), pins)
            self.assertEqual(adapter.read_state(root)["source"], state["source"])
            # Configuration writes now require explicit adapter migration. The
            # updated installed verifier checks that enumerated adapter while
            # retaining the old workflow source/runtime pins and legacy modes;
            # the pre-adapter historical verifier correctly lacks that schema.
            updated = self.config_module(root / ".flightcheck/install.py", "migrated_fixture_installer")
            yield area, root, adapter, updated, cli, supplied

    def test_revision_preimage_race(self):
        with self.config_fixture() as (_, root, engine, installed, cli, supplied):
            model = cli.configuration_model(engine, root)
            path = root / engine.CONFIG
            original = path.read_bytes()
            owner = original + b"\n "
            snapshot = model.snapshot
            observed = []
            def owner_edit_after_snapshot(project):
                result = snapshot(project)
                path.write_bytes(owner)
                observed.append(project)
                return result
            with patch.object(cli, "configuration_model", return_value=model), patch.object(model, "snapshot", side_effect=owner_edit_after_snapshot):
                with self.assertRaisesRegex(ValueError, "preimage|revision|changed"):
                    cli.configuration_plan(engine, root, {"protected_branches": ["release-next"]}, model.revision(original), "Owner update")
            self.assertEqual(observed, [root], "The owner edit must occur at the actual installed-model planning seam")
            self.assertEqual(path.read_bytes(), owner, "Planner must preserve intervening owner bytes")


if __name__ == "__main__":
    unittest.main()
