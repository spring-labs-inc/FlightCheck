"""Exercise the public handoff commands with real check receipts."""

import hashlib
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

    def record(self, *, fail=False, refresh=False, owner=None):
        return subprocess.run(
            [sys.executable, "-B", str(SCRIPTS / "capture_check.py"), "--gate", "policy",
             "--scope", self.request["scope"], "--candidate", self.task["candidate"],
             "--fingerprint-command", json.dumps(self.request["fingerprint_command"]),
             "--evidence-dir", str(self.evidence), *(["--refresh"] if refresh else []),
             *(["--owner", owner] if owner else []),
             *(item for path in self.request["artifacts"] for item in ("--artifact", path)),
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

    def test_check_plan_carries_only_current_receipts_from_an_allowed_owner(self):
        self.gate["owner"] = "worker"
        self.assertEqual(self.handoff("checks", 0)["checks"][0]["action"], "run")
        self.assertEqual(self.record(owner="worker").returncode, 0)
        check = self.handoff("checks", 0)["checks"][0]
        self.assertEqual((check["action"], check["owner"], check["assigned_owner"]), ("carry", "worker", "worker"))
        self.assertTrue(self.handoff("review", 0)["ready_for_review"])
        self.task["candidate"] = "B"
        self.assertEqual(self.handoff("checks", 0)["checks"][0]["action"], "reuse")
        self.gate["owner"] = "controller"
        self.assertEqual(self.handoff("checks", 0)["checks"][0]["action"], "run")
        self.assertEqual(self.handoff("review", 1)["checks"][0]["status"], "unverified")
        self.assertEqual(self.record(refresh=True, owner="controller").returncode, 0)
        self.gate["owner"] = "worker"
        check = self.handoff("checks", 0)["checks"][0]
        self.assertEqual((check["action"], check["owner"]), ("carry", "controller"))
        self.inputs.write_text("changed")
        self.assertEqual(self.handoff("checks", 0)["checks"][0]["action"], "run")

    def test_check_plan_preserves_newer_failures_and_incomplete_attempts(self):
        self.gate["owner"] = "worker"
        self.assertEqual(self.record(owner="worker").returncode, 0)
        self.assertEqual(self.record(fail=True, refresh=True, owner="worker").returncode, 1)
        self.assertEqual(self.handoff("checks", 0)["checks"][0]["action"], "repair")
        latest = json.loads((self.evidence / "gate-policy.json").read_text())
        (self.evidence / latest / "output.log").write_text("corrupted")
        self.assertEqual(self.handoff("checks", 0)["checks"][0]["action"], "run")
        self.task["candidate"] = "B"
        self.assertEqual(self.handoff("checks", 0)["checks"][0]["action"], "run")
        receipt = self.evidence / latest / "run.json"
        incomplete = json.loads(receipt.read_text())
        incomplete.update(status="incomplete", exit_code=None)
        receipt.write_text(json.dumps(incomplete))
        self.assertEqual(self.handoff("checks", 0)["checks"][0]["action"], "wait")

    def test_final_packet_verifies_test_identities_and_outcomes(self):
        baseline = {"passed": ["required"], "skipped": ["skip"], "expected_failures": ["xfail"], "failed": []}
        raw = json.dumps(baseline).encode()
        (self.evidence / "baseline.json").write_bytes(raw)
        report = self.checkout / "coverage.json"
        self.request["artifacts"] = [report.name]
        self.gate["coverage"] = {"artifact": report.name, "baseline": "baseline.json",
                                 "baseline_sha256": hashlib.sha256(raw).hexdigest()}
        report.write_text(json.dumps(dict(baseline, passed=["required", "added"])))
        self.assertEqual(self.record().returncode, 0)
        packet = self.handoff("review", 0)
        coverage = packet["checks"][0]["coverage"]["verified"]
        self.assertEqual((coverage["tests"], coverage["passed"], coverage["skipped"],
                          coverage["expected_failures"], coverage["baseline"]["matched"]), (4, 2, 1, 1, 3))
        Path(coverage["report"]).write_text("changed after capture")
        self.assertEqual(self.handoff("review", 1)["blockers"], ["policy"])

        report.write_text(json.dumps(dict(baseline, passed=["unrelated", "added"],
                                          skipped=["xfail"], expected_failures=["skip"])))
        self.assertEqual(self.record(refresh=True).returncode, 0)
        coverage = self.handoff("review", 1)["checks"][0]["coverage"]["verified"]
        self.assertEqual(coverage["baseline"]["missing"], ["required"])
        self.assertEqual(coverage["baseline"]["outcome_changed"], ["skip", "xfail"])

    def test_implementation_brief_excludes_review_state_and_private_commands(self):
        self.task.update(scope=["src/"], findings=["review detail"])
        self.gate.update(owner="worker", phase="cheap", invocation=["trusted-check", "policy"])
        self.task["gates"].append({"id": "private", "request": dict(self.request, command=["private-evaluator"]),
                                   "invocation": ["private-evaluator"]})
        brief = self.handoff("brief", 0)
        self.assertEqual(brief["checks"][0]["invocation"], ["trusted-check", "policy"])
        self.assertNotIn("invocation", brief["checks"][1])
        self.assertNotIn("preview", brief)
        self.assertNotIn("findings", brief)
        self.assertNotIn("private-evaluator", json.dumps(brief))
        self.assertIn("shared contract", brief["early_code"])
        self.assertIn("bounded invariant", brief["early_code"])
        self.task["early_code"] = "Review shared interfaces"
        self.assertEqual(self.handoff("brief", 0)["early_code"], self.task["early_code"])


if __name__ == "__main__":
    unittest.main()
