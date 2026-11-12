"""Project-supplied behavior cases, independent challenges and oracle controls.

These helpers verify actual evidence bindings. The independent reviewer judges
whether the selected cases, observations and expected outcomes are meaningful.
"""

import fcntl
import hashlib
import json
import time
from pathlib import Path

from capture_check import digest, write_json
from proof import (PASS, identifier, inside, nonempty, passed_tests, read,
                   retained_artifact, report_tests, test_names)

EXPECTATIONS = {"regression": "failed", "compatibility": "passed", "specification": "failed"}


def case_spec(case, criteria, independent=False):
    identifier(case["id"])
    for key in ("dimension", "input", "observable", "expected"):
        nonempty(case[key])
    if case["criterion"] not in criteria:
        raise ValueError("Behavior case names an unknown acceptance criterion")
    expectation = case["expectation"]
    if expectation["kind"] not in EXPECTATIONS:
        raise ValueError("Expectation must be regression, compatibility or specification")
    nonempty(expectation["reference"])
    if not independent:
        identifier(case["gate"])
        test_names(case["tests"])
    return case


def acceptance_cases(task):
    known = {item["id"] for item in task["acceptance"]}
    gates = {gate["id"]: gate for gate in task["gates"]}
    result, seen = [], set()
    for item in task["acceptance"]:
        native = [proof for proof in item["proofs"] if proof["kind"] == "check"]
        has_native = any("coverage" in gates.get(proof["gate"], {}) for proof in native)
        # Preserve assertion-only policy callers. Product behavior must explicitly
        # declare behavior or supply native coverage; review judges classification.
        kind = item.get("kind", "behavior" if has_native else "policy")
        if kind not in ("behavior", "policy"):
            raise ValueError("Acceptance kind must be behavior or policy")
        for proof in native:
            gate = gates.get(proof["gate"], {})
            if "coverage" in gate:
                # Native identities cannot be replaced with aggregate suite success,
                # even when the criterion verifies policy or evidence metadata.
                test_names(proof.get("tests"))
        if not native or kind == "policy":
            if item.get("cases"):
                raise ValueError("Behavior cases belong to an automated behavior criterion")
            continue
        cases = item.get("cases")
        if not isinstance(cases, list) or not cases:
            raise ValueError("Behavior acceptance needs explicit observable cases")
        for raw in cases:
            case = case_spec(dict(raw, criterion=item["id"]), known)
            if case["id"] in seen:
                raise ValueError("Behavior case identities must be unique across the flight")
            seen.add(case["id"])
            gate = gates.get(case["gate"])
            if gate is None or "coverage" not in gate:
                raise ValueError("Behavior cases require a configured gate with native coverage")
            result.append(case)
    return result


def challenge_brief(task):
    # Deliberately excludes diff, implementation notes, proposed tests and verdicts.
    brief = {"scope": task.get("scope", ""),
             "acceptance": [{"id": item["id"], "description": item["description"]}
                            for item in task["acceptance"]]}
    raw = json.dumps(brief, sort_keys=True, separators=(",", ":")).encode()
    return dict(brief, scope_sha256=hashlib.sha256(raw).hexdigest())


def challenge_ledger(root):
    path = root / "challenge-plan.json"
    return read(path) if path.exists() else None


