"""Public, project-independent workflow contracts using real native receipts."""

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(os.environ.get("FLIGHTCHECK_PRODUCT_ROOT", Path(__file__).resolve().parents[1])) / "examples/existing-project/scripts"
OUTCOMES = ("passed", "skipped", "expected_failures", "failed")


class FlightFixture(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.checkout = self.root / "project"
        self.checkout.mkdir()
        self.evidence = self.root / "evidence"
        self.evidence.mkdir(mode=0o700)
        self.manifest = self.root / "task.json"
        self.product = self.checkout / "product"
        self.product.write_text("good")
        self.fixture = self.checkout / "fixture.json"
        self.fixture.write_text('{"contract":"two independently observable results"}\n')
        self.producer = self.checkout / "probe.py"
        self.producer.write_text(
            "import json,os,sys\nfrom pathlib import Path\n"
            "out=Path(os.environ['FLIGHTCHECK_REPORT_DIR'])\n"
            "mode=Path('product').read_text();bad=mode.startswith('bad')\n"
            "passed=[] if bad else ['case.a','case.b']\n"
            "if mode=='only-a':passed=['case.a']\n"
            "if mode=='similar':passed=['case.a-similar','case.b']\n"
            "if mode=='reordered':passed.reverse()\n"
            "report={'passed':passed,'skipped':[],'expected_failures':[],"
            "'failed':['case.a','case.b'] if bad else ['case.a'] if mode=='duplicate' else []}\n"
            "if mode in ['skipped','expected_failures']:report['passed']=['case.a'];report[mode]=['case.b']\n"
            "if mode=='members-reordered':report=dict(reversed(list(report.items())))\n"
            "if mode=='malformed':report={'passed':'case.a'}\n"
            "(out/'coverage.json').write_text(json.dumps(report))\n"
            "(out/'fixture.json').write_bytes(Path('fixture.json').read_bytes())\n"
            "print(report)\nsys.exit(int(bad))\n"
        )
        (self.evidence / "baseline.json").write_text(json.dumps({k: [] for k in OUTCOMES}))
        (self.evidence / "candidate.diff").write_text("synthetic project change")
        self.request = {
            "command": [sys.executable, "-B", str(self.producer)],
            "scope": "Both public results of the toy operation",
            "summary": None,
            "fingerprint_command": [sys.executable, "-B", "-c",
                "import hashlib;from pathlib import Path;"
                "print([(n,hashlib.sha256(Path(n).read_bytes()).hexdigest()) "
                "for n in ['product','probe.py','fixture.json']])"],
            "artifacts": ["coverage.json", "fixture.json"], "isolated_reports": True,
        }
        self.gate = {"id": "operation", "request": self.request, "owner": "controller",
                     "coverage": {"artifact": "coverage.json", "baseline": "baseline.json",
                                  "baseline_sha256": self.sha(self.evidence / "baseline.json")}}
        self.task = {"scope": "Preserve independently observable operation results",
                     "candidate": "A", "saved_candidate": "A", "preview": None,
                     "gates": [self.gate], "diff": "candidate.diff", "delivery": "local fixture only",
                     "acceptance": [{"id": "operation", "kind": "policy",
                        "description": "The native evidence preserves both named results",
                        "proofs": [{"kind": "check", "gate": "operation", "tests": ["case.a", "case.b"],
                                    "assertion": "Both identities have actual passing native outcomes"}]}]}
        self.ctl("preflight")

    @staticmethod
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def ctl(self, mode, expected=0, review=None, target=None):
        self.manifest.write_text(json.dumps(self.task))
        args = [sys.executable, "-B", str(SCRIPTS / "handoff.py"), mode,
                "--task", str(self.manifest), "--evidence-dir", str(self.evidence)]
        if review:
            args += ["--review", str(review)]
        if target:
            args += ["--target", target]
        p = subprocess.run(args, cwd=self.checkout, capture_output=True, text=True, timeout=15)
        self.assertEqual(p.returncode, expected, p.stdout + p.stderr)
        return json.loads(p.stdout) if p.stdout.strip() else {}

    def record(self, expected=0, owner="controller"):
        args = [sys.executable, "-B", str(SCRIPTS / "capture_check.py"),
                "--evidence-dir", str(self.evidence), "--candidate", self.task["candidate"],
                "--gate", self.gate["id"], "--owner", owner, "--scope", self.request["scope"],
                "--fingerprint-command", json.dumps(self.request["fingerprint_command"]),
                "--isolated-reports", "--artifact", "coverage.json", "--artifact", "fixture.json",
                "--refresh", "--", *self.request["command"]]
        p = subprocess.run(args, cwd=self.checkout, capture_output=True, text=True, timeout=15)
        self.assertEqual(p.returncode, expected, p.stdout + p.stderr)
        return json.loads((self.evidence / ("gate-" + self.gate["id"] + ".json")).read_text()) + "/run.json"

    def native_review(self, role="EVIDENCE", verdict="APPROVE", findings=None, requests=None, **extra):
        path = self.root / "review.json"
        case_ids = {case["id"] for item in self.task["acceptance"] for case in item.get("cases", [])}
        if (self.evidence / "challenge-plan.json").exists():
            case_ids.update(json.loads((self.evidence / "challenge-plan.json").read_text())["cases"])
        data = {"candidate": self.task["candidate"], "role": role, "verdict": verdict,
                "coverage": "Synthetic unit-test reviewer input; not an implementation approval",
                "criteria": [{"id": item["id"], "sufficient": True, "reason": "Fixture assertions inspected"}
                             for item in self.task["acceptance"]],
                "challenge": "Synthetic independent case assessment for this API test",
                "findings": findings or [], "test_requests": requests or [],
                "case_assessments": [{"id": key, "sufficient": True, "reason": "Fixture case assertion inspected"}
                                     for key in sorted(case_ids)], **extra}
        path.write_text(json.dumps(data))
        return path

    def obligation(self):
        self.product.write_text("bad")
        before = self.record(1)
        request = {"id": "first-request", "criterion": "operation", "input": "first public result",
                   "expected": "valid result without caller mutation", "reason": "Boundary invariant"}
        finding = {"id": "first-finding", "kind": "functional", "severity": "BLOCKER",
                   "reference": "public operation", "impact": "The first public result is invalid"}
        self.ctl("requests", review=self.native_review("CODE", "REVISE", [finding], [request]))
        self.task["request_checks"] = {"first-request": {"gate": "operation", "tests": ["case.a"],
                                                       "assertion": "The concrete requested first result"}}
        self.task["regressions"] = {"first-finding": {"before": before, "after_gate": "operation",
            "report": "coverage.json", "spec": "fixture.json", "tests": ["case.a"]}}
        return before

    def amend(self, expected=0):
        path = self.evidence / "owner.json"
        path.write_text(json.dumps({"candidate": self.task["candidate"], "authority": "owner",
            "accepted": True, "source": "Synthetic fixture setup instruction", "reason": "Configure test contract",
            "previous_contract_sha256": self.sha(self.evidence / "acceptance-contract.json")}))
        self.manifest.write_text(json.dumps(self.task))
        p = subprocess.run([sys.executable, "-B", str(SCRIPTS / "handoff.py"), "preflight",
            "--task", str(self.manifest), "--evidence-dir", str(self.evidence), "--amend-contract", path.name],
            cwd=self.checkout, capture_output=True, text=True, timeout=15)
        self.assertEqual(p.returncode, expected, p.stdout + p.stderr)

    def case(self, key="first-case", tests=None, kind="regression"):
        return {"id": key, "dimension": "public observation", "input": "A caller invokes the operation",
                "observable": "The requested public result and unchanged caller state",
                "expected": "A valid result", "expectation": {"kind": kind, "reference": "task contract"},
                "gate": self.gate["id"], "tests": tests or ["case.a"]}

    def proposal(self, cases=None):
        brief = self.ctl("challenge-brief")
        if cases is None:
            case = self.case("independent-case")
            case.pop("gate")
            case.pop("tests")
            cases = [dict(case, criterion="operation")]
        return {"role": "EVIDENCE", "scope_sha256": brief["scope_sha256"],
                "coverage": "Synthetic independent planning context; no implementation narrative", "cases": cases}

    def submit_plan(self, proposal=None, expected=0):
        path = self.root / "independent-plan.json"
        path.write_text(json.dumps(proposal or self.proposal()))
        return self.ctl("challenges", expected, review=path)

    def enable_behavior(self, cases=None):
        self.task["acceptance"][0].update(kind="behavior", cases=cases or [self.case()])
        self.amend()
        self.submit_plan()
        self.task["challenge_checks"] = {"independent-case": {"gate": self.gate["id"], "tests": ["case.a"]}}

    def control(self, receipt, candidate="A", source="baseline"):
        return {"receipt": receipt, "candidate": candidate, "source": source,
                "report": "coverage.json", "spec": "fixture.json"}

    def complete_behavior(self, cases=None):
        self.enable_behavior(cases)
        self.product.write_text("bad")
        before = self.record(1)
        self.task["case_controls"] = {key: self.control(before)
            for key in [case["id"] for case in self.task["acceptance"][0]["cases"]] + ["independent-case"]}
        self.product.write_text("good")
        self.task["candidate"] = "B"
        self.record()
        return before

    def false_claim(self, unrelated=False):
        self.record()
        finding = {"id": "false-claim", "kind": "functional", "severity": "BLOCKER",
                   "reference": "public operation", "impact": "Alleged invalid first result"}
        requests = [{"id": "linked-request", "criterion": "operation", "input": "first result",
                     "expected": "alleged alternate contract", "reason": "Original mistaken premise"}]
        if unrelated:
            requests.append(dict(requests[0], id="unrelated-request", input="separate caller"))
        self.ctl("requests", review=self.native_review("CODE", "REVISE", [finding], requests))
        return copy.deepcopy(json.loads((self.evidence / "review-obligations.json").read_text()))

    def refutation(self, kind, identity, receipt):
        if kind == "challenge-case":
            entry = json.loads((self.evidence / "challenge-plan.json").read_text())["cases"][identity]
            original = entry["plan_sha256"]
        else:
            state = json.loads((self.evidence / "review-obligations.json").read_text())
            entry = state["findings" if kind == "functional-finding" else "requests"][identity]
            original = entry["review_sha256"]
        return {"scope_sha256": self.ctl("challenge-brief")["scope_sha256"],
                "original_sha256": original, "assertion": "Original public result contradicts the claim's premise",
                "reference": "Documented two-result operation contract", "receipt": receipt,
                "report": "coverage.json", "spec": "fixture.json", "tests": ["case.a"]}

    def acknowledgments(self):
        packet = self.ctl("disposition-review")
        self.assertEqual(packet["purpose"], "disposition")
        return [{"id": row["id"], "kind": row["kind"],
                 "proposal_sha256": row["evidence"]["proposal_sha256"],
                 "reason": "Synthetic independent reviewer inspected the original-product counterevidence"}
                for row in packet["proposals"]]


class RecoveryPlannerTests(FlightFixture):
    def test_repair_after_code_approval_refreshes_earlier_proof(self):
        before = self.obligation()
        original = (self.evidence / "review-obligations.json").read_bytes()
        before_hash = self.sha(self.evidence / before)
        self.task["candidate"] = "B"
        self.product.write_text("good repaired first result")
        plan = self.ctl("next-action")
        self.assertEqual(plan["state"], "needs_checks")
        self.assertEqual([(a["action"], a.get("gate")) for a in plan["actions"]], [("run", "operation")])
        self.assertEqual(self.ctl("code-review", 1)["recovery"]["state"], "needs_checks")
        self.record()
        self.assertEqual(self.ctl("next-action")["state"], "ready")
        self.assertEqual(self.ctl("code-review")["action"], "start")
        self.ctl("requests", review=self.native_review("CODE"))
        # Later EVIDENCE asks for a distinct result after CODE has approved.
        later = {"id": "later-request", "criterion": "operation", "input": "second public result",
                 "expected": "second result preserved", "reason": "Alternate caller"}
        self.ctl("requests", review=self.native_review("EVIDENCE", "REVISE", requests=[later]))
        self.task["request_checks"]["later-request"] = {"gate": "operation", "tests": ["case.b"],
                                                       "assertion": "Second result on the repaired source"}
        self.task["candidate"] = "C"
        self.product.write_text("good repaired alternate caller")
        self.task["early_review"] = {"candidate": "B", "verdict": "APPROVE", "session": "prior-code"}
        plan = self.ctl("next-action")
        self.assertEqual(plan["action"], "run_checks")
        self.assertIn("first-finding", {r["id"] for r in plan["obligations"]["obligations"]})
        self.assertEqual(self.ctl("code-review", 1)["recovery"]["state"], "needs_checks")
        self.record()
        self.assertEqual(self.ctl("code-review")["action"], "start")
        self.ctl("requests", review=self.native_review("CODE"))
        self.assertEqual(self.ctl("next-action", target="final")["state"], "ready")
        self.assertTrue(self.ctl("verdict", review=self.native_review())["ready_for_approval"])
        state = json.loads((self.evidence / "review-obligations.json").read_text())
        old = json.loads(original)
        for group in ("requests", "findings"):
            for key, value in old[group].items():
                self.assertEqual(state[group][key], value)
        self.assertEqual(self.sha(self.evidence / before), before_hash)

    def test_repeated_repair_and_restart(self):
        self.obligation()
        for version in ("B", "C", "D"):
            self.task["candidate"] = version
            self.product.write_text("good " + version)
            # Every public call starts a new process from persisted task/evidence.
            self.assertEqual(self.ctl("next-action")["state"], "needs_checks")
            self.record()
            self.assertEqual(self.ctl("next-action")["state"], "ready")
            self.ctl("requests", review=self.native_review("CODE"))
        self.assertTrue(self.ctl("review")["ready_for_review"])
        self.assertEqual(len(list(self.evidence.glob("check-*/run.json"))), 4)

    def test_invalid_history_never_yields_ready(self):
        self.obligation()
        self.task["candidate"] = "B"
        self.product.write_text("good")
        self.record(owner="worker")
        plan = self.ctl("next-action")
        self.assertNotEqual(plan["state"], "ready")
        self.assertTrue(any(a.get("owner") == "controller" for a in plan["actions"]))
        receipt = self.record()
        self.assertEqual(self.ctl("next-action")["state"], "ready")
        for filename in ("output.log", "artifact-0"):
            path = (self.evidence / receipt).parent / filename
            saved = path.read_bytes()
            for delete in (False, True):
                if delete:
                    path.unlink()
                else:
                    path.write_text("damaged evidence")
                plan = self.ctl("next-action")
                self.assertNotEqual(plan["state"], "ready")
                self.assertTrue(plan["actions"])
                path.write_bytes(saved)
        (self.evidence / receipt).parent.joinpath("output.log").write_text("altered output")
        self.assertNotEqual(self.ctl("next-action")["state"], "ready")
        self.product.write_text("bad newest attempt")
        self.record(1)
        self.assertEqual(self.ctl("next-action")["action"], "repair")
        latest = json.loads((self.evidence / "gate-operation.json").read_text())
        path = self.evidence / latest / "run.json"
        data = json.loads(path.read_text())
        data.update(status="running", exit_code=None)
        path.write_text(json.dumps(data))
        self.assertEqual(self.ctl("next-action")["action"], "wait")
        data.update(status="interrupted", exit_code=143)
        path.write_text(json.dumps(data))
        self.assertNotEqual(self.ctl("next-action")["state"], "ready")

    def test_new_code_review_leaves_unrelated_later_gates_pending(self):
        self.assertEqual(self.ctl("next-action")["state"], "ready")
        self.assertEqual(self.ctl("code-review")["action"], "start")
        self.assertEqual(self.ctl("next-action", target="final")["state"], "needs_checks")


class BehaviorEvidenceTests(FlightFixture):
    def test_green_suite_without_case_witness_cannot_approve(self):
        self.complete_behavior([self.case(), self.case("second-case", ["case.b"])])
        self.assertTrue(self.ctl("review")["ready_for_review"])
        self.product.write_text("only-a")
        self.record()
        packet = self.ctl("review", 1)
        self.assertEqual(packet["checks"][0]["status"], "passed")
        self.assertIn("acceptance-case:second-case", packet["blockers"])
        self.assertFalse(self.ctl("verdict", 1, review=self.native_review())["ready_for_approval"])
        for mode in ("skipped", "expected_failures"):
            self.product.write_text(mode)
            self.record()
            self.assertIn("acceptance-case:second-case", self.ctl("review", 1)["blockers"])
        policy = FlightFixture()
        policy.setUp()
        self.addCleanup(policy.doCleanups)
        policy.gate.pop("coverage")
        policy.task["acceptance"][0]["proofs"][0].pop("tests")
        policy.amend()
        policy.record()
        self.assertTrue(policy.ctl("review")["ready_for_review"])

    def test_native_coverage_requires_test_identities(self):
        before = (self.evidence / "acceptance-contract.json").read_bytes()
        self.task["acceptance"][0]["proofs"][0].pop("tests")
        self.amend(2)
        self.assertEqual((self.evidence / "acceptance-contract.json").read_bytes(), before)

    def test_behavior_cannot_be_declared_without_observable_cases(self):
        self.task["acceptance"][0]["kind"] = "behavior"
        self.amend(2)
        self.task["acceptance"][0]["cases"] = [dict(self.case(), observable="")]
        self.amend(2)

    def test_actual_case_disposition_is_required_after_passing_witnesses(self):
        self.complete_behavior()
        self.assertTrue(self.ctl("review")["ready_for_review"])
        verdict = self.ctl("verdict", 1, review=self.native_review(case_assessments=[]))
        self.assertIn("independent behavior-case assessments", verdict["blockers"])
        self.assertTrue(self.ctl("verdict", review=self.native_review())["ready_for_approval"])


class ChallengePlanTests(FlightFixture):
    def test_independent_challenges_require_current_executed_witnesses(self):
        self.product.write_text("bad")
        before = self.record(1)
        self.product.write_text("good")
        self.task["candidate"] = "B"
        self.record()
        self.enable_behavior()
        self.task["case_controls"] = {key: self.control(before) for key in ["first-case", "independent-case"]}
        packet = self.ctl("review", 1)
        self.assertIn("challenge-case:independent-case", packet["blockers"])
        row = next(c for c in packet["behavior_evidence"]["cases"] if c["id"] == "independent-case")
        self.assertIn("predates", row["reason"])
        self.record()
        self.assertTrue(self.ctl("verdict", review=self.native_review())["ready_for_approval"])
        del self.task["challenge_checks"]["independent-case"]
        self.assertIn("challenge-case:independent-case", self.ctl("review", 1)["blockers"])
        self.task["challenge_checks"]["independent-case"] = {"gate": self.gate["id"], "tests": ["case.a"]}
        plan_path = self.evidence / "challenge-plan.json"
        saved = plan_path.read_bytes()
        plan_path.unlink()
        self.assertIn("independent challenge plan", self.ctl("review", 1)["blockers"])
        self.task["worker_handoff"] = "All challenge cases passed"
        self.assertFalse(self.ctl("review", 1)["ready_for_review"])
        plan_path.write_bytes(saved)
        pointer = self.evidence / "gate-operation.json"
        prior = pointer.read_bytes()
        pointer.unlink()
        self.assertIn("challenge-case:independent-case", self.ctl("review", 1)["blockers"])
        pointer.write_bytes(prior)
        self.task["candidate"] = "C"
        self.product.write_text("good changed relevant inputs")
        self.assertIn("challenge-case:independent-case", self.ctl("review", 1)["blockers"])
        self.record()
        self.assertTrue(self.ctl("review")["ready_for_review"])

    def test_challenge_brief_excludes_implementation_story(self):
        self.task.update(diff="private implementation", findings=["success narrative"],
                         decisions=["prior verdict"], worker_handoff="worker notes")
        brief = self.ctl("challenge-brief")
        fields = {"scope", "acceptance", "scope_sha256"}
        if "schemas" in brief:
            fields.update(("schemas", "examples", "schema_guide", "grounding", "proposal_status"))
            self.assertEqual(brief["schemas"]["challenge"]["properties"]["cases"]["type"], "array")
        self.assertEqual(set(brief), fields)
        self.assertEqual(brief["acceptance"], [{"id": "operation",
                                               "description": self.task["acceptance"][0]["description"]}])
        self.assertNotIn("private implementation", json.dumps(brief))
        self.assertNotIn("probe.py", json.dumps(brief))

    def test_restart_preserves_omitted_cases_and_rejects_changed_or_foreign_plans(self):
        self.complete_behavior()
        proposal = self.proposal()
        extra = dict(proposal["cases"][0], id="second-independent")
        proposal["cases"].append(extra)
        self.submit_plan(proposal)
        self.submit_plan(self.proposal())
        state = json.loads((self.evidence / "challenge-plan.json").read_text())
        self.assertEqual(set(state["cases"]), {"independent-case", "second-independent"})
        self.assertIn("challenge-case:second-independent", self.ctl("review", 1)["blockers"])
        saved = (self.evidence / "challenge-plan.json").read_bytes()
        changed = self.proposal()
        changed["cases"][0]["expected"] = "weaker expectation"
        self.submit_plan(changed, 2)
        changed = self.proposal()
        changed["scope_sha256"] = "0" * 64
        self.submit_plan(changed, 2)
        self.assertEqual((self.evidence / "challenge-plan.json").read_bytes(), saved)


class QualificationTests(FlightFixture):
    def test_invalid_receipts_preserve_existing_review_guards(self):
        self.record()
        request = {"id": "timed-request", "criterion": "operation", "input": "first result",
                   "expected": "valid first result", "reason": "Actual post-request witness required"}
        self.ctl("requests", review=self.native_review("CODE", "REVISE", requests=[request]))
        self.task["request_checks"] = {"timed-request": {"gate": "operation", "tests": ["case.a"],
                                                         "assertion": "The first public result"}}
        self.assertFalse(self.ctl("review", 1)["ready_for_review"])
        self.record(owner="worker")
        self.assertFalse(self.ctl("review", 1)["ready_for_review"])
        receipt = self.record()
        self.assertTrue(self.ctl("review")["ready_for_review"])
        (self.evidence / receipt).parent.joinpath("output.log").write_text("damaged output")
        self.assertFalse(self.ctl("review", 1)["ready_for_review"])
        self.product.write_text("bad newest result")
        self.record(1)
        self.assertFalse(self.ctl("review", 1)["ready_for_review"])
        latest = self.evidence / json.loads((self.evidence / "gate-operation.json").read_text()) / "run.json"
        data = json.loads(latest.read_text())
        data.update(status="running", exit_code=None)
        latest.write_text(json.dumps(data))
        self.assertFalse(self.ctl("review", 1)["ready_for_review"])

    def test_control_detects_wrong_expectation_and_insensitive_check(self):
        before = self.complete_behavior()
        self.assertTrue(self.ctl("review")["ready_for_review"])
        healthy = self.record()
        self.task["case_controls"]["first-case"] = self.control(healthy, candidate="B")
        # A passing old/control run cannot establish negative sensitivity.
        self.assertIn("acceptance-case:first-case", self.ctl("review", 1)["blockers"])
        self.product.write_text("bad violating result")
        self.record(1)
        self.assertFalse(self.ctl("review", 1)["ready_for_review"])
        # An oracle that ignores the violating product passes its negative control
        # and must not qualify as regression evidence, even on the original identity.
        original_oracle = self.producer.read_text()
        self.producer.write_text(original_oracle.replace("bad=mode.startswith('bad')", "bad=False"))
        self.product.write_text("bad violating result ignored by oracle")
        self.task["candidate"] = "A"
        insensitive = self.record()
        self.task["case_controls"]["first-case"] = self.control(insensitive)
        self.task["candidate"] = "B"
        self.record()
        self.assertIn("acceptance-case:first-case", self.ctl("review", 1)["blockers"])
        self.producer.write_text(original_oracle)
        self.product.write_text("good")
        self.task["case_controls"]["first-case"] = self.control(before)
        self.fixture.write_text('{"contract":"weakened fixture"}\n')
        self.record()
        self.assertIn("acceptance-case:first-case", self.ctl("review", 1)["blockers"])

    def test_compatibility_requires_a_passing_baseline(self):
        positive = self.record()
        self.complete_behavior([self.case(kind="compatibility")])
        self.assertIn("acceptance-case:first-case", self.ctl("review", 1)["blockers"])
        self.task["case_controls"]["first-case"] = self.control(positive)
        self.assertTrue(self.ctl("review")["ready_for_review"])
        self.product.write_text("bad compatibility violation")
        self.record(1)
        self.assertFalse(self.ctl("review", 1)["ready_for_review"])
        self.product.write_text("good")
        self.record()
        self.assertTrue(self.ctl("review")["ready_for_review"])
        requirement = self.task["acceptance"][0]["cases"][0]
        requirement["expectation"] = {"kind": "specification", "reference": "New owner contract, not historical preservation"}
        self.amend()
        self.task["candidate"] = "violating-control"
        self.product.write_text("bad specified behavior")
        negative = self.record(1)
        self.task["case_controls"]["first-case"] = self.control(negative, candidate="violating-control", source="mutation")
        self.task["candidate"] = "B"
        self.product.write_text("good")
        self.record()
        self.assertTrue(self.ctl("review")["ready_for_review"])
        requirement["expectation"]["kind"] = "unsupported-prose"
        self.amend(2)

    def test_current_pass_cannot_be_relabeled_as_the_original_baseline(self):
        self.complete_behavior([self.case(kind="compatibility")])
        positive = self.record()
        self.task["case_controls"]["first-case"] = self.control(positive, candidate="B")
        self.assertIn("acceptance-case:first-case", self.ctl("review", 1)["blockers"])

    def test_exact_identities_and_ordering_preserve_existing_coverage_guards(self):
        self.record()
        self.assertTrue(self.ctl("review")["ready_for_review"])
        for mode in ("similar", "duplicate", "malformed"):
            self.product.write_text(mode)
            self.record()
            self.assertFalse(self.ctl("review", 1)["ready_for_review"])
        self.product.write_text("reordered")
        self.record()
        self.assertTrue(self.ctl("review")["ready_for_review"])
        self.product.write_text("members-reordered")
        receipt = self.record()
        self.assertTrue(self.ctl("review")["ready_for_review"])
        artifact = (self.evidence / receipt).parent / "artifact-0"
        artifact.write_text(artifact.read_text() + " ")
        self.assertFalse(self.ctl("review", 1)["ready_for_review"])
        # Exact matching also applies to distinct parameterized identities.
        source = self.producer.read_text().replace("case.a", "public[one]").replace("case.b", "public[two]")
        self.producer.write_text(source)
        self.task["acceptance"][0]["proofs"][0]["tests"] = ["public[one]", "public[two]"]
        self.amend()
        self.record()
        self.assertTrue(self.ctl("review")["ready_for_review"])
        self.task["acceptance"][0]["proofs"][0]["tests"] = ["public[one-similar]"]
        self.amend()
        self.assertFalse(self.ctl("review", 1)["ready_for_review"])

    def test_two_projects_preserve_selection_and_frozen_gate_contracts(self):
        self.record()
        self.assertTrue(self.ctl("review")["ready_for_review"])
        # The same public interfaces accept a separately named project contract.
        self.task["scope"] = "A different project with a different command name"
        self.gate["id"] = "other-project-check"
        self.task["acceptance"][0]["proofs"][0]["gate"] = self.gate["id"]
        self.amend()
        self.record()
        self.assertTrue(self.ctl("review")["ready_for_review"])
        self.request["scope"] = "silently reduced gate"
        self.assertIn("acceptance contract", self.ctl("review", 1)["blockers"])
        example = SCRIPTS.parent
        self.assertIn("when the owner explicitly selects", (example / "AGENTS.md").read_text())
        self.assertEqual(json.loads((example / ".codex/hooks.json").read_text())["hooks"], {})
        self.assertEqual((example / "AGENTS.md").read_text().count("when the owner explicitly selects"), 1)
        # A second project really supplies a different command and identity format.
        other = FlightFixture()
        other.setUp()
        self.addCleanup(other.doCleanups)
        other.producer.write_text(other.producer.read_text().replace("case.a", "operation::first").replace("case.b", "operation::second"))
        other.request["scope"] = "other independently configured native project"
        other.gate["id"] = "second-project"
        other.task["scope"] = "Another selected project"
        other.task["acceptance"][0]["proofs"][0].update(gate="second-project", tests=["operation::first", "operation::second"])
        other.amend()
        other.record()
        self.assertNotEqual(self.request["command"], other.request["command"])
        self.assertNotEqual(self.checkout, other.checkout)
        self.assertTrue(other.ctl("review")["ready_for_review"])
        other.task["gates"] = []
        self.assertIn("acceptance contract", other.ctl("review", 1)["blockers"])


class FindingDispositionTests(FlightFixture):
    def test_withdrawal_needs_control_evidence_and_independent_acknowledgment(self):
        self.false_claim()
        original = (self.evidence / "review-obligations.json").read_bytes()
        self.task["withdrawal_proposals"] = {"functional-finding:false-claim": {"assertion": "implementer says false"}}
        self.assertEqual(self.ctl("disposition-review", 1)["action"], "blocked")
        self.ctl("requests", 2, review=self.native_review("CODE", withdrawals=[{
            "kind": "functional-finding", "id": "false-claim", "proposal_sha256": "0" * 64,
            "reason": "Unsupported assertion"}]))
        self.assertEqual((self.evidence / "review-obligations.json").read_bytes(), original)
        receipt = self.record()
        self.task["withdrawal_proposals"] = {
            "functional-finding:false-claim": self.refutation("functional-finding", "false-claim", receipt),
            "test-request:linked-request": self.refutation("test-request", "linked-request", receipt)}
        self.assertEqual(self.ctl("next-action")["action"], "review_disposition")
        self.assertFalse(self.ctl("review", 1)["ready_for_review"])
        rows = self.acknowledgments()
        self.ctl("requests", review=self.native_review("CODE", phase="disposition", withdrawals=rows))
        self.assertTrue(self.ctl("review")["ready_for_review"])
        bounded = self.native_review(phase="disposition", withdrawals=rows)
        self.assertIn("full independent final review", self.ctl("verdict", 1, review=bounded)["blockers"])
        self.assertTrue(self.ctl("verdict", review=self.native_review())["ready_for_approval"])

    def test_withdrawal_preserves_original_request_spec(self):
        original = self.false_claim(unrelated=True)
        review_hash = original["findings"]["false-claim"]["review_sha256"]
        original_review = (self.evidence / "reviews" / (review_hash + ".json")).read_bytes()
        receipt = self.record()
        self.task["withdrawal_proposals"] = {
            "functional-finding:false-claim": self.refutation("functional-finding", "false-claim", receipt),
            "test-request:linked-request": self.refutation("test-request", "linked-request", receipt)}
        rows = self.acknowledgments()
        self.ctl("requests", review=self.native_review("CODE", phase="disposition", withdrawals=rows))
        state = json.loads((self.evidence / "review-obligations.json").read_text())
        self.assertEqual(state["requests"], original["requests"])
        self.assertEqual(state["findings"], original["findings"])
        self.assertEqual((self.evidence / "reviews" / (review_hash + ".json")).read_bytes(), original_review)
        packet = self.ctl("review", 1)
        self.assertIn("test-request:unrelated-request", packet["blockers"])
        self.assertNotIn("regression:false-claim", packet["blockers"])

    def test_wrong_source_scope_owner_or_acknowledgment_cannot_withdraw(self):
        self.false_claim()
        receipt = self.record()
        valid = self.refutation("functional-finding", "false-claim", receipt)
        for field in ("scope_sha256", "original_sha256"):
            self.task["withdrawal_proposals"] = {"functional-finding:false-claim": dict(valid, **{field: "0" * 64})}
            self.assertEqual(self.ctl("disposition-review", 1)["action"], "blocked")
        self.task["withdrawal_proposals"] = {"functional-finding:false-claim": valid}
        rows = self.acknowledgments()
        self.task["withdrawal_proposals"]["functional-finding:unknown"] = valid
        self.assertEqual(self.ctl("disposition-review", 1)["action"], "blocked")
        del self.task["withdrawal_proposals"]["functional-finding:unknown"]
        state_path = self.evidence / "review-obligations.json"
        saved = state_path.read_bytes()
        state = json.loads(saved)
        state["findings"]["false-claim"]["spec"]["impact"] = "edited original claim"
        state_path.write_text(json.dumps(state))
        self.assertEqual(self.ctl("disposition-review", 1)["action"], "blocked")
        state_path.write_bytes(saved)
        rows[0]["proposal_sha256"] = "0" * 64
        self.ctl("requests", 2, review=self.native_review("CODE", phase="disposition", withdrawals=rows))
        self.task["candidate"] = "B"
        self.product.write_text("good other source")
        other = self.record()
        self.task["withdrawal_proposals"]["functional-finding:false-claim"] = dict(valid, receipt=other)
        self.assertEqual(self.ctl("disposition-review", 1)["action"], "blocked")
        self.task["candidate"] = "A"
        self.product.write_text("good")
        worker = self.record(owner="worker")
        self.task["withdrawal_proposals"]["functional-finding:false-claim"] = dict(valid, receipt=worker)
        self.assertEqual(self.ctl("disposition-review", 1)["action"], "blocked")

    def test_damaged_withdrawal_evidence_reopens_the_blocker(self):
        self.false_claim()
        receipt = self.record()
        self.task["withdrawal_proposals"] = {
            "functional-finding:false-claim": self.refutation("functional-finding", "false-claim", receipt),
            "test-request:linked-request": self.refutation("test-request", "linked-request", receipt)}
        self.ctl("requests", review=self.native_review("CODE", phase="disposition", withdrawals=self.acknowledgments()))
        self.task["candidate"] = "B"
        self.product.write_text("good B")
        self.record()
        self.assertTrue(self.ctl("review")["ready_for_review"])
        (self.evidence / receipt).parent.joinpath("output.log").write_text("changed counterevidence")
        packet = self.ctl("review", 1)
        self.assertEqual(packet["checks"][0]["status"], "passed")
        self.assertIn("withdrawal-evidence:functional-finding:false-claim", packet["blockers"])
        self.assertTrue(any(a["action"] == "repair_evidence" for a in self.ctl("next-action")["actions"]))

    def test_idempotent_acknowledgment_and_explicit_revision_retain_history(self):
        self.false_claim()
        receipt = self.record()
        self.task["withdrawal_proposals"] = {
            "functional-finding:false-claim": self.refutation("functional-finding", "false-claim", receipt)}
        rows = self.acknowledgments()
        native = self.native_review("CODE", phase="disposition", withdrawals=rows)
        self.ctl("requests", review=native)
        old = json.loads((self.evidence / "review-obligations.json").read_text())
        self.ctl("requests", review=native)
        self.assertEqual(json.loads((self.evidence / "review-obligations.json").read_text()), old)
        self.task["withdrawal_proposals"]["functional-finding:false-claim"]["reference"] = "More precise documented reference"
        changed = self.acknowledgments()
        self.ctl("requests", 2, review=self.native_review("CODE", phase="disposition", withdrawals=changed))
        saved = old["withdrawals"]["functional-finding:false-claim"]
        changed[0]["supersedes"] = hashlib.sha256(json.dumps(saved, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.ctl("requests", review=self.native_review("CODE", phase="disposition", withdrawals=changed))
        current = json.loads((self.evidence / "review-obligations.json").read_text())
        self.assertEqual(current["withdrawal_history"][0]["value"], saved)
        self.assertEqual(current["findings"], old["findings"])

    def test_challenge_withdrawal_retains_the_original_plan_and_acceptance(self):
        self.enable_behavior()
        original = (self.evidence / "challenge-plan.json").read_bytes()
        receipt = self.record()
        self.task["withdrawal_proposals"] = {
            "challenge-case:independent-case": self.refutation("challenge-case", "independent-case", receipt)}
        self.ctl("requests", review=self.native_review("EVIDENCE", phase="disposition", withdrawals=self.acknowledgments()))
        self.assertEqual((self.evidence / "challenge-plan.json").read_bytes(), original)
        packet = self.ctl("review", 1)
        row = next(c for c in packet["behavior_evidence"]["cases"] if c["id"] == "independent-case")
        self.assertTrue(row["withdrawn"])
        # Independent challenge withdrawal cannot waive the owner's required case.
        self.assertIn("acceptance-case:first-case", packet["blockers"])


class FinalPhaseTests(FlightFixture):
    def test_explicit_nonfinal_review_never_authorizes_landing(self):
        self.record()
        self.assertTrue(self.ctl("verdict", review=self.native_review(phase="final"))["ready_for_approval"])
        for phase in ("code", "disposition"):
            verdict = self.ctl("verdict", 1, review=self.native_review(phase=phase))
            self.assertIn("full independent final review", verdict["blockers"])


if __name__ == "__main__":
    unittest.main()
