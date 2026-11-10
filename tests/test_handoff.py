"""Exercise the public handoff commands with real check receipts."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "examples/existing-project/scripts"


class HandoffTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        root = Path(scratch.name)
        self.checkout = root / "checkout"
        self.checkout.mkdir()
        self.inputs = self.checkout / "input"
        self.inputs.write_text("original")
        self.evidence = root / "evidence"
        self.evidence.mkdir(mode=0o700)
        (self.evidence / "candidate.diff").write_text("current diff")
        self.manifest = root / "task.json"
        command = [
            sys.executable, "-c",
            "import os, sys; print('required policy gate'); sys.exit(int(os.environ['FAIL_CHECK']))",
        ]
        self.request = {
            "command": command, "scope": "Required policy check", "summary": None,
            "fingerprint_command": [
                sys.executable, "-c", "from pathlib import Path; print(Path('input').read_text())",
            ],
            "artifacts": [],
        }
        self.gate = {"id": "policy", "request": self.request}
        self.task = {
            "candidate": "A", "saved_candidate": "A", "preview": None, "gates": [self.gate],
            "diff": "candidate.diff", "acceptance": ["policy passes"], "delivery": "local only",
        }

    def record(self, *, fail=False, refresh=False):
        return subprocess.run(
            [sys.executable, "-B", str(SCRIPTS / "capture_check.py"), "--gate", "policy",
             "--scope", self.request["scope"], "--candidate", self.task["candidate"],
             "--fingerprint-command", json.dumps(self.request["fingerprint_command"]),
             "--evidence-dir", str(self.evidence), *(["--refresh"] if refresh else []),
             "--", *self.request["command"]],
            cwd=self.checkout, env=dict(os.environ, FAIL_CHECK=str(int(fail))),
            check=False, capture_output=True, text=True, timeout=10,
        )

    def handoff(self, mode, expected_exit):
        self.manifest.write_text(json.dumps(self.task))
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPTS / "handoff.py"), mode, "--task", str(self.manifest),
             "--evidence-dir", str(self.evidence)],
            cwd=self.checkout, check=False, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, expected_exit, result.stderr)
        return json.loads(result.stdout)

    def test_clean_resume_and_final_review_use_the_verified_receipt(self):
        self.assertEqual(self.record().returncode, 0)
        self.task["candidate"] = "A-with-unrelated-edit"
        summary = self.handoff("resume", 0)
        self.assertEqual(summary["checks"][0]["status"], "reusable")
        self.assertEqual(summary["blockers"], [])
        self.assertEqual(summary["route"], "resume_work")
        self.assertEqual(self.handoff("review", 1)["blockers"], ["policy"])

        self.assertIn("Check reused:", self.record().stdout)
        reuse, = self.evidence.glob("reuse-*/reuse.json")
        self.gate["reuse"] = str(reuse.relative_to(self.evidence))
        packet = self.handoff("review", 0)
        self.assertTrue(packet["ready_for_review"])
        self.assertEqual(packet["checks"][0]["status"], "reused")
        self.assertEqual(packet["diff"]["path"], str((self.evidence / "candidate.diff").resolve()))
        Path(packet["checks"][0]["output"]).write_text("corrupted")
        self.assertEqual(self.handoff("review", 1)["checks"][0]["status"], "unverified")

    def test_changed_ui_requires_new_checks_and_current_approval_or_waiver(self):
        self.assertEqual(self.record().returncode, 0)
        self.task["candidate"] = "B"
        self.task["preview"] = {"surface": "new", "approved_surface": "old"}
        self.inputs.write_text("changed")
        summary = self.handoff("resume", 0)
        self.assertTrue(summary["candidate_changed"])
        self.assertEqual(summary["preview"]["status"], "stale")
        self.assertEqual(summary["checks"][0]["status"], "stale")
        self.assertEqual(summary["blockers"], ["policy", "preview approval"])
        self.task["preview"]["waiver"] = "explicit test waiver"
        self.assertEqual(self.handoff("review", 1)["blockers"], ["policy"])
        self.assertEqual(self.record().returncode, 0)
        waiver = self.task["preview"].pop("waiver")
        self.assertEqual(self.handoff("review", 1)["blockers"], ["preview approval"])
        self.task["preview"]["waiver"] = waiver
        packet = self.handoff("review", 0)
        self.assertEqual(packet["preview"]["status"], "stale")
        self.assertEqual(packet["checks"][0]["status"], "passed")

    def test_latest_failed_non_ui_gate_blocks_review_even_after_an_older_pass(self):
        self.assertEqual(self.handoff("review", 1)["checks"][0]["status"], "missing")
        self.assertEqual(self.record().returncode, 0)
        self.assertEqual(self.record(fail=True, refresh=True).returncode, 1)
        summary = self.handoff("resume", 0)
        self.assertEqual(summary["preview"]["status"], "not-applicable")
        self.assertEqual(summary["checks"][0]["status"], "failed")
        self.assertEqual(self.handoff("review", 1)["blockers"], ["policy"])
        self.assertEqual(self.record().returncode, 0)
        self.assertTrue(self.handoff("review", 0)["ready_for_review"])

    def test_direct_final_review_requires_an_explicit_clean_resume(self):
        self.assertEqual(self.record().returncode, 0)
        self.assertEqual(self.handoff("resume", 0)["route"], "resume_work")
        state = {"phase": "awaiting_final_review", "pending_work": False,
                 "pending_decisions": False, "active_processes": False}
        self.task["resume_state"] = state
        self.assertEqual(self.handoff("resume", 0)["route"], "final_review")
        for key in ("pending_work", "pending_decisions", "active_processes"):
            with self.subTest(key=key):
                state[key] = True
                self.assertEqual(self.handoff("resume", 0)["route"], "resume_work")
                state[key] = False
        self.task["preview"] = {"surface": "new", "approved_surface": "old", "waiver": "test waiver"}
        self.assertEqual(self.handoff("resume", 0)["route"], "resume_work")
        self.task["preview"].update(approved_surface="new", decision_reference="owner decision")
        self.assertEqual(self.handoff("resume", 0)["route"], "final_review")
        self.task["candidate"] = "B"
        self.assertEqual(self.handoff("resume", 0)["route"], "resume_work")
        self.task["candidate"] = "A"
        self.assertEqual(self.record(fail=True, refresh=True).returncode, 1)
        self.assertEqual(self.handoff("resume", 0)["route"], "resume_work")

    def test_code_review_reuses_a_session_only_for_an_in_scope_repair(self):
        self.assertEqual(self.handoff("code-review", 0)["action"], "start")
        (self.evidence / "findings.md").write_text("Unresolved boundary regression")
        (self.evidence / "repair.diff").write_text("Repair to the boundary")
        prior = {"candidate": "A", "session": "early-session", "verdict": "REVISE",
                 "findings": "findings.md", "repair_diff": "repair.diff", "scope_unchanged": True}
        self.task.update(candidate="B", early_review=prior)
        packet = self.handoff("code-review", 0)
        self.assertEqual((packet["action"], packet["session"], packet["reviewed_candidate"]),
                         ("resume", "early-session", "A"))
        self.assertEqual(Path(packet["repair_diff"]["path"]).name, "repair.diff")
        prior["scope_unchanged"] = False
        self.assertEqual(self.handoff("code-review", 0)["action"], "start")
        prior.update(scope_unchanged=True, repair_diff="../outside.diff")
        self.assertEqual(self.handoff("code-review", 0)["action"], "start")

    def test_code_review_waits_for_current_cheap_checks_and_leaves_later_gates_pending(self):
        self.gate["phase"] = "cheap"
        self.task["gates"].append({"id": "full-suite", "request": self.request})
        blocked = self.handoff("code-review", 1)
        self.assertEqual((blocked["action"], blocked["blockers"]), ("blocked", ["policy"]))
        self.assertEqual(self.record().returncode, 0)
        self.assertEqual(self.record(fail=True, refresh=True).returncode, 1)
        self.assertEqual(self.handoff("code-review", 1)["cheap_checks"][0]["status"], "failed")
        self.assertEqual(self.record().returncode, 0)
        self.assertEqual(self.handoff("code-review", 0)["action"], "start")
        self.assertEqual(self.handoff("review", 1)["blockers"], ["full-suite"])
        self.task["candidate"] = "B"
        self.assertEqual(self.handoff("code-review", 1)["blockers"], ["policy"])
        self.assertIn("Check reused:", self.record().stdout)
        reuse, = self.evidence.glob("reuse-*/reuse.json")
        self.gate["reuse"] = str(reuse.relative_to(self.evidence))
        check = self.handoff("code-review", 0)["cheap_checks"][0]
        self.assertEqual(check["status"], "reused")
        Path(check["output"]).write_text("corrupted")
        self.assertEqual(self.handoff("code-review", 1)["cheap_checks"][0]["status"], "unverified")


if __name__ == "__main__":
    unittest.main()