def record_plan(task, root, path):
    """Append actual reviewer proposals; omission never drops a required case."""
    with (root / "challenge-plan.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        raw = path.read_bytes()
        proposal = json.loads(raw)
        scope = challenge_brief(task)["scope_sha256"]
        if proposal["role"] not in ("CODE", "EVIDENCE") or proposal["scope_sha256"] != scope:
            raise ValueError("Independent challenge plan must match this task contract")
        nonempty(proposal["coverage"])
        if not isinstance(proposal["cases"], list) or not proposal["cases"]:
            raise ValueError("Independent challenge plan needs concrete cases")
        known = {item["id"] for item in task["acceptance"]}
        proposed, ids = [], set()
        reserved = {case["id"] for case in acceptance_cases(task)}
        for case in proposal["cases"]:
            case_spec(case, known, independent=True)
            if case["id"] in ids or case["id"] in reserved:
                raise ValueError("Challenge case identities must be unique")
            ids.add(case["id"])
            proposed.append(case)
        state = challenge_ledger(root) or {"scope_sha256": scope, "cases": {}, "plans": []}
        if state["scope_sha256"] != scope:
            # Scope revision needs a new explicit contract/flight; existing cases
            # must not disappear through replacement of a task's description.
            raise ValueError("Challenge scope changed; retain the old flight and explicitly prepare the revised scope")
        source = hashlib.sha256(raw).hexdigest()
        for case in proposed:
            old = state["cases"].get(case["id"])
            if old and old["spec"] != case:
                raise ValueError("An independent challenge cannot be overwritten; add a separately identified case")
        directory = root / "challenges"
        directory.mkdir(mode=0o700, exist_ok=True)
        retained = directory / (source + ".json")
        if not retained.exists():
            retained.write_bytes(raw)
        for case in proposed:
            state["cases"].setdefault(case["id"], {"spec": case, "role": proposal["role"],
                "plan_sha256": source, "recorded_at": time.time()})
        if source not in state["plans"]:
            state["plans"].append(source)
        write_json(root / "challenge-plan.json", state)
        return {"scope_sha256": scope, "cases": sorted(state["cases"]),
                "plan_sha256": source}


def qualified_control(task, root, case, check, mapping):
    """A control must discriminate the assertion under the same test fixtures."""
    control = mapping[case["id"]]
    before, report = retained_artifact(root, control["receipt"], control["report"])
    after, _ = retained_artifact(root, str(Path(check["receipt"]).relative_to(root)),
                                control["report"])
    expected = EXPECTATIONS[case["expectation"]["kind"]]
    source = control["source"]
    sources = {"baseline", "mutation"} if case["expectation"]["kind"] == "specification" else {"baseline"}
    if (source not in sources or before["candidate"] != nonempty(control["candidate"])
            or control["spec"] == control["report"]
            or (source == "baseline"
                and before["candidate"] != read(root / "acceptance-contract.json")["baseline_candidate"])
            or before["artifacts"][control["spec"]] != after["artifacts"][control["spec"]]
            or (before["exit_code"] == 0) != (expected == "passed")
            or not test_names(case["tests"]) <= report_tests(report, expected)):
        raise ValueError("Expectation control does not establish the declared baseline or sensitivity")
    return {"receipt": control["receipt"], "source": source,
            "candidate": before["candidate"], "expected_outcome": expected,
            "spec_sha256": before["artifacts"][control["spec"]]}


def status(task, root, checks):
    from proof import ledger
    from disposition import verified as withdrawal_verified, key as withdrawal_key
    base = acceptance_cases(task)
    by_gate = {check["id"]: check for check in checks}
    gates = {gate["id"]: gate for gate in task["gates"]}
    state = challenge_ledger(root)
    dispositions = ledger(root)
    blockers, rows = [], []
    if base and state is None:
        blockers.append("independent challenge plan")
    if state and state["scope_sha256"] != challenge_brief(task)["scope_sha256"]:
        return {"cases": [], "blockers": ["independent challenge scope"]}
    work = [(case, "acceptance", None) for case in base]
    if state:
        for key, entry in state["cases"].items():
            plan = root / "challenges" / (entry["plan_sha256"] + ".json")
            original = read(plan)
            if digest(plan) != entry["plan_sha256"] or entry["spec"] not in original["cases"]:
                raise ValueError("Independent challenge provenance was changed")
            case = dict(entry["spec"])
            binding = task.get("challenge_checks", {}).get(key, {})
            case.update({k: binding[k] for k in ("gate", "tests") if k in binding})
            work.append((case, "challenge", entry))
    for case, origin, entry in work:
        row = {"id": case["id"], "criterion": case["criterion"], "origin": origin,
               "dimension": case["dimension"], "input": case["input"],
               "observable": case["observable"], "expected": case["expected"],
               "expectation": case["expectation"], "verified": False}
        row.update({key: case[key] for key in ("gate", "tests") if key in case})
        if entry:
            row["recorded_at"] = entry["recorded_at"]
        if origin == "challenge" and withdrawal_key("challenge-case", case["id"]) in dispositions.get("withdrawals", {}):
            closed = withdrawal_verified(task, root, dispositions, "challenge-case", case["id"])
            row.update(verified=closed, withdrawn=closed, withdrawal_invalid=not closed)
            if not closed:
                row["reason"] = "Retained withdrawal evidence is invalid"
                blockers.append("withdrawal-evidence:challenge-case:" + case["id"])
            rows.append(row)
            continue
        try:
            case_spec(case, {item["id"] for item in task["acceptance"]})
            if case["gate"] not in gates or "coverage" not in gates[case["gate"]]:
                raise ValueError("Case witness requires configured native coverage")
            check = by_gate[case["gate"]]
            if (check["status"] not in PASS or check.get("owner") != "controller"
                    or not passed_tests(check, case["tests"])):
                raise ValueError("Case needs exact passing controller-executed test identities")
            if entry and check.get("started_at", 0) < entry["recorded_at"]:
                raise ValueError("Challenge witness predates the actual independent proposal")
            row.update(gate=case["gate"], tests=case["tests"], receipt=check["receipt"],
                       control=qualified_control(task, root, case, check, task.get("case_controls", {})),
                       verified=True)
        except (OSError, KeyError, TypeError, ValueError) as error:
            row["reason"] = str(error)
            blockers.append(origin + "-case:" + case["id"])
        rows.append(row)
    return {"cases": rows, "blockers": blockers}


def assessment_blockers(review, evidence):
    expected = {row["id"] for row in evidence["cases"]}
    rows = review.get("case_assessments", [])
    if (not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows)
            or len(rows) != len(expected) or {row.get("id") for row in rows} != expected
            or any(row.get("sufficient") is not True or not isinstance(row.get("reason"), str)
                   or not row["reason"].strip() for row in rows)):
        return ["independent behavior-case assessments"]
    return []
