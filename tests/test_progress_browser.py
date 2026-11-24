"""Execute the shipped browser UI with a deterministic DOM, clock and transport."""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ProgressBrowserTests(unittest.TestCase):
    def test_freshness_disconnect_resume_identity(self):
        node = os.environ.get("FLIGHTCHECK_NODE") or shutil.which("node")
        if not node:
            self.skipTest("Node is required for the shipped task.js browser contract")
        result = subprocess.run([node, str(ROOT / "tests/progress_dom.cjs"),
                                 str(ROOT / "status-card/task.js"), str(ROOT / "status-card/task.html")],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"contract":"freshness-disconnect-resume-identity"', result.stdout)
