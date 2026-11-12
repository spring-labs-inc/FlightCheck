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
            "diff": "candidate.diff", "acceptance": [{"id": "policy", "description": "Policy passes",
                "proofs": [{"kind": "check", "gate": "policy", "assertion": "The native policy command rejects violations"}]}],
            "delivery": "local only",
        }
        self.handoff("preflight", 0)

    def record(self, *, fail=False, refresh=False, owner=None):
        return subprocess.run(
            [sys.executable, "-B", str(SCRIPTS / "capture_check.py"), "--gate", "policy",
             "--scope", self.request["scope"], "--candidate", self.task["candidate"],
             "--fingerprint-command", json.dumps(self.request["fingerprint_command"]),
             "--evidence-dir", str(self.evidence), *(["--refresh"] if refresh else []),
             *(["--owner", owner] if owner else []),
             *(["--isolated-reports"] if self.request.get("isolated_reports") else []),
             *(item for path in self.request["artifacts"] for item in ("--artifact", path)),
             "--", *self.request["command"]],
            cwd=self.checkout, env=dict(os.environ, FAIL_CHECK=str(int(fail))),
            check=False, capture_output=True, text=True, timeout=10,
        )

    def handoff(self, mode, expected_exit, review=None, amendment=None):
        self.manifest.write_text(json.dumps(self.task))
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPTS / "handoff.py"), mode, "--task", str(self.manifest),
             "--evidence-dir", str(self.evidence), *(["--review", str(review)] if review else []),
             *(["--amend-contract", amendment] if amendment else [])],
            cwd=self.checkout, check=False, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, expected_exit, result.stderr)
        return json.loads(result.stdout)

    def amend_fixture(self):
        contract = self.evidence / "acceptance-contract.json"
        path = self.evidence / "fixture-owner.json"
        path.write_text(json.dumps({"candidate": self.task["candidate"], "authority": "owner",
            "accepted": True, "source": "Synthetic fixture owner setup instruction", "reason": "Configure this test fixture",
            "previous_contract_sha256": hashlib.sha256(contract.read_bytes()).hexdigest()}))
        self.handoff("preflight", 0, amendment=path.name)

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
        self.amend_fixture()
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
        self.request["isolated_reports"] = True
        self.request["command"] = [sys.executable, "-c", "import os; from pathlib import Path; "
            "(Path(os.environ['FLIGHTCHECK_REPORT_DIR']) / 'coverage.json').write_bytes(Path('coverage.json').read_bytes())"]
        self.gate["coverage"] = {"artifact": report.name, "baseline": "baseline.json",
                                 "baseline_sha256": hashlib.sha256(raw).hexdigest()}
        report.write_text(json.dumps(dict(baseline, passed=["required", "added"])))
        self.amend_fixture()
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

    def review_file(self, **changes):
        review = {"candidate": self.task["candidate"], "role": "EVIDENCE", "verdict": "APPROVE",
                  "coverage": "Inspected current source, assertions and original policy receipt",
                  "criteria": [{"id": "policy", "sufficient": True,
                                "reason": "Inspected the policy assertion and its current native result"}],
                  "challenge": "Checked invalid input and unchanged caller state against the policy contract",
                  "findings": [], "test_requests": []}
        review.update(changes)
        path = self.evidence / "native-review.json"
        path.write_text(json.dumps(review))
        return path

    def configure_behavior_check(self):
        baseline = {key: [] for key in ("passed", "skipped", "expected_failures", "failed")}
        raw = json.dumps(baseline).encode()
        (self.evidence / "behavior-baseline.json").write_bytes(raw)
        (self.checkout / "spec.py").write_text("assert input_is_valid_and_caller_is_unchanged\n")
        self.request.update(artifacts=["behavior.json", "spec.py"], isolated_reports=True,
            command=[sys.executable, "-c", "import json, os, sys; from pathlib import Path; "
                "out=Path(os.environ['FLIGHTCHECK_REPORT_DIR']); bad=Path('input').read_text()=='broken'; "
                "report={'passed':[] if bad else ['case'], 'failed':['case'] if bad else [], "
                "'skipped':[], 'expected_failures':[]}; "
                "(out/'behavior.json').write_text(json.dumps(report)); "
                "(out/'spec.py').write_bytes(Path('spec.py').read_bytes()); sys.exit(int(bad))"])
        self.gate["coverage"] = {"artifact": "behavior.json", "baseline": "behavior-baseline.json",
                                 "baseline_sha256": hashlib.sha256(raw).hexdigest()}
        self.amend_fixture()

    def test_preflight_freezes_criteria_and_checks_the_real_evidence_round_trip(self):
        packet = self.handoff("preflight", 0)
        self.assertTrue(packet["ready"])
        self.assertEqual(packet["probe"]["status"], "passed")
        self.assertEqual(self.record().returncode, 0)
        self.task["acceptance"][0]["description"] = "Silently weakened scope"
        self.assertIn("acceptance contract", self.handoff("review", 1)["blockers"])
        self.task["acceptance"] = ["legacy unchecked prose"]
        self.assertIn("acceptance contract", self.handoff("review", 1)["blockers"])

    def test_a_passing_suite_does_not_prove_a_missing_behavior_identity(self):
        self.configure_behavior_check()
        # A new flight freezes a criterion naming the exact behavior assertion.
        (self.evidence / "acceptance-contract.json").unlink()
        self.task["acceptance"][0]["proofs"][0]["tests"] = ["unexecuted-boundary-case"]
        self.handoff("preflight", 0)
        self.assertEqual(self.record(owner="controller").returncode, 0)
        packet = self.handoff("review", 1)
        self.assertEqual(packet["checks"][0]["status"], "passed")
        self.assertIn("acceptance:policy", packet["blockers"])

    def test_final_verdict_requires_current_independent_semantic_assessment(self):
        self.assertEqual(self.record().returncode, 0)
        packet = self.handoff("verdict", 0, self.review_file())
        self.assertTrue(packet["ready_for_approval"])
        for changes in ({"role": "CODE"}, {"criteria": []}, {"challenge": ""},
                        {"criteria": [{"id": "policy", "sufficient": False, "reason": "Only whitespace proved"}]}):
            with self.subTest(changes=changes):
                self.assertFalse(self.handoff("verdict", 1, self.review_file(**changes))["ready_for_approval"])
        finding = {"id": "process-1", "kind": "process", "severity": "BLOCKER",
                   "reference": "required evidence", "impact": "Acceptance is unproven"}
        packet = self.handoff("verdict", 1, self.review_file(findings=[finding]))
        self.assertEqual(packet["verdict"], "REVISE")
        self.assertIn("verdict does not match findings", packet["blockers"])

    def test_reviewer_request_survives_omission_and_needs_a_fresh_controller_run(self):
        self.configure_behavior_check()
        self.assertEqual(self.record(owner="controller").returncode, 0)
        request = {"id": "boundary", "criterion": "policy", "input": "Smallest invalid input",
                   "expected": "Reject it without modifying the caller", "reason": "Alternate entry point"}
        self.handoff("requests", 0, self.review_file(role="CODE", test_requests=[request]))
        self.assertIn("test-request:boundary", self.handoff("code-review", 1)["blockers"])
        self.task["request_checks"] = {"boundary": {"gate": "policy", "tests": ["case"],
                                                   "assertion": "Actual counterexample test in spec.py"}}
        # The pass predates the request and cannot be relabeled as its execution.
        self.assertIn("test-request:boundary", self.handoff("review", 1)["blockers"])
        self.assertEqual(self.record(owner="controller", refresh=True).returncode, 0)
        self.assertTrue(self.handoff("review", 0)["ready_for_review"])
        # A subsequent reviewer omitting the request cannot remove its obligation.
        self.assertTrue(self.handoff("verdict", 0, self.review_file())["ready_for_approval"])
        self.inputs.write_text("changed")
        self.assertIn("test-request:boundary", self.handoff("review", 1)["blockers"])

    def test_functional_finding_needs_same_spec_failed_before_and_passed_after(self):
        self.configure_behavior_check()
        self.inputs.write_text("broken")
        self.assertEqual(self.record(owner="controller").returncode, 1)
        before = json.loads((self.evidence / "gate-policy.json").read_text()) + "/run.json"
        finding = {"id": "caller-state", "kind": "functional", "severity": "BLOCKER",
                   "reference": "spec.py", "impact": "The caller's state is changed"}
        self.handoff("requests", 0, self.review_file(role="CODE", verdict="REVISE", findings=[finding]))
        self.inputs.write_text("fixed")
        self.task["candidate"] = "B"
        self.assertEqual(self.record(owner="controller", refresh=True).returncode, 0)
        self.assertIn("regression:caller-state", self.handoff("review", 1)["blockers"])
        self.task["regressions"] = {"caller-state": {"before": before, "after_gate": "policy",
            "report": "behavior.json", "spec": "spec.py", "tests": ["case"]}}
        self.assertTrue(self.handoff("verdict", 0, self.review_file())["ready_for_approval"])
        # A different test cannot pass as proof of repairing the original defect.
        (self.checkout / "spec.py").write_text("weakened assertion")
        self.assertEqual(self.record(owner="controller", refresh=True).returncode, 0)
        self.assertIn("regression:caller-state", self.handoff("review", 1)["blockers"])

    def test_stale_or_missing_owner_decision_cannot_substitute_for_acceptance(self):
        (self.evidence / "acceptance-contract.json").unlink()
        self.task["acceptance"] = [{"id": "surface", "description": "Owner accepts the surface",
                                  "proofs": [{"kind": "owner", "reference": "owner.json"}]}]
        self.handoff("preflight", 0)
        self.assertEqual(self.record().returncode, 0)
        self.assertIn("acceptance:surface", self.handoff("review", 1)["blockers"])
        path = self.evidence / "owner.json"
        decision = {"candidate": "old", "criterion": "surface", "accepted": True,
                    "authority": "owner", "source": "actual owner message", "reason": "Preview approved"}
        path.write_text(json.dumps(decision))
        self.assertIn("acceptance:surface", self.handoff("review", 1)["blockers"])
        decision["candidate"] = self.task["candidate"]
        path.write_text(json.dumps(decision))
        self.assertTrue(self.handoff("review", 0)["ready_for_review"])

    def test_owner_exception_remains_an_observation_requiring_bound_approval(self):
        self.assertEqual(self.record(owner="controller").returncode, 0)
        finding = {"id": "live-only", "kind": "functional", "severity": "CONCERN",
                   "reference": "external service", "impact": "Cannot reproduce an unavailable live service"}
        self.handoff("requests", 0, self.review_file(role="CODE", findings=[finding]))
        self.task["regressions"] = {"live-only": {"exception": "exception.json"}}
        self.assertIn("regression:live-only", self.handoff("review", 1)["blockers"])
        decision = {"candidate": "A", "authority": "owner", "accepted": True,
                    "finding": "live-only", "source": "Actual synthetic owner instruction",
                    "reason": "Accept live-only risk for this fixture"}
        (self.evidence / "exception.json").write_text(json.dumps(decision))
        native = self.review_file(verdict="APPROVE_WITH_OBSERVATIONS")
        packet = self.handoff("verdict", 1, native)
        self.assertEqual(packet["blockers"], ["explicit owner approval of observations"])
        self.task["observation_approval"] = "observations.json"
        decision.pop("finding")
        decision["observations_sha256"] = packet["observations_sha256"]
        (self.evidence / "observations.json").write_text(json.dumps(decision))
        self.assertTrue(self.handoff("verdict", 0, native)["ready_for_approval"])
        # A changed risk set cannot inherit the previous approval.
        changed = dict(finding, id="new-risk", kind="process", impact="A different live risk")
        self.assertIn("explicit owner approval of observations", self.handoff(
            "verdict", 1, self.review_file(verdict="APPROVE_WITH_OBSERVATIONS", findings=[changed]))["blockers"])

    def test_scope_amendment_needs_the_actual_owner_and_archives_the_old_contract(self):
        contract = self.evidence / "acceptance-contract.json"
        previous = contract.read_bytes()
        self.task["acceptance"][0]["description"] = "Owner's revised scope"
        self.manifest.write_text(json.dumps(self.task))
        decision = {"candidate": "A", "authority": "worker", "accepted": True,
                    "previous_contract_sha256": hashlib.sha256(previous).hexdigest(),
                    "source": "Owner instruction fixture", "reason": "Revised scope"}
        path = self.evidence / "scope-amendment.json"
        path.write_text(json.dumps(decision))
        args = [sys.executable, "-B", str(SCRIPTS / "handoff.py"), "preflight", "--task", str(self.manifest),
                "--evidence-dir", str(self.evidence), "--amend-contract", path.name]
        self.assertEqual(subprocess.run(args, cwd=self.checkout, capture_output=True).returncode, 2)
        self.assertEqual(contract.read_bytes(), previous)
        decision["authority"] = "owner"
        path.write_text(json.dumps(decision))
        self.assertEqual(subprocess.run(args, cwd=self.checkout, capture_output=True).returncode, 0)
        self.assertEqual(next((self.evidence / "contracts").glob("*.json")).read_bytes(), previous)
        self.assertEqual(self.record().returncode, 0)
        self.assertTrue(self.handoff("review", 0)["ready_for_review"])
        self.task["gates"] = []
        self.assertIn("acceptance contract", self.handoff("review", 1)["blockers"])

    def test_request_specs_cannot_be_overwritten_by_a_later_review(self):
        request = {"id": "boundary", "criterion": "policy", "input": "invalid input",
                   "expected": "reject", "reason": "boundary case"}
        self.handoff("requests", 0, self.review_file(test_requests=[request]))
        self.task["candidate"] = "B"
        # Repetition keeps the original request time and source candidate.
        self.handoff("requests", 0, self.review_file(test_requests=[request]))
        state = json.loads((self.evidence / "review-obligations.json").read_text())
        self.assertEqual(state["requests"]["boundary"]["candidate"], "A")
        self.manifest.write_text(json.dumps(self.task))
        native = self.review_file(test_requests=[dict(request, expected="silently accept")])
        result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "handoff.py"), "requests", "--task",
            str(self.manifest), "--evidence-dir", str(self.evidence), "--review", str(native)],
            cwd=self.checkout, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads((self.evidence / "review-obligations.json").read_text()), state)


    def test_frozen_gate_definition_cannot_be_weakened_under_the_same_id(self):
        import copy
        self.configure_behavior_check()
        original = copy.deepcopy(self.task)
        baseline = self.evidence / 'weaker-baseline.json'
        baseline.write_text(json.dumps({'passed':[], 'skipped':[], 'expected_failures':[], 'failed':[]}))
        mutations = {
            'command': lambda g: g['request'].update(command=[sys.executable, '-c', "print('unrelated pass')"]),
            'fingerprint': lambda g: g['request'].update(fingerprint_command=[sys.executable, '-c', "print('weaker probe')"]),
            'scope': lambda g: g['request'].update(scope='Only a subset of the required behavior'),
            'phase': lambda g: g.update(phase='cheap'),
            'coverage': lambda g: g['coverage'].update(baseline=baseline.name, baseline_sha256=hashlib.sha256(baseline.read_bytes()).hexdigest()),
            'removed_coverage': lambda g: g.pop('coverage'),
        }
        for label, mutate in mutations.items():
            with self.subTest(definition=label):
                self.task = copy.deepcopy(original)
                self.gate = self.task['gates'][0]
                self.request = self.gate['request']
                mutate(self.gate)
                # A native zero exit does not authorize a changed required gate.
                self.assertEqual(self.record(owner='controller', refresh=True).returncode, 0)
                packet = self.handoff('code-review', 1)
                self.assertIn('acceptance contract', packet['blockers'])
                self.assertIn('acceptance contract', self.handoff('review', 1)['blockers'])

    def test_incomplete_native_reviews_never_imply_zero_findings_or_requests(self):
        self.assertEqual(self.record().returncode, 0)
        native = self.review_file()
        complete = json.loads(native.read_text())
        bad = []
        for key in ('coverage', 'findings', 'test_requests'):
            missing = dict(complete)
            missing.pop(key)
            bad.append(missing)
        missing_all = dict(complete)
        for key in ('coverage', 'findings', 'test_requests'):
            missing_all.pop(key)
        bad.append(missing_all)
        for key, values in [('coverage', ['', None, []]), ('findings', [None, {}, '']),
                            ('test_requests', [None, {}, ''])]:
            bad.extend(dict(complete, **{key:value}) for value in values)
        for review in bad:
            with self.subTest(review=review):
                native.write_text(json.dumps(review))
                self.manifest.write_text(json.dumps(self.task))
                result = subprocess.run([sys.executable, '-B', str(SCRIPTS / 'handoff.py'), 'verdict',
                    '--task', str(self.manifest), '--evidence-dir', str(self.evidence), '--review', str(native)],
                    cwd=self.checkout, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.handoff('verdict', 0, self.review_file())['ready_for_approval'])



if __name__ == "__main__":
    unittest.main()
