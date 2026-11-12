"""Project-independent acceptance and review obligations for a selected flight.

The adapter owns the private evidence root and records actual reviewer output.
These checks validate provenance and completeness, not the meaning of a test.
The independent reviewer must still judge whether its assertions prove acceptance.
"""

import hashlib
import fcntl
import json
import re
import time
from pathlib import Path

from capture_check import digest, write_json

IDENTIFIER = re.compile(r"[a-zA-Z0-9_-]+")
PASS = {"passed", "reused", "reusable"}
OUTCOMES = {"passed", "skipped", "expected_failures", "failed"}


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError("Expected a nonempty identifier containing letters, digits, _ or -")
    return value


def nonempty(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected a nonempty explanation or reference")
    return value


def inside(root, name):
    path = (root / nonempty(name)).resolve()
    if root not in path.parents:
        raise ValueError("Evidence reference escapes the task evidence root")
    return path


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def criteria(task):
    items = task["acceptance"]
    if not isinstance(items, list) or not items:
        raise ValueError("Acceptance needs structured criteria with IDs, descriptions, and proofs")
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Acceptance needs structured criteria, not unverified prose")
        key = identifier(item["id"])
        if key in seen:
            raise ValueError("Acceptance criterion IDs must be unique")
        seen.add(key)
        nonempty(item["description"])
        if not isinstance(item["proofs"], list) or not item["proofs"]:
            raise ValueError("Every acceptance criterion needs a verification method")
        for proof in item["proofs"]:
            kind = proof["kind"]
            if kind == "check":
                identifier(proof["gate"])
                nonempty(proof["assertion"])
                if "tests" in proof:
                    test_names(proof["tests"])
            elif kind == "owner":
                nonempty(proof["reference"])
            elif kind == "review":
                if item.get("automatable") is not False:
                    raise ValueError("Review-only proof needs an explicitly non-automatable criterion")
                nonempty(item["reason"])
                nonempty(proof["assertion"])
            else:
                raise ValueError("Unknown acceptance verification method")
    from behavior import acceptance_cases
    acceptance_cases(task)
    return items


def test_names(names):
    if (not isinstance(names, list) or not names or any(not isinstance(n, str) or not n.strip() for n in names)
            or len(set(names)) != len(names)):
        raise ValueError("Expected unique nonempty test identities")
    return set(names)


def owner_decision(root, reference, candidate, key, value):
    path = inside(root, reference)
    decision = read(path)
    if (decision.get("candidate") != candidate or decision.get(key) != value
            or decision.get("accepted") is not True or decision.get("authority") != "owner"):
        raise ValueError("Current explicit owner decision required")
    nonempty(decision["source"])
    nonempty(decision["reason"])
    return {"reference": reference, "sha256": digest(path), "reason": decision["reason"]}


def gate_contracts(task):
    # Ownership can move to the controller and reuse receipts change per run;
    # neither is permission to change what a required gate proves or when it runs.
    return {g["id"]: {"request": g["request"], "coverage": g.get("coverage"),
                      "phase": g.get("phase", "authoritative")} for g in task["gates"]}


def preserves_gates(previous, current):
    frozen = previous.get("gates")
    return isinstance(frozen, dict) and all(current.get(key) == value for key, value in frozen.items())


def freeze(task, root, amendment=None):
    """Do not silently erase or weaken an earlier task contract on resume."""
    path = root / "acceptance-contract.json"
    previous = read(path) if path.exists() else None
    baseline = task.get("baseline_candidate", (previous or {}).get("baseline_candidate", task["candidate"]))
    nonempty(baseline)
    if previous is not None and "baseline_candidate" not in previous and "baseline_candidate" not in task:
        raise ValueError("Legacy flight needs its retained original baseline_candidate for explicit contract migration")
    contract = {"acceptance": criteria(task), "required_gates": sorted(g["id"] for g in task["gates"]),
                "gates": gate_contracts(task), "baseline_candidate": baseline}
    for item in contract["acceptance"]:
        for proof in item["proofs"]:
            if proof["kind"] == "check" and proof["gate"] not in contract["required_gates"]:
                raise ValueError("Acceptance proof names an unconfigured required gate")
    if previous is not None:
        changed = (previous["acceptance"] != contract["acceptance"]
                   or not preserves_gates(previous, contract["gates"])
                   or previous.get("baseline_candidate") != baseline)
        if changed:
            if amendment is None:
                raise ValueError("Frozen scope changed; record the owner's scope instruction with --amend-contract")
            decision = owner_decision(root, amendment, task["candidate"], "previous_contract_sha256", digest(path))
            contract["amendment"] = decision
        if changed or set(previous["required_gates"]) != set(contract["required_gates"]):
            history = root / "contracts"
            history.mkdir(mode=0o700, exist_ok=True)
            (history / (digest(path) + ".json")).write_bytes(path.read_bytes())
            write_json(path, contract)
    else:
        write_json(path, contract)
    return {"path": str(path), "sha256": digest(path)}


def contract_status(task, root):
    try:
        items = criteria(task)
        contract = read(root / "acceptance-contract.json")
        valid = (contract["acceptance"] == items
                 and preserves_gates(contract, gate_contracts(task))
                 and isinstance(contract.get("baseline_candidate"), str)
                 and bool(contract["baseline_candidate"].strip())
                 and task.get("baseline_candidate", contract["baseline_candidate"]) == contract["baseline_candidate"])
        if not valid:
            raise ValueError("Frozen acceptance or required gates changed")
        return items, None
    except (OSError, KeyError, TypeError, ValueError) as error:
        return [], str(error)


def passed_tests(check, names):
    required = test_names(names)
    verified = check.get("coverage", {}).get("verified", {})
    return required <= set(verified.get("passed_tests", []))


def acceptance_status(task, root, checks):
    items, error = contract_status(task, root)
    if error:
        return {"criteria": [], "blockers": ["acceptance contract"], "reason": error}
    by_gate = {g["id"]: g for g in checks}
    rows, blockers = [], []
    for item in items:
        proofs = []
        for proof in item["proofs"]:
            state = "unverified"
            row = dict(proof)
            try:
                if proof["kind"] == "check":
                    gate = by_gate[proof["gate"]]
                    if gate["status"] in PASS and ("tests" not in proof or passed_tests(gate, proof["tests"])):
                        state = "verified"
                    row["receipt"] = gate.get("receipt")
                elif proof["kind"] == "owner":
                    path = inside(root, proof["reference"])
                    decision = read(path)
                    if (decision["candidate"] == task["candidate"] and decision["criterion"] == item["id"]
                            and decision["accepted"] is True and decision["authority"] == "owner"
                            and nonempty(decision["source"]) and nonempty(decision["reason"])):
                        state = "verified"
                    row["sha256"] = digest(path)
                else:
                    state = "review-required"
            except (OSError, KeyError, TypeError, ValueError):
                pass
            proofs.append(dict(row, status=state))
        ready = all(p["status"] in ("verified", "review-required") for p in proofs)
        # A failed required gate already blocks the enclosing packet. Reserve a
        # separate acceptance blocker for missing mappings, decisions, or assertions.
        extra = any(p["status"] == "unverified" and
                    (p["kind"] != "check" or by_gate.get(p.get("gate"), {}).get("status") in PASS
                     or p.get("gate") not in by_gate) for p in proofs)
        if not ready and extra:
            blockers.append("acceptance:" + item["id"])
        rows.append({"id": item["id"], "description": item["description"], "proofs": proofs,
                     "ready_for_review": ready})
    return {"criteria": rows, "blockers": blockers}


def ledger(root):
    path = root / "review-obligations.json"
    return read(path) if path.exists() else {"requests": {}, "findings": {}}


def record_review(task, root, path):
    with (root / "review-obligations.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _record_review(task, root, path)


def _record_review(task, root, path):
    """Retain native reviewer output and append obligations; omission cannot clear them."""
    raw = path.read_bytes()
    review = json.loads(raw)
    _, contract_error = contract_status(task, root)
    if contract_error:
        raise ValueError(contract_error)
    # Missing arrays are an incomplete review, never an implicit zero finding.
    if not isinstance(review, dict):
        raise ValueError("Native reviewer output must be a complete object")
    nonempty(review["coverage"])
    if not isinstance(review["findings"], list) or not isinstance(review["test_requests"], list):
        raise ValueError("Native review requires explicit findings and test_requests arrays")
    if review["verdict"] not in ("APPROVE", "APPROVE_WITH_NITS", "APPROVE_WITH_OBSERVATIONS", "REVISE"):
        raise ValueError("Native review needs a recognized verdict")
    for field in ("criteria", "challenge"):
        if field not in review:
            raise ValueError("Native review is incomplete")
    if review["candidate"] != task["candidate"] or review["role"] not in ("CODE", "EVIDENCE"):
        raise ValueError("Reviewer role or candidate does not match")
    if review.get("phase") not in (None, "code", "final", "disposition"):
        raise ValueError("Unknown native review phase")
    known = {c["id"] for c in criteria(task)}
    state = ledger(root)
    source = hashlib.sha256(raw).hexdigest()
    additions = {"requests": [], "findings": []}
    for request in review["test_requests"]:
        identifier(request["id"])
        if request["criterion"] not in known:
            raise ValueError("Reviewer test request names an unknown criterion")
        for field in ("input", "expected", "reason"):
            nonempty(request[field])
        additions["requests"].append(request)
    for finding in review["findings"]:
        identifier(finding["id"])
        if finding["kind"] not in ("functional", "process", "nit"):
            raise ValueError("Every finding needs its actual kind")
        if finding["severity"] not in ("BLOCKER", "CONCERN", "NIT"):
            raise ValueError("Unknown finding severity")
        nonempty(finding["reference"])
        nonempty(finding["impact"])
        if finding["kind"] == "functional":
            additions["findings"].append(finding)
    for group, items in additions.items():
        for item in items:
            old = state[group].get(item["id"])
            kind = "test-request" if group == "requests" else "functional-finding"
            if kind + ":" + item["id"] in state.get("withdrawals", {}):
                raise ValueError("A recurrent claim needs a new identity; withdrawn history cannot be silently reopened")
            if old and old["spec"] != item:
                raise ValueError("An earlier review obligation cannot be overwritten")
            if not old:
                state[group][item["id"]] = {"spec": item, "candidate": review["candidate"],
                                             "role": review["role"], "review_sha256": source,
                                             "recorded_at": time.time()}
    from disposition import acknowledge
    withdrawals, revisions = acknowledge(task, root, state, review, source)
    if withdrawals:
        state.setdefault("withdrawals", {}).update(withdrawals)
    if revisions:
        state.setdefault("withdrawal_history", []).extend(revisions)
    directory = root / "reviews"
    directory.mkdir(mode=0o700, exist_ok=True)
    retained = directory / (source + ".json")
    if not retained.exists():
        retained.write_bytes(raw)
    write_json(root / "review-obligations.json", state)
    return review


def retained_artifact(root, receipt_path, artifact):
    path = inside(root, receipt_path)
    receipt = read(path)
    run = path.parent
    request = receipt["request"]
    # Validate every retained output and input binding, including a deliberately failing reproduction.
    if (receipt["status"] != "finished" or receipt.get("owner") != "controller"
            or not receipt.get("inputs_before") or receipt["inputs_before"] != receipt["inputs_after"]
            or receipt["output"]["path"] != "output.log"
            or receipt["output"]["status"] != "complete"
            or digest(run / "output.log") != receipt["output"]["sha256"]):
        raise ValueError("Regression receipt is incomplete or not controller verified")
    for index, name in enumerate(request["artifacts"]):
        if digest(run / f"artifact-{index}") != receipt["artifacts"][name]:
            raise ValueError("Regression artifact was changed")
    index = request["artifacts"].index(artifact)
    return receipt, run / f"artifact-{index}"


def report_tests(path, outcome):
    report = read(path)
    if set(report) != OUTCOMES:
        raise ValueError("Behavior report needs the four coverage outcome lists")
    seen = set()
    for names in report.values():
        if not isinstance(names, list) or any(not isinstance(n, str) or not n.strip() or n in seen for n in names):
            raise ValueError("Behavior test identities must be unique")
        if len(set(names)) != len(names):
            raise ValueError("Duplicate behavior test identity")
        seen.update(names)
    return set(report[outcome])


def obligations_status(task, root, checks, code=False):
    from disposition import verified as withdrawn, pending as refutation, key as withdrawal_key
    state = ledger(root)
    by_gate = {g["id"]: g for g in checks}
    blockers, rows, exceptions = [], [], []
    for key, request in state["requests"].items():
        if code and request["role"] != "CODE":
            continue
        if withdrawal_key("test-request", key) in state.get("withdrawals", {}):
            valid = withdrawn(task, root, state, "test-request", key)
            rows.append({"id": key, "kind": "test-request", "spec": request["spec"],
                         "verified": valid, "withdrawn": valid, "withdrawal_invalid": not valid})
            if not valid:
                blockers.append("withdrawal-evidence:test-request:" + key)
            continue
        valid = False
        try:
            proof = task["request_checks"][key]
            check = by_gate[proof["gate"]]
            valid = (check["status"] in PASS and check.get("owner") == "controller"
                     and check.get("started_at", 0) >= request["recorded_at"]
                     and nonempty(proof["assertion"]) and passed_tests(check, proof["tests"]))
        except (OSError, KeyError, TypeError, ValueError):
            pass
        rows.append({"id": key, "kind": "test-request", "spec": request["spec"], "verified": bool(valid),
                     "refutation": refutation(task, root, state, "test-request", key)})
        if not valid:
            blockers.append("test-request:" + key)
    for key, finding in state["findings"].items():
        if code and finding["role"] != "CODE":
            continue
        if withdrawal_key("functional-finding", key) in state.get("withdrawals", {}):
            valid = withdrawn(task, root, state, "functional-finding", key)
            rows.append({"id": key, "kind": "functional-finding", "verified": valid,
                         "withdrawn": valid, "withdrawal_invalid": not valid})
            if not valid:
                blockers.append("withdrawal-evidence:functional-finding:" + key)
            continue
        valid = False
        try:
            proof = task["regressions"][key]
            if "exception" in proof:
                decision = owner_decision(root, proof["exception"], task["candidate"], "finding", key)
                exceptions.append(dict(decision, finding=key))
                rows.append({"id": key, "kind": "functional-finding", "verified": True,
                             "owner_exception": decision})
                continue
            before, before_report = retained_artifact(root, proof["before"], proof["report"])
            check = by_gate[proof["after_gate"]]
            after_path = str(Path(check["receipt"]).relative_to(root))
            after, after_report = retained_artifact(root, after_path, proof["report"])
            tests = test_names(proof["tests"])
            # Identical retained test specification/fixture manifests must govern both runs.
            spec = proof["spec"]
            valid = (before["candidate"] == finding["candidate"] and before["exit_code"] != 0
                     and after["candidate"] == task["candidate"] and check["status"] in PASS
                     and before["artifacts"][spec] == after["artifacts"][spec]
                     and tests <= report_tests(before_report, "failed")
                     and tests <= report_tests(after_report, "passed"))
        except (OSError, KeyError, TypeError, ValueError):
            pass
        rows.append({"id": key, "kind": "functional-finding", "verified": bool(valid),
                     "refutation": refutation(task, root, state, "functional-finding", key)})
        if not valid:
            blockers.append("regression:" + key)
    return {"obligations": rows, "blockers": blockers, "owner_exceptions": exceptions}


def verdict_status(task, root, packet, review):
    blockers = list(packet["blockers"])
    if review.get("role") != "EVIDENCE" or review.get("candidate") != task["candidate"]:
        blockers.append("current independent EVIDENCE review")
    if review.get("phase") in ("code", "disposition"):
        blockers.append("full independent final review")
    expected_ids = {c["id"] for c in criteria(task)}
    assessments = review.get("criteria", [])
    if (not isinstance(assessments, list) or len(assessments) != len(expected_ids)
            or any(not isinstance(c, dict) for c in assessments)
            or {c.get("id") for c in assessments} != expected_ids
            or any(c.get("sufficient") is not True or not isinstance(c.get("reason"), str)
                   or not c["reason"].strip() for c in assessments)):
        blockers.append("reviewer acceptance assessment")
    if not isinstance(review.get("challenge"), str) or not review["challenge"].strip():
        blockers.append("independent boundary challenge assessment")
    from behavior import assessment_blockers
    blockers.extend(assessment_blockers(review, packet["behavior_evidence"]))
    severities = {f["severity"] for f in review.get("findings", [])}
    exceptions = packet["review_obligations"].get("owner_exceptions", [])
    if exceptions:
        severities.add("CONCERN")
    routed = ("REVISE" if "BLOCKER" in severities else "APPROVE_WITH_OBSERVATIONS" if "CONCERN" in severities
              else "APPROVE_WITH_NITS" if "NIT" in severities else "APPROVE")
    if review.get("verdict") != routed:
        blockers.append("verdict does not match findings")
    observations = {"findings": [f for f in review.get("findings", []) if f["severity"] == "CONCERN"],
                    "regression_exceptions": exceptions}
    observation_hash = hashlib.sha256(json.dumps(observations, sort_keys=True).encode()).hexdigest()
    if routed == "REVISE":
        blockers.append("blocking finding")
    elif routed == "APPROVE_WITH_OBSERVATIONS":
        try:
            owner_decision(root, task["observation_approval"], task["candidate"], "observations_sha256", observation_hash)
        except (OSError, KeyError, TypeError, ValueError):
            blockers.append("explicit owner approval of observations")
    return {"candidate": task["candidate"], "verdict": routed, "blockers": sorted(set(blockers)),
            "ready_for_approval": not blockers, "owner_approval_required": routed == "APPROVE_WITH_OBSERVATIONS",
            "observations_sha256": observation_hash if routed == "APPROVE_WITH_OBSERVATIONS" else None}
