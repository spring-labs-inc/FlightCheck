"""Independent contract probes for the synthetic evidence-inspection track.

All inline evidence and answer keys below are invented calibration data.  The
real preserved-history originals and frozen oracles are deliberately absent.
"""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "benchmarks/evidence_inspection.py"
MANIFEST = ROOT / "benchmarks/evidence-inspection-v1.json"
BASELINE = "ee869f9a3c03c8c048ad778d7465d9c31e70f970"
INCREMENTAL = "c69bbfe364ac01c9a13b46cb983f0c4ffd2c5e33"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


class EvidenceInspectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("inspection_contract", CLI)
        cls.inspection = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.inspection)
        cls.suite = cls.inspection.load_suite(MANIFEST)
        cls.scratch = tempfile.TemporaryDirectory(prefix="inspection-tests-")
        cls.addClassCleanup(cls.scratch.cleanup)
        cls.scratch_path = Path(cls.scratch.name).resolve()
        cls.runtime_results = {}

    def native(self, *arguments, success=True):
        result = subprocess.run([sys.executable, "-B", str(CLI), *map(str, arguments)],
                                cwd=ROOT, capture_output=True, text=True, timeout=90)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def runtime(self, pin):
        if pin not in self.runtime_results:
            self.runtime_results[pin] = self.inspection.exercise_runtime(
                ROOT, pin, self.scratch_path / pin[:7])
        return self.runtime_results[pin]

    def rejected(self, function, *arguments, **keywords):
        with self.assertRaises((ValueError, OSError, KeyError, TypeError)):
            function(*arguments, **keywords)

    def review(self, *, verdict="BLOCK", findings=None):
        return {"verdict": verdict, "findings": findings or [],
                "native_output": "Synthetic test-authored response; no model was invoked.",
                "matcher": "structured-exact-v1"}

    def oracle(self):
        return {"clean": False, "defects": [{
            "id": "synthetic-missing-row", "claim": "synthetic-membership",
            "category": "synthetic-behavior", "references": ["synthetic-output"],
            "discrepancy": "Expected rows 2 and 4; observed only row 2.",
            "repair": "Preserve row 4 when applying the second predicate.",
            "critical": True}]}

    def finding(self):
        defect = self.oracle()["defects"][0]
        return {key: copy.deepcopy(defect[key]) for key in
                ("claim", "category", "references", "discrepancy", "repair")} | {
                    "narrative": "Synthetic behavior differs at the stated row."}

    def test_comparison(self):
        self.assertEqual(self.inspection.BASELINE_PIN, BASELINE)
        self.assertEqual(self.inspection.INCREMENTAL_PIN, INCREMENTAL)
        self.assertEqual([row["stage"] for row in self.suite["schedule"]], ["CODE", "FINAL"])
        self.assertTrue(self.suite["schedule"][1]["independent"])

        for change in ("omit-final", "non-independent-final", "substitute-helper"):
            with self.subTest(change=change):
                malformed = copy.deepcopy(self.suite)
                if change == "omit-final":
                    malformed["schedule"].pop()
                elif change == "non-independent-final":
                    malformed["schedule"][1]["independent"] = False
                else:
                    malformed["conditions"][0]["pin"] = INCREMENTAL
                self.rejected(self.inspection.validate_suite, malformed)

        identities = []
        for pin in (BASELINE, INCREMENTAL):
            with self.subTest(pin=pin):
                observed = self.runtime(pin)
                self.assertEqual(observed["pin"], pin)
                self.assertTrue(observed["synthetic"])
                files = observed["identity"]["files"]
                by_path = {row["path"]: row["sha256"] for row in files}
                self.assertIn("workflow/scripts/handoff.py", by_path)
                self.assertIn("workflow/scripts/proof.py", by_path)
                for path, actual in by_path.items():
                    original = subprocess.check_output(
                        ["git", "show", pin + ":" + path], cwd=ROOT)
                    self.assertEqual(actual, sha(original), path)
                identities.append(by_path["workflow/scripts/proof.py"])
                self.assertEqual([row["stage"] for row in observed["schedule"]], ["CODE", "FINAL"])
                self.assertTrue(observed["schedule"][1]["independent"])
                self.assertGreater(len(observed["calls"]), 5)
        # The two actual proof helpers differ, independently of display labels.
        self.assertNotEqual(*identities)

    def test_semantics(self):
        # Execute the public invented products against independently specified
        # boundary observations; differing case names cannot make this pass.
        products = {}
        for case_id in ("c01", "c03", "c04", "c05"):
            case = next(item for item in self.suite["cases"] if item["id"] == case_id)
            source = next(item["content"] for item in case["artifacts"] if item["path"] == "source.txt")
            namespace = {}
            exec(compile(source, "synthetic-" + case_id, "exec"), namespace)
            products[case_id] = namespace
        self.assertEqual(products["c01"]["transform"]("\ufeffx"), "x")
        self.assertNotEqual(products["c03"]["transform"]("\ufeffx"), "x")
        self.assertFalse(products["c04"]["allowed"](b"a\0", False))
        self.assertTrue(products["c04"]["allowed"](b"a\0", True))
        self.assertTrue(products["c05"]["buffered"](True, False))
        self.assertFalse(products["c05"]["buffered"](True, True))
        sensitive = lambda product: product["transform"]("\ufeffx") == "x"
        insensitive = lambda product: bool(product["transform"]("\ufeffx"))
        for assertion, expected in ((sensitive, True), (insensitive, False)):
            self.assertIs(self.inspection.proof_sensitive({
                "defect_present_passed": assertion(products["c03"]),
                "repair_passed": assertion(products["c01"]),
                "same_assertion_sha256": True}), expected)

        # An independent expected row set is the oracle; verdict words alone
        # cannot establish either discovery or an actionable repair.
        oracle = self.oracle()
        precise = self.inspection.score_decision(oracle, self.review(findings=[self.finding()]))
        self.assertEqual(precise["specific_detected"], 1)
        self.assertEqual(precise["actionable_repairs"], 1)
        self.assertEqual(precise["false_alarms"], 0)
        self.assertFalse(precise["critical_false_approval"])

        generic = self.inspection.score_decision(oracle, self.review())
        self.assertEqual(generic["specific_detected"], 0)
        self.assertEqual(generic["actionable_repairs"], 0)
        self.assertFalse(generic["quality_pass"])

        no_repair = self.finding()
        no_repair["repair"] = ""
        detected = self.inspection.score_decision(oracle, self.review(findings=[no_repair]))
        self.assertEqual(detected["specific_detected"], 1)
        self.assertEqual(detected["actionable_repairs"], 0)

        for field, unrelated in (("claim", "different-claim"),
                                 ("category", "different-behavior"),
                                 ("references", ["different-output"]),
                                 ("discrepancy", "Please investigate the result.")):
            with self.subTest(mismatched=field):
                finding = self.finding()
                finding[field] = unrelated
                scored = self.inspection.score_decision(oracle, self.review(findings=[finding]))
                self.assertEqual(scored["specific_detected"], 0)
                self.assertEqual(scored["actionable_repairs"], 0)
                self.assertGreaterEqual(scored["false_alarms"], 1)

        copied = self.finding()
        copied["discrepancy"] = "The check passed; the proof might be incomplete."
        copied["repair"] = "Run more tests."
        scored = self.inspection.score_decision(oracle, self.review(findings=[copied]))
        self.assertEqual(scored["specific_detected"], 0)
        self.assertEqual(scored["actionable_repairs"], 0)

        # A deliberately insensitive assertion (nonempty output) passes both
        # products. It cannot override the exact independent expected rows.
        original_rows, repaired_rows = [2], [2, 4]
        self.assertTrue(original_rows and repaired_rows)
        self.assertNotEqual(original_rows, [2, 4])
        approved = self.inspection.score_decision(oracle, self.review(verdict="APPROVE"))
        self.assertTrue(approved["critical_false_approval"])
        self.assertFalse(approved["quality_pass"])
        self.assertTrue(approved["semantic_audit_required"])

        clean = {"clean": True, "defects": []}
        self.assertTrue(self.inspection.score_decision(
            clean, self.review(verdict="APPROVE"))["quality_pass"])
        alarm = self.inspection.score_decision(clean, self.review(findings=[self.finding()]))
        self.assertEqual(alarm["specific_detected"], 0)
        self.assertEqual(alarm["false_alarms"], 1)
        self.assertFalse(alarm["quality_pass"])

        duplicate = self.inspection.score_decision(
            oracle, self.review(findings=[self.finding(), self.finding()]))
        self.assertEqual(duplicate["specific_detected"], 1)
        self.assertEqual(duplicate["actionable_repairs"], 1)

        for defect_passed, repaired_passed, same, expected in (
                (False, True, True, True), (True, True, True, False),
                (False, False, True, False), (False, True, False, False)):
            with self.subTest(defect_passed=defect_passed, repaired_passed=repaired_passed, same=same):
                self.assertIs(self.inspection.proof_sensitive({
                    "defect_present_passed": defect_passed,
                    "repair_passed": repaired_passed,
                    "same_assertion_sha256": same}), expected)

    def attempt(self, name, interval, *, status="completed", session=None):
        return {"id": name, "status": status, "role": "CODE", "session": session or name,
                "active_intervals": [interval], "wall_interval": interval,
                "buckets": {key: [] for key in (
                    "setup", "view_preparation", "supervision", "provider_wait", "queue_wait",
                    "tool_wait", "repair", "rerun")},
                "tool_calls": 2, "requests": 1, "tokens": 30, "quota": 4, "presented_bytes": 100}

    def event(self, offset, size, *, phase="inspection", artifact=None):
        return {"schema": "evidence-inspection-v1", "kind": "read-event", "phase": phase,
                "artifact_sha256": artifact or sha(b"invented-0123456789"),
                "offset": offset, "bytes": size}

    def test_accounting(self):
        attempts = [self.attempt("a", [0, 10]), self.attempt("b", [5, 15])]
        attempts[0]["active_intervals"] = [[0, 5], [3, 10]]
        attempts[0]["buckets"]["provider_wait"] = [[8, 11], [10, 12]]
        attempts[1]["buckets"]["repair"] = [[5, 7]]
        reads = [self.event(0, 5), self.event(3, 5), self.event(0, 5),
                 self.event(0, 2, phase="probe")]
        account = self.inspection.account(attempts, reads)
        self.assertEqual(account["attempt_count"], 2)
        self.assertEqual(account["session_launches"], 2)
        self.assertEqual([a["active_seconds"] for a in account["attempts"]], [10, 10])
        self.assertEqual(account["session_active_seconds"], 20)
        self.assertEqual(account["active_critical_path_seconds"], 15)
        self.assertEqual(account["critical_path_elapsed_seconds"], 15)
        self.assertEqual(account["buckets"]["provider_wait"], 4)
        self.assertEqual(account["buckets"]["repair"], 2)
        self.assertEqual(account["buckets"]["rerun"], 0)
        self.assertEqual(account["tool_calls"], 4)
        self.assertEqual(account["requests"], 2)
        self.assertEqual(account["tokens"], 60)
        self.assertEqual(account["quota"], 8)
        self.assertEqual(account["presented_bytes"], 200)
        self.assertEqual(account["read_calls"], 3)
        self.assertEqual(account["read_bytes"], 15)
        self.assertEqual(account["unique_read_bytes"], 8)
        self.assertEqual(account["repeat_read_bytes"], 7)
        self.assertEqual(account["probe_bytes"], 2)

        interrupted = self.attempt("c", [20, 21], status="interrupted")
        for key in ("tokens", "quota", "tool_calls", "requests", "active_intervals", "wall_interval"):
            interrupted[key] = None
        interrupted["buckets"]["tool_wait"] = None
        interrupted["presented_bytes"] = None
        unknown = self.inspection.account(attempts + [interrupted], None)
        self.assertEqual(unknown["attempt_count"], 3)
        self.assertEqual(unknown["attempts"][-1]["status"], "interrupted")
        for key in ("tokens", "quota", "tool_calls", "requests", "session_active_seconds",
                    "active_critical_path_seconds", "critical_path_elapsed_seconds", "presented_bytes",
                    "read_calls", "read_bytes", "unique_read_bytes", "repeat_read_bytes", "probe_bytes"):
            with self.subTest(unknown=key):
                self.assertIsNone(unknown[key])
        self.assertIsNone(unknown["buckets"]["tool_wait"])
        self.assertEqual(unknown["buckets"]["provider_wait"], 4)

        # Disjoint intervals must not silently become the enclosing span.
        gaps = self.inspection.account([self.attempt("g1", [0, 2]),
                                        self.attempt("g2", [5, 7])], [])
        self.assertEqual(gaps["critical_path_elapsed_seconds"], 4)
        self.assertEqual(gaps["read_bytes"], 0)
        same_session = self.inspection.account([self.attempt("s1", [0, 2], session="shared"),
                                                self.attempt("s2", [3, 4], session="shared")], [])
        self.assertEqual(same_session["session_launches"], 1)
        reused_session = [self.attempt("r1", [0, 2], session="same-actual-session"),
                          self.attempt("r2", [3, 4], session="same-actual-session")]
        reused_session[1]["role"] = "EVIDENCE"
        self.assertEqual(self.inspection.account(reused_session, [])["session_launches"], 1)
        with self.subTest(shared_session_overlap=True):
            overlapping = [self.attempt("overlap-first", [0, 10], status="failed", session="resumed-session"),
                           self.attempt("overlap-resume", [5, 15], session="resumed-session"),
                           self.attempt("other-session", [3, 7], session="independent-session")]
            overlapping[2]["role"] = "EVIDENCE"
            overlapping[0]["buckets"]["provider_wait"] = [[5, 8]]
            overlapping[1]["buckets"]["provider_wait"] = [[5, 8]]
            overlapping[2]["buckets"]["provider_wait"] = [[6, 9]]
            measured = self.inspection.account(overlapping, [])
            self.assertEqual(measured["attempt_count"], 3)
            self.assertEqual(measured["session_launches"], 2)
            self.assertEqual([row["active_seconds"] for row in measured["attempts"]], [10, 10, 4])
            self.assertEqual([row["status"] for row in measured["attempts"]], ["failed", "completed", "completed"])
            self.assertEqual(measured["session_active_seconds"], 19)
            self.assertEqual(measured["active_critical_path_seconds"], 15)
            self.assertEqual([row["buckets"]["provider_wait"] for row in measured["attempts"]], [3, 3, 3])
            # A resumed session records the same wait twice. Its three seconds
            # count once, plus three for the independent session: six total.
            # A global elapsed union would be four, from time five through nine.
            self.assertEqual(measured["buckets"]["provider_wait"], 6)
            self.assertNotEqual(measured["buckets"]["provider_wait"], 9 - 5)

        with self.subTest(shared_session_bucket_unknown=True):
            missing_wait = copy.deepcopy(overlapping)
            missing_wait[1]["buckets"]["provider_wait"] = None
            unknown_wait = self.inspection.account(missing_wait, [])
            self.assertEqual(unknown_wait["attempt_count"], 3)
            self.assertEqual(unknown_wait["session_launches"], 2)
            self.assertEqual([row["buckets"]["provider_wait"] for row in unknown_wait["attempts"]], [3, None, 3])
            self.assertIsNone(unknown_wait["buckets"]["provider_wait"])
            self.assertEqual(unknown_wait["session_active_seconds"], 19)
            self.assertEqual(unknown_wait["active_critical_path_seconds"], 15)

        for field, bad in (("tokens", -1), ("tokens", True), ("quota", float("nan")),
                           ("active_intervals", [[2, 1]])):
            with self.subTest(malformed=field, value=str(bad)):
                malformed = self.attempt("bad", [0, 1])
                malformed[field] = bad
                self.rejected(self.inspection.account, [malformed], [])
        self.rejected(self.inspection.account, [attempts[0], attempts[0]], [])
        self.rejected(self.inspection.account, attempts, [self.event(-1, 3)])
        self.rejected(self.inspection.account, attempts, [self.event(0, -1)])

        cheaper_escape = self.inspection.score_decision(
            self.oracle(), self.review(verdict="APPROVE"))
        self.assertTrue(cheaper_escape["critical_false_approval"])
        self.assertFalse(cheaper_escape["quality_pass"])
        self.assertFalse(cheaper_escape["acceptable_efficiency_claim"])

    def make_view(self, root):
        root.mkdir()
        payload = b"Synthetic reviewer evidence: 0123456789\n"
        (root / "evidence.txt").write_bytes(payload)
        view = {"schema": "evidence-inspection-v1", "kind": "reviewer-view", "case_id": "testview",
                "condition": "incremental", "candidate": "synthetic-candidate", "source_pin": INCREMENTAL,
                "created_ns": 1, "artifacts": [{"id": "allowed", "path": "evidence.txt",
                    "sha256": sha(payload), "bytes": len(payload), "necessary": True,
                    "coverage": ["synthetic-claim"]}]}
        return write_json(root / "view.json", view), view, payload

    def test_boundaries(self):
        with tempfile.TemporaryDirectory(dir=self.scratch_path) as temporary:
            outer = Path(temporary)
            view_path, original, payload = self.make_view(outer / "view")
            events = outer / "reads.jsonl"
            kwargs = {"role": "CODE", "session": "synthetic-session", "events_path": events}
            first = self.inspection.read_artifact(view_path, "allowed", offset=3, length=7, **kwargs)
            self.assertEqual(first["data"], payload[3:10])
            self.assertEqual(first["event"]["returned_sha256"], sha(payload[3:10]))
            self.assertEqual(first["event"]["bytes"], 7)
            self.inspection.read_artifact(view_path, "allowed", offset=3, length=7, **kwargs)
            records = [json.loads(row) for row in events.read_text().splitlines()]
            self.assertEqual(len(records), 2)
            self.assertTrue(all(row["phase"] == "inspection" for row in records))
            self.assertTrue(all(row["finished_ns"] >= row["started_ns"] for row in records))
            before = events.read_bytes()
            for unknown in ("oracle", "other-condition", "../allowed"):
                with self.subTest(unknown=unknown):
                    self.rejected(self.inspection.read_artifact, view_path, unknown, **kwargs)
            self.assertEqual(events.read_bytes(), before)

            for offset, length in ((-1, 2), (0, -2), (True, 2), (0, True)):
                with self.subTest(offset=offset, length=length):
                    self.rejected(self.inspection.read_artifact, view_path, "allowed",
                                  offset=offset, length=length, **kwargs)
            self.rejected(self.inspection.read_artifact, view_path, "allowed",
                          role="controller", session="s", events_path=events)
            self.rejected(self.inspection.read_artifact, view_path, "allowed",
                          role="CODE", session="s", events_path=view_path.parent / "events.jsonl")

            for unsafe in ("../outside", "/etc/hosts", "sub/../../outside", "./evidence.txt",
                           "sub//evidence.txt", "sub\\evidence.txt", "view.json"):
                with self.subTest(path=unsafe):
                    changed = copy.deepcopy(original)
                    changed["artifacts"][0]["path"] = unsafe
                    write_json(view_path, changed)
                    self.rejected(self.inspection.read_artifact, view_path, "allowed", **kwargs)
            write_json(view_path, original)
            (view_path.parent / "evidence.txt").write_bytes(b"tampered")
            self.rejected(self.inspection.read_artifact, view_path, "allowed", **kwargs)
            (view_path.parent / "evidence.txt").unlink()

            private = outer / "private-oracle"
            private.write_bytes(payload)
            (view_path.parent / "evidence.txt").symlink_to(private)
            self.rejected(self.inspection.read_artifact, view_path, "allowed", **kwargs)
            (view_path.parent / "evidence.txt").unlink()
            (view_path.parent / "evidence.txt").write_bytes(payload)
            alias = outer / "view-alias"
            alias.symlink_to(view_path.parent, target_is_directory=True)
            self.rejected(self.inspection.read_artifact, alias / "view.json", "allowed", **kwargs)
            events_alias = outer / "event-alias"
            events_alias.symlink_to(private)
            self.rejected(self.inspection.read_artifact, view_path, "allowed",
                          role="CODE", session="s", events_path=events_alias)
            self.assertEqual(private.read_bytes(), payload)

            result = self.native("read", "--view", view_path, "--artifact", "allowed", "--offset", 0,
                                 "--length", 5, "--role", "CODE", "--session", "native-read",
                                 "--events", events)
            self.assertNotIn("private-oracle", result.stdout + result.stderr)
            self.native("read", "--view", view_path, "--artifact", "oracle", "--role", "CODE",
                        "--session", "native-read", "--events", events, success=False)

        # These are parser unit fixtures, not asserted external observations.
        # Synthetic/controller reports must never satisfy the measured boundary.
        boundary = {"schema": "evidence-inspection-v1", "view_sha256": sha(b"view"),
            "session": "review-session", "observer": "external-reviewer-session", "synthetic": False,
            "observed_ns": 10, "boundary": {"read_only": True, "write_rejected": True},
            "probes": {"allowed_read": True, "oracle_denied": True, "other_condition_denied": True,
                       "write_denied": True, "necessary_access": True},
            "tools": ["synthetic-reader"], "reads_instrumented": True}
        args = (sha(b"view"), "review-session", 20)
        sufficient = self.inspection.validate_boundary(boundary, *args)
        self.assertTrue(sufficient["access_sufficient"])
        for field, value in (("synthetic", True), ("observer", "controller"),
                             ("view_sha256", sha(b"different")), ("session", "other-session"),
                             ("observed_ns", 20), ("observed_ns", 21)):
            with self.subTest(boundary=field, value=value):
                changed = copy.deepcopy(boundary)
                changed[field] = value
                self.rejected(self.inspection.validate_boundary, changed, *args)
        for probe in ("allowed_read", "oracle_denied", "other_condition_denied", "write_denied"):
            with self.subTest(probe=probe):
                changed = copy.deepcopy(boundary)
                changed["probes"][probe] = False
                self.rejected(self.inspection.validate_boundary, changed, *args)
        missing = copy.deepcopy(boundary)
        missing["probes"]["necessary_access"] = False
        self.assertFalse(self.inspection.validate_boundary(missing, *args)["access_sufficient"])
        uninstrumented = copy.deepcopy(boundary)
        uninstrumented["reads_instrumented"] = False
        self.assertFalse(self.inspection.validate_boundary(uninstrumented, *args)["telemetry_complete"])

        runtime = self.runtime(INCREMENTAL)
        actual = runtime["observations"]
        self.assertFalse(actual["necessary_missing"]["ready_for_review"])
        self.assertTrue(actual["covered_duplicate"]["ready_for_review"])
        for case in ("tampered", "new_failure"):
            with self.subTest(native_rejection=case):
                self.assertFalse(actual[case]["ready_for_review"])
        self.assertNotEqual(actual["wrong_candidate"]["exit_code"], 0)
        self.assertIn("candidate", actual["wrong_candidate"]["stderr"].lower())

        premises = []
        for case_id, private_state in (("c07", "contradiction"), ("c09", "necessary_missing"),
                                       ("c11", "tampered")):
            with self.subTest(blinded_lifecycle=case_id):
                with tempfile.TemporaryDirectory(dir=self.scratch_path) as temporary:
                    view_root = Path(temporary)
                    artifacts, _, _ = self.inspection.lifecycle_view(runtime, case_id, view_root)
                    premise_bytes = (view_root / "history-premise.json").read_bytes()
                    premises.append(premise_bytes)
                    premise = json.loads(premise_bytes)
                    self.assertEqual(set(premise), {"schema", "kind", "scripted_prior_reviews",
                                                   "real_review_observations", "meaning"})
                    self.assertTrue(premise["scripted_prior_reviews"])
                    self.assertFalse(premise["real_review_observations"])
                    self.assertNotIn(private_state.encode(), premise_bytes)
                    controller_record = Path(runtime["states"][private_state]["root"]) / "controller-state.json"
                    retained = json.loads(controller_record.read_text())
                    self.assertEqual(retained["actual_native_state"], private_state)
                    self.assertEqual(retained["case_id"], case_id)
                    self.assertNotIn(view_root, controller_record.parents)
                    self.assertFalse(any(row["path"].endswith("controller-state.json") for row in artifacts))
        self.assertEqual(premises[0], premises[1])
        self.assertEqual(premises[1], premises[2])

    def test_bounded(self):
        proposal = copy.deepcopy(self.suite["cohort_proposal"])
        checked = self.inspection.validate_cohort(proposal)
        self.assertTrue(checked["valid"])
        self.assertFalse(checked["authorized"])
        self.assertIn("not implemented", checked["execution"])
        clean = sum(case["clean"] for case in proposal["cases"])
        self.assertEqual(clean * 2, len(proposal["cases"]))
        self.assertEqual(len(proposal["order"]),
                         len(proposal["cases"]) * proposal["repetitions"] * 2)
        self.assertEqual(proposal["limits"]["sessions_per_decision"], 2)
        for field in ("source_sha256", "workflow_sha256", "evidence_sha256", "oracle_sha256",
                      "prompt_sha256", "environment_sha256", "model", "effort", "tools", "cache",
                      "endpoint", "exclusions", "order", "repetitions"):
            with self.subTest(missing=field):
                malformed = copy.deepcopy(proposal)
                malformed.pop(field)
                self.rejected(self.inspection.validate_cohort, malformed)
        for value in (0, -1, True, 1.5):
            with self.subTest(repetitions=value):
                malformed = copy.deepcopy(proposal)
                malformed["repetitions"] = value
                self.rejected(self.inspection.validate_cohort, malformed)
        for limit in proposal["limits"]:
            with self.subTest(limit=limit):
                malformed = copy.deepcopy(proposal)
                malformed["limits"][limit] = 0
                self.rejected(self.inspection.validate_cohort, malformed)
        for change in ("omit-cell", "duplicate-cell", "all-clean", "unmatched-stage", "unknown-field"):
            with self.subTest(change=change):
                malformed = copy.deepcopy(proposal)
                if change == "omit-cell":
                    malformed["order"].pop()
                elif change == "duplicate-cell":
                    malformed["order"][1] = copy.deepcopy(malformed["order"][0])
                elif change == "all-clean":
                    for case in malformed["cases"]:
                        case["clean"] = True
                elif change == "unmatched-stage":
                    malformed["schedule"].pop()
                else:
                    malformed["retry_until_green"] = True
                self.rejected(self.inspection.validate_cohort, malformed)

        # A supplied grant cannot freeze observations which are still unknown.
        # This is parser-only invented input, never actual owner authorization.
        approval = {"schema": "evidence-inspection-v1", "authority": "owner",
                    "grant": "measured-cohort", "cohort_sha256": checked["cohort_sha256"],
                    "source": "synthetic parser fixture, not actual authorization"}
        self.rejected(self.inspection.validate_cohort, proposal, approval=approval)
        self.assertTrue(any(proposal[field] is None for field in (
            "source_sha256", "workflow_sha256", "evidence_sha256", "oracle_sha256",
            "prompt_sha256", "environment_sha256")))
        self.assertTrue(any(case["private_variant_sha256"] is None for case in proposal["cases"]))
        for field in ("source_sha256", "workflow_sha256", "evidence_sha256", "oracle_sha256",
                      "prompt_sha256", "environment_sha256"):
            with self.subTest(stale_approval=field):
                changed = copy.deepcopy(proposal)
                changed[field] = sha((field + "changed").encode())
                self.rejected(self.inspection.validate_cohort, changed, approval=approval)
        wrong = dict(approval, grant="deterministic-smoke")
        self.rejected(self.inspection.validate_cohort, proposal, approval=wrong)

        attempts = [self.attempt("first", [0, 1], status="failed"),
                    self.attempt("retry", [2, 3], status="completed"),
                    self.attempt("interrupted", [4, 5], status="interrupted")]
        retained = self.inspection.account(attempts, [])
        self.assertEqual([row["status"] for row in retained["attempts"]],
                         ["failed", "completed", "interrupted"])
        self.assertEqual(retained["attempt_count"], 3)

    def import_fixture(self, outer):
        """Invented sealed source mimic, unrelated to retained private history."""
        source = outer / "original"
        source.mkdir()
        view = source / "view"
        (view / "source").mkdir(parents=True)
        entry = {"case": "invented-case", "candidate": "invented-candidate", "source_pin": INCREMENTAL,
                 "claim": "Invented query must retain both independently expected rows, two and four."}
        write_json(view / "ENTRY.json", entry)
        (view / "candidate.diff").write_text("Synthetic change adds the missing row.\n")
        (view / "source/excerpt.txt").write_text("Invented source: expected rows are two and four.\n")
        rows = [{"id": "a" + str(index), "path": path.relative_to(view).as_posix(),
                 "sha256": sha(path.read_bytes()), "bytes": path.stat().st_size,
                 "necessary": True, "coverage": ["invented-claim"]}
                for index, path in enumerate(sorted(p for p in view.rglob("*") if p.is_file()))]
        seal = write_json(source / "seal.json", {row["path"]: row["sha256"] for row in rows})
        oracle = write_json(source / "oracle.json", [{"case": "invented-case", "candidate": "invented-candidate",
                    "defect_identity": "INVENTED_EXPECTED_ROW_FOUR", "required_score": 1}])
        dependency = write_json(source / "dependency.json", {"synthetic": True, "source_only": True})
        inventory = {str(path): sha(path.read_bytes()) for path in
                     [*(view / row["path"] for row in rows), seal, oracle, dependency]}
        original_manifest = write_json(source / "manifest.json", {"files": inventory})
        bound = lambda path: {"path": str(path), "sha256": sha(path.read_bytes())}
        spec = {"schema": "evidence-inspection-v1", "kind": "historical-import",
                "lineage": {"id": "invented-lineage", "subject_pin": INCREMENTAL,
                            "limitations": ["Invented testfixture; never historical acceptance."]},
                "source_manifest": bound(original_manifest), "oracle": bound(oracle),
                "views": [{"id": "invented-case", "root": str(view), "seal": bound(seal), "files": rows}],
                "dependencies": [bound(dependency)]}
        return write_json(outer / "import.json", spec), spec

    def test_provenance(self):
        for field in self.suite:
            with self.subTest(missing_suite_field=field):
                malformed = copy.deepcopy(self.suite)
                malformed.pop(field)
                self.rejected(self.inspection.validate_suite, malformed)
        unknown = copy.deepcopy(self.suite)
        unknown["historical_approval"] = True
        self.rejected(self.inspection.validate_suite, unknown)
        with tempfile.TemporaryDirectory(dir=self.scratch_path) as temporary:
            outer = Path(temporary)
            duplicate = outer / "duplicate.json"
            duplicate.write_text('{"schema":"evidence-inspection-v1","schema":"other"}')
            self.rejected(self.inspection.load_suite, duplicate)
            nonfinite = outer / "nan.json"
            nonfinite.write_text('{"schema":NaN}')
            self.rejected(self.inspection.load_suite, nonfinite)
            spec_path, original = self.import_fixture(outer)
            imported = self.inspection.verify_import(spec_path)
            self.assertEqual(len(imported["views"]), 1)
            self.assertEqual(imported["views"][0]["candidate"], "invented-candidate")
            self.assertEqual(imported["views"][0]["source_pin"], INCREMENTAL)
            self.assertEqual(imported["spec_sha256"], sha(spec_path.read_bytes()))

            # Both IDs exist in the sealed inventory. Membership alone cannot
            # establish that a cited source location belongs to its artifact.
            selected = imported["views"][0]["files"]
            excerpt_row = next(row for row in selected if row["path"] == "source/excerpt.txt")
            unrelated_row = next(row for row in selected if row["path"] == "candidate.diff")
            derived_oracle = self.oracle()
            derived_oracle["defects"][0]["references"] = [excerpt_row["id"]]
            crosswalk = {"schema": "evidence-inspection-crosswalk-v1", "kind": "derived-private-adjudication",
                "original_oracle_sha256": original["oracle"]["sha256"], "case_id": "invented-case",
                "candidate": "invented-candidate", "oracle": derived_oracle,
                "source_references": [{"artifact_id": excerpt_row["id"], "location": excerpt_row["path"]}],
                "adjudication": {"status": "provisional", "source": "Invented source-mapping fixture; no historical or independent audit."}}
            crosswalk_path = outer / "crosswalk.json"
            for suffix in ("", ":1", ":1-1"):
                with self.subTest(valid_source_location=suffix or "exact-path"):
                    valid = copy.deepcopy(crosswalk)
                    valid["source_references"][0]["location"] += suffix
                    write_json(crosswalk_path, valid)
                    normalized = self.inspection.normalize_historical_oracle(spec_path, "invented-case", crosswalk_path)
                    self.assertEqual(normalized["oracle"], derived_oracle)
                    self.assertEqual(normalized["original_oracle_sha256"], original["oracle"]["sha256"])
                    self.assertTrue(normalized["provisional"])
                    self.assertTrue(normalized["semantic_audit_required"])
                    finding = self.finding()
                    finding["references"] = [excerpt_row["id"]]
                    scored = self.inspection.score_decision(normalized["oracle"], self.review(findings=[finding]))
                    self.assertEqual(scored["specific_detected"], 1)
                    self.assertEqual(scored["actionable_repairs"], 1)
                    self.assertFalse(scored["quality_accepted"])

            for label, artifact, location in (
                    ("existing-wrong-artifact", unrelated_row["id"], excerpt_row["path"] + ":1"),
                    ("existing-wrong-location", excerpt_row["id"], unrelated_row["path"] + ":1"),
                    ("out-of-range", excerpt_row["id"], excerpt_row["path"] + ":2"),
                    ("reversed-range", excerpt_row["id"], excerpt_row["path"] + ":2-1")):
                with self.subTest(invalid_source_binding=label):
                    invalid = copy.deepcopy(crosswalk)
                    invalid["source_references"][0] = {"artifact_id": artifact, "location": location}
                    # Keep reference membership internally consistent so the
                    # exact selected path/range guard must catch the mismatch.
                    invalid["oracle"]["defects"][0]["references"] = [artifact]
                    write_json(crosswalk_path, invalid)
                    self.rejected(self.inspection.normalize_historical_oracle, spec_path, "invented-case", crosswalk_path)

            for kind in ("wrong-pin", "wrong-candidate", "wrong-source-digest", "wrong-oracle-digest",
                         "wrong-dependency-digest", "omitted-artifact", "traversal", "extra-field"):
                with self.subTest(import_rejection=kind):
                    changed = copy.deepcopy(original)
                    if kind == "wrong-pin":
                        changed["lineage"]["subject_pin"] = BASELINE
                    elif kind == "wrong-candidate":
                        changed["views"][0]["id"] = "unrelated-case"
                    elif kind == "wrong-source-digest":
                        changed["source_manifest"]["sha256"] = sha(b"wrong-source")
                    elif kind == "wrong-oracle-digest":
                        changed["oracle"]["sha256"] = sha(b"wrong-oracle")
                    elif kind == "wrong-dependency-digest":
                        changed["dependencies"][0]["sha256"] = sha(b"wrong-dependency")
                    elif kind == "omitted-artifact":
                        changed["views"][0]["files"].pop()
                    elif kind == "traversal":
                        changed["views"][0]["files"][0]["path"] = "../oracle.json"
                    else:
                        changed["accepted"] = True
                    write_json(spec_path, changed)
                    self.rejected(self.inspection.verify_import, spec_path)
            write_json(spec_path, original)
            excerpt = Path(original["views"][0]["root"]) / "source/excerpt.txt"
            before = excerpt.read_bytes()
            excerpt.write_bytes(b"A changed original cannot keep its seal.")
            self.rejected(self.inspection.verify_import, spec_path)
            excerpt.write_bytes(before)
            oracle = Path(original["oracle"]["path"])
            excerpt.unlink()
            excerpt.symlink_to(oracle)
            self.rejected(self.inspection.verify_import, spec_path)
            excerpt.unlink()
            excerpt.write_bytes(before)

            # Unselected archive material is intentionally not traversed.
            (outer / "irrelevant-archive").symlink_to(outer / "absent")
            self.inspection.verify_import(spec_path)

            def snapshot_only(repo, pin, output):
                output.mkdir()
                runtime = output / "runtime"
                runtime.mkdir()
                return {"identity": self.inspection.snapshot_runtime(repo, pin, runtime)}

            with mock.patch.object(self.inspection, "exercise_runtime", side_effect=snapshot_only):
                prepared = self.inspection.prepare(self.suite, "invented-case", ROOT,
                    outer / "prepared", import_spec=spec_path)
            public_view = Path(prepared["view_path"]).parent
            visible = b"\n".join(p.read_bytes() for p in public_view.rglob("*") if p.is_file())
            self.assertNotIn(b"INVENTED_EXPECTED_ROW_FOUR", visible)
            self.assertNotIn(str(outer).encode(), visible)
            self.assertFalse((public_view / "oracle.json").exists())
            self.assertFalse(prepared["run"]["measured_review_observations"])
            self.assertFalse(prepared["run"]["synthetic"])
            self.assertEqual(prepared["run"]["manifests"]["lineage"]["kind"], "preserved-private")
            # Preserve provenance without turning a valid byte import into an
            # invented independent review or a semantic acceptance result.
            self.assertEqual(prepared["run"]["boundary"], "pending-external-reviewer-probes")

    def test_lifecycle(self):
        runtime = self.runtime(INCREMENTAL)
        observed = runtime["observations"]
        self.assertEqual(observed["preflight"]["review_protocol"], "incremental-v1")
        self.assertTrue(observed["accepted"]["ready_for_approval"])
        accepted = observed["unchanged_resume"]["incremental_evidence"]
        self.assertEqual([row["state"] for row in accepted["dependencies"]], ["accepted", "accepted"])
        self.assertEqual(accepted["delta"], [])
        for name in ("unchanged_resume_0", "unchanged_resume_1"):
            with self.subTest(resume=name):
                self.assertEqual(observed[name]["incremental_evidence"]["delta"], [])
                self.assertEqual(observed[name]["incremental_evidence"]["decision_basis_sha256"],
                                 accepted["decision_basis_sha256"])
        for name in ("selective_dependency", "changed_input", "changed_claim"):
            with self.subTest(invalidation=name):
                current = observed[name]["incremental_evidence"]
                self.assertEqual([row["state"] for row in current["dependencies"]], ["changed", "accepted"])
                self.assertNotEqual(current["decision_basis_sha256"], accepted["decision_basis_sha256"])
                self.assertEqual(current["dependencies"][1]["evidence_sha256"],
                                 accepted["dependencies"][1]["evidence_sha256"])
        self.assertEqual(observed["changed_input"]["checks"][0]["status"], "stale")
        self.assertNotEqual(observed["changed_claim"]["incremental_evidence"]["dependencies"][0]["claim_sha256"],
                            accepted["dependencies"][0]["claim_sha256"])

        self.assertFalse(observed["contradiction"]["ready_for_review"])
        self.assertTrue(observed["contradiction"]["blockers"])
        self.assertEqual(observed["new_failure"]["checks"][0]["status"], "failed")
        self.assertTrue(observed["new_failure"]["checks"][0]["current_failure"])
        self.assertFalse(observed["new_failure"]["ready_for_review"])
        for repaired in ("input_repaired", "claim_repaired", "failure_repaired"):
            with self.subTest(repaired=repaired):
                self.assertTrue(observed[repaired]["ready_for_approval"])
        for resumed_name in ("input_repaired_resume", "claim_repaired_resume", "contradiction_repaired_resume"):
            with self.subTest(repaired_resume=resumed_name):
                resumed_packet = observed[resumed_name]
                self.assertFalse(resumed_packet["blockers"])
                self.assertEqual([row["state"] for row in resumed_packet["incremental_evidence"]["dependencies"]],
                                 ["accepted", "accepted"])

        unresolved = observed["unresolved"]["review_obligations"]["obligations"]
        self.assertTrue(any(row["kind"] == "functional-finding" and not row["verified"] for row in unresolved))
        self.assertTrue(any(row["kind"] == "test-request" and not row["verified"] for row in unresolved))
        resumed = observed["unresolved_resume"]["review_obligations"]["obligations"]
        self.assertEqual({(row["kind"], row["id"]) for row in unresolved},
                         {(row["kind"], row["id"]) for row in resumed})
        self.assertTrue(observed["unresolved_resume"]["blockers"])
        deps = observed["unresolved_resume"]["incremental_evidence"]["dependencies"]
        self.assertEqual([row["state"] for row in deps], ["reopened", "accepted"])

        calls = runtime["calls"]
        by_label = {row["label"]: row for row in calls if row.get("label")}
        for name in ("preflight", "code_result", "accepted", "unchanged_resume_0", "unchanged_resume_1"):
            with self.subTest(native_success=name):
                self.assertEqual(by_label[name]["exit_code"], 0, by_label[name]["stderr"])
        for name in ("wrong_candidate", "wrong_basis", "necessary_missing", "tampered", "new_failure", "unresolved"):
            with self.subTest(native_refusal=name):
                self.assertNotEqual(by_label[name]["exit_code"], 0, by_label[name]["stdout"])
        for row in calls:
            self.assertEqual(row["stdout_sha256"], sha(row["stdout"].encode()))
            self.assertEqual(row["stderr_sha256"], sha(row["stderr"].encode()))
            self.assertGreaterEqual(row["finished_ns"], row["started_ns"])
            self.assertIn("workflow/scripts/", " ".join(row["command"]))
        stages = [row["mode"] for row in calls]
        self.assertLess(stages.index("code-review"), stages.index("verdict"))

    def test_integration(self):
        help_text = self.native("--help").stdout
        for command in ("prepare", "read", "score", "smoke"):
            self.assertIn(command, help_text)
        for document in ("benchmark.md", "benchmark-records.md"):
            self.assertIn("evidence-inspection", (ROOT / "docs" / document).read_text())
        with tempfile.TemporaryDirectory(dir=self.scratch_path) as temporary:
            outer = Path(temporary)
            output = outer / "prepared"
            native = json.loads(self.native("prepare", "--case", "c03", "--runtime", ROOT,
                                           "--condition", "incremental", "--output", output).stdout)
            run_path, view_path = Path(native["run_path"]), Path(native["view_path"])
            original_run_bytes = run_path.read_bytes()
            run, view = json.loads(run_path.read_text()), json.loads(view_path.read_text())
            self.assertTrue(native["prepared"])
            self.assertTrue(run["synthetic"])
            self.assertFalse(run["measured_review_observations"])
            self.inspection.validate_run(run)
            for name, identity in run["manifests"].items():
                independent = json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
                self.assertEqual(run["manifest_sha256"][name], sha(independent), name)
            self.assertEqual(run["view_sha256"], sha(view_path.read_bytes()))
            self.assertEqual(view["candidate"], run["manifests"]["source"]["candidate"])
            self.assertEqual(view["source_pin"], run["manifests"]["source"]["pin"])
            for packet_id in ("native-code-packet", "native-final-packet"):
                row = next(item for item in view["artifacts"] if item["id"] == packet_id)
                packet = json.loads((view_path.parent / row["path"]).read_text())
                self.assertEqual(packet["candidate"], view["candidate"])
                self.assertIn(view["source_pin"], packet["scope"])
                claims = packet["acceptance"]
                self.assertTrue(claims)
                claim_bindings = json.dumps(claims)
                for artifact in (item for item in view["artifacts"] if item["id"] in ("a01", "a02")):
                    self.assertIn(artifact["sha256"], claim_bindings)
                self.assertIn("incremental_evidence", packet)
            policy = next(row for row in view["artifacts"] if row["id"] == "workflow-policy")
            actual_policy = subprocess.check_output(
                ["git", "show", INCREMENTAL + ":workflow/docs/development-workflow.md"], cwd=ROOT)
            self.assertEqual((view_path.parent / policy["path"]).read_bytes(), actual_policy)
            visible = b"\n".join(path.read_bytes() for path in view_path.parent.rglob("*") if path.is_file())
            self.assertNotIn(str(outer).encode(), visible)
            oracle_path = run_path.parent / "synthetic-oracle.json"
            oracle = json.loads(oracle_path.read_text())
            self.assertTrue(oracle["defects"])
            self.assertNotIn(oracle["defects"][0]["repair"].encode(), visible)

            events = outer / "events.jsonl"
            artifact = view["artifacts"][0]
            read = self.native("read", "--view", view_path, "--artifact", artifact["id"],
                               "--role", "EVIDENCE", "--session", "final-session", "--events", events)
            self.assertEqual(read.stdout.encode(), (view_path.parent / artifact["path"]).read_bytes())
            event = json.loads(events.read_text())
            self.assertEqual(event["view_sha256"], run["view_sha256"])
            self.assertEqual(event["artifact_sha256"], artifact["sha256"])

            def append_declared_reads(manifest, event_path):
                for offset, phase in ((0, "inspection"), (3, "inspection"), (0, "probe")):
                    self.native("read", "--view", manifest, "--artifact", artifact["id"],
                        "--offset", offset, "--length", 4 if phase == "probe" else 7,
                        "--role", "CODE", "--session", "code-session", "--phase", phase,
                        "--events", event_path)

            append_declared_reads(view_path, events)
            valid_event_bytes = events.read_bytes()
            valid_events = [json.loads(line) for line in valid_event_bytes.splitlines()]

            boundary = {"schema": "evidence-inspection-v1", "view_sha256": run["view_sha256"],
                "session": "final-session", "observer": "external-reviewer-session", "synthetic": False,
                "observed_ns": event["wall_time_ns"] - 1,
                "boundary": {"read_only": True, "write_rejected": True},
                "probes": {"allowed_read": True, "oracle_denied": True, "other_condition_denied": True,
                           "write_denied": True, "necessary_access": True},
                "tools": ["synthetic-parser-fixture"], "reads_instrumented": True}
            review = self.review(verdict="APPROVE")
            review["native_output"] = "INVENTED_PRIVATE_NATIVE_OUTPUT marker " + str(outer)
            attempts = [self.attempt("code-first", [0, 1], status="failed", session="code-session"),
                        self.attempt("code-resumed", [1, 2], session="code-session"),
                        self.attempt("final-attempt", [2, 3], session="final-session")]
            attempts[-1]["role"] = "EVIDENCE"
            # This tests the score parser only; a false literal cannot create an
            # external reviewer. The prepared run remains synthetic throughout.
            capture = {"review": review, "attempts": attempts, "boundary": boundary,
                       "session": "final-session",
                       "decision_time_ns": max(row["wall_time_ns"] for row in valid_events) + 1}
            reviews_path = write_json(outer / "capture.json", capture)
            scored_dir = outer / "scored"
            args = ("score", "--run", run_path, "--reviews", reviews_path, "--events", events,
                    "--oracle", oracle_path, "--output", scored_dir)
            scored = json.loads(self.native(*args).stdout)
            self.assertTrue(scored["decision"]["critical_false_approval"])
            self.assertFalse(scored["decision"]["quality_pass"])
            self.assertFalse(scored["acceptable_efficiency_claim"])
            with self.subTest(declared_read_attribution=True):
                measured = scored["accounting"]
                self.assertEqual(measured["attempt_count"], 3)
                self.assertEqual(measured["session_launches"], 2)
                self.assertEqual([row["status"] for row in measured["attempts"]],
                                 ["failed", "completed", "completed"])
                self.assertEqual([row["session"] for row in measured["attempts"]],
                                 ["code-session", "code-session", "final-session"])
                self.assertEqual(measured["read_calls"], 3)
                self.assertEqual(measured["read_bytes"], artifact["bytes"] + 14)
                self.assertEqual(measured["unique_read_bytes"], artifact["bytes"])
                self.assertEqual(measured["repeat_read_bytes"], 14)
                self.assertEqual(measured["probe_bytes"], 4)
                self.assertTrue(scored["observability"]["telemetry_complete"])
            public = (scored_dir / "score.json").read_bytes()
            for secret in (str(outer).encode(), b"INVENTED_PRIVATE_NATIVE_OUTPUT",
                           oracle["defects"][0]["repair"].encode()):
                self.assertNotIn(secret, public)
            self.assertNotIn((view_path.parent / artifact["path"]).read_bytes(), public)
            self.assertIn(b"INVENTED_PRIVATE_NATIVE_OUTPUT", (scored_dir / "audit.json").read_bytes())
            self.native(*args, success=False)

            def expected_score_identity(prepared_run):
                return {"case_id": prepared_run["case_id"], "condition": prepared_run["condition"],
                        "pin": prepared_run["pin"], "view_sha256": prepared_run["view_sha256"],
                        "run_sha256": sha(json.dumps(prepared_run, sort_keys=True,
                            separators=(",", ":"), allow_nan=False).encode()),
                        "manifest_sha256": prepared_run["manifest_sha256"]}

            with self.subTest(sanitized_run_identity="incremental"):
                expected_identity = expected_score_identity(run)
                self.assertEqual({key: scored.get(key) for key in expected_identity}, expected_identity)

            with self.subTest(sanitized_run_identity="matched-conditions"):
                baseline_native = json.loads(self.native("prepare", "--case", "c03", "--runtime", ROOT,
                    "--condition", "baseline", "--output", outer / "baseline-prepared").stdout)
                baseline_run_path = Path(baseline_native["run_path"])
                baseline_view_path = Path(baseline_native["view_path"])
                baseline_run = json.loads(baseline_run_path.read_text())
                baseline_view = json.loads(baseline_view_path.read_text())
                baseline_artifact = next(row for row in baseline_view["artifacts"] if row["id"] == artifact["id"])
                self.assertEqual((baseline_view_path.parent / baseline_artifact["path"]).read_bytes(),
                                 (view_path.parent / artifact["path"]).read_bytes())
                baseline_events = outer / "baseline-events.jsonl"
                self.native("read", "--view", baseline_view_path, "--artifact", artifact["id"],
                    "--role", "EVIDENCE", "--session", "final-session", "--events", baseline_events)
                append_declared_reads(baseline_view_path, baseline_events)
                baseline_rows = [json.loads(line) for line in baseline_events.read_bytes().splitlines()]
                baseline_capture = copy.deepcopy(capture)
                baseline_capture["boundary"]["view_sha256"] = baseline_run["view_sha256"]
                baseline_capture["decision_time_ns"] = max(row["wall_time_ns"] for row in baseline_rows) + 1
                baseline_capture_path = write_json(outer / "baseline-capture.json", baseline_capture)
                baseline_scored = json.loads(self.native("score", "--run", baseline_run_path,
                    "--reviews", baseline_capture_path, "--events", baseline_events,
                    "--oracle", baseline_run_path.parent / "synthetic-oracle.json",
                    "--output", outer / "baseline-scored").stdout)
                self.assertEqual(baseline_scored["native_review_audit_sha256"], scored["native_review_audit_sha256"])
                self.assertEqual(baseline_scored["accounting"], scored["accounting"])
                self.assertNotEqual(baseline_scored, scored)
                expected_identity = expected_score_identity(baseline_run)
                self.assertEqual({key: baseline_scored.get(key) for key in expected_identity}, expected_identity)
                self.assertEqual(baseline_scored["case_id"], scored["case_id"])
                self.assertNotEqual(baseline_scored["condition"], scored["condition"])
                self.assertNotEqual(baseline_scored["pin"], scored["pin"])
                for secret in (str(outer), "INVENTED_PRIVATE_NATIVE_OUTPUT", oracle["defects"][0]["repair"]):
                    self.assertNotIn(secret, json.dumps(baseline_scored))

            with self.subTest(sanitized_run_identity="changed-effective-input"):
                changed_run = copy.deepcopy(run)
                changed_run["manifests"]["prompt"]["instruction"] += " Changed synthetic bound instruction."
                changed_run["manifest_sha256"]["prompt"] = sha(json.dumps(
                    changed_run["manifests"]["prompt"], sort_keys=True, separators=(",", ":"),
                    allow_nan=False).encode())
                try:
                    write_json(run_path, changed_run)
                    changed_args = list(args)
                    changed_args[-1] = outer / "changed-input-scored"
                    changed_scored = json.loads(self.native(*changed_args).stdout)
                    self.assertEqual(changed_scored["native_review_audit_sha256"], scored["native_review_audit_sha256"])
                    self.assertEqual(changed_scored["accounting"], scored["accounting"])
                    self.assertNotEqual(changed_scored, scored)
                    expected_identity = expected_score_identity(changed_run)
                    self.assertEqual({key: changed_scored.get(key) for key in expected_identity}, expected_identity)
                    self.assertEqual(changed_scored["view_sha256"], scored["view_sha256"])
                    self.assertNotEqual(changed_scored["run_sha256"], scored["run_sha256"])
                    self.assertNotEqual(changed_scored["manifest_sha256"]["prompt"], scored["manifest_sha256"]["prompt"])
                    for secret in (str(outer), "INVENTED_PRIVATE_NATIVE_OUTPUT",
                                   changed_run["manifests"]["prompt"]["instruction"]):
                        self.assertNotIn(secret, json.dumps(changed_scored))
                finally:
                    run_path.write_bytes(original_run_bytes)

            for label, change in (("unknown-session", {"session": "unlisted-session"}),
                                  ("mismatched-role", {"role": "CODE"}),
                                  ("after-decision", {"wall_time_ns": capture["decision_time_ns"] + 1})):
                with self.subTest(refused_same_view_event=label):
                    unattributed = dict(event, **change)
                    events.write_bytes(valid_event_bytes + json.dumps(unattributed).encode() + b"\n")
                    refusal = list(args)
                    refusal[-1] = outer / ("refused-attribution-" + label)
                    self.native(*refusal, success=False)
                    self.assertFalse(Path(refusal[-1]).exists())
            events.write_bytes(valid_event_bytes)

            for field in ("necessary_access", "oracle_denied", "other_condition_denied"):
                with self.subTest(refused_probe=field):
                    invalid = copy.deepcopy(capture)
                    invalid["boundary"]["probes"][field] = False
                    write_json(reviews_path, invalid)
                    refusal = list(args)
                    refusal[-1] = outer / ("refused-" + field)
                    self.native(*refusal, success=False)
                    self.assertFalse(Path(refusal[-1]).exists())
            write_json(reviews_path, capture)
            foreign = dict(event, view_sha256=sha(b"another condition"))
            events.write_text(json.dumps(foreign) + "\n")
            refusal = list(args)
            refusal[-1] = outer / "refused-foreign-event"
            self.native(*refusal, success=False)
            self.assertFalse(Path(refusal[-1]).exists())

            for group in ("source", "workflow", "evidence", "prompt", "environment"):
                with self.subTest(manifest_drift=group):
                    changed = copy.deepcopy(run)
                    changed["manifests"][group]["unexpected"] = "changed effective input"
                    self.rejected(self.inspection.validate_run, changed)
            substituted = copy.deepcopy(run)
            replacement = self.runtime(BASELINE)["identity"]
            substituted["manifests"]["workflow"] = copy.deepcopy(replacement)
            substituted["manifests"]["workflow"]["pin"] = INCREMENTAL
            substituted["manifest_sha256"]["workflow"] = sha(json.dumps(
                substituted["manifests"]["workflow"], sort_keys=True, separators=(",", ":")).encode())
            self.rejected(self.inspection.validate_run, substituted)

            smoke_dir = outer / "smoke"
            smoke = json.loads(self.native("smoke", "--runtime", ROOT, "--output", smoke_dir).stdout)
            self.assertTrue(smoke["machinery_only"])
            self.assertTrue(smoke["synthetic"])
            self.assertFalse(smoke["measured_review_observations"])
            self.assertFalse(smoke["acceptable_efficiency_claim"])
            self.assertEqual(smoke["default_protocols"], {"baseline": "legacy", "incremental": "incremental-v1"})
            self.assertEqual(smoke["generic_block_detection_credit"], 0)
            self.assertTrue(smoke["critical_false_approval_gates_efficiency"])
            for arm in ("baseline", "incremental"):
                native_runtime = json.loads((smoke_dir / arm / "native.json").read_text())
                self.assertFalse(native_runtime["measured_review_observations"])
                for call in native_runtime["calls"]:
                    self.assertIn("workflow/scripts/", " ".join(call["command"]))
                    self.assertEqual(Path(call["command"][0]).resolve(), Path(sys.executable).resolve())
                self.assertEqual(smoke["native_call_counts"][arm], len(native_runtime["calls"]))


if __name__ == "__main__":
    unittest.main()
