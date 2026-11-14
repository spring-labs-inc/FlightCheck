"""Upstream documentation/policy assertions; not adopter runtime contracts."""

import json
from pathlib import Path
import unittest


class UpstreamPolicyTests(unittest.TestCase):
    def test_upstream_adoption_and_contribution_policy(self):
        root = Path(__file__).resolve().parents[1]
        example = root / "examples/existing-project"
        self.assertEqual((example / "AGENTS.md").read_text().count("when the owner explicitly selects"), 1)
        self.assertEqual(json.loads((example / ".codex/hooks.json").read_text())["hooks"], {})
        self.assertIn("Outside code contributions are currently deferred", (root / "CONTRIBUTING.md").read_text())
        self.assertTrue((root / "LICENSE").is_file())
