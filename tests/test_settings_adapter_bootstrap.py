"""Explicit adapter migration for recognized installations predating the model."""
import json
import os
from pathlib import Path
import shutil
import stat
import unittest

from foundation_config_cases import ConfigurationCases, PRODUCT


def current_adapter(case, area):
    """A clean current fixture source, independent of developer checkout state."""
    source = area / "current-adapter-source"
    source.mkdir()
    manifest = json.loads((PRODUCT / "setup/manifest.json").read_bytes())
    for name in {row[0] for row in manifest["files"]}:
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PRODUCT / name, target)
    for args in (("init", "-q", "--template=", "-b", "trunk"),
                 ("config", "core.hooksPath", os.devnull), ("add", "."),
                 ("-c", "user.name=Adapter fixture", "-c", "user.email=fixture@example.invalid",
                  "-c", "commit.gpgsign=false", "commit", "-qm", "Pinned current adapter fixture")):
        case.config_git(source, *args)
    return case.config_module(source / "setup/install.py", "explicit_current_adapter")


class SettingsAdapterBootstrapTests(unittest.TestCase):
    config_fixture = ConfigurationCases.config_fixture
    config_module = ConfigurationCases.config_module
    config_git = ConfigurationCases.config_git

    def test_explicit_legacy_adapter_bootstrap_and_fail_closed_models(self):
        with self.config_fixture(legacy=True) as (area, root, engine, installed, cli, supplied):
            adapter = current_adapter(self, area)
            state = json.loads((root / engine.STATE).read_bytes())
            config = (root / engine.CONFIG).read_bytes()
            revision = cli.sha(config)
            pin = (root / cli.PIN).read_bytes()
            mode = stat.S_IMODE((root / engine.CONFIG).stat().st_mode)
            helper = root / ".flightcheck/scripts/project_config.py"
            self.assertFalse(helper.exists())
            with self.assertRaisesRegex(ValueError, "configuration model.*unavailable"):
                cli.configuration_plan(adapter, root, {"review_client": "Unapproved ordinary write"}, revision, "Fixture owner")
            # This is the public operation under test, not fixture setup. Its
            # reviewed explicit migration must bootstrap the genuinely absent model.
            plan, _ = cli.configuration_adapter_plan(adapter, root, revision, "Owner explicitly migrates legacy configuration adapter")
            result = cli.configuration_adapter_apply(adapter, root, plan)
            self.assertEqual(result["status"], "configuration_adapter_updated")
            self.assertEqual((root / engine.CONFIG).read_bytes(), config)
            self.assertEqual(stat.S_IMODE((root / engine.CONFIG).stat().st_mode), mode)
            self.assertEqual((root / cli.PIN).read_bytes(), pin)
            updated = json.loads((root / engine.STATE).read_bytes())
            self.assertEqual(updated["source"], state["source"])
            changed = {op["path"] for op in plan["operations"]}
            for name in state["files"]:
                if name not in changed:
                    self.assertEqual(updated["files"][name], state["files"][name])
            self.assertEqual(cli.configuration_model(adapter, root).SETTINGS_SCHEMA, 1)
            before = helper.read_bytes()
            for replacement in (None, before + b"\n# changed installed helper\n"):
                with self.subTest(helper="missing" if replacement is None else "tampered"):
                    if replacement is None: helper.unlink()
                    else: helper.write_bytes(replacement)
                    for operation in (cli.configuration_model,
                                      lambda module, project: cli.configuration_adapter_plan(module, project, revision, "Owner cannot bypass integrity")):
                        with self.assertRaisesRegex(ValueError, "Missing|Modified"):
                            operation(adapter, root)
                    helper.write_bytes(before)
            self.assertEqual((root / engine.CONFIG).read_bytes(), config)
        with self.config_fixture(legacy=True) as (area, root, engine, installed, cli, supplied):
            adapter = current_adapter(self, area)
            helper = root / ".flightcheck/scripts/project_config.py"
            helper.parent.mkdir(parents=True, exist_ok=True)
            marker = area / "undeclared-helper-executed"
            helper.write_text("from pathlib import Path\nPath(" + repr(str(marker)) + ").write_text('forbidden')\n")
            with self.assertRaisesRegex(ValueError, "Unrecognized"):
                cli.configuration_adapter_plan(adapter, root, cli.sha((root / engine.CONFIG).read_bytes()), "Owner explicit adapter migration")
            self.assertFalse(marker.exists())
            with self.assertRaisesRegex(ValueError, "configuration model.*unavailable"):
                cli.configuration_model(adapter, root)
