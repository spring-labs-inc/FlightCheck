"""Read-only dependency planning for a selected flight's next review.

The adapter executes the returned actions through its trusted recorder, then
asks again. A missing prerequisite is an actionable state, never approval.
"""

from pathlib import Path

from proof import (contract_status, ledger, obligations_status, retained_artifact,
                   report_tests, test_names)
from behavior import status as behavior_status
from disposition import pending as refutation


def plan(task, root, checks, target="code"):
    if target not in ("code", "final"):
        raise ValueError("Recovery target must be code or final")
    try:
        return _plan(task, root, checks, target)
    except (OSError, KeyError, TypeError, ValueError) as error:
        return {"candidate": task.get("candidate"), "target": target,
                "state": "infrastructure_error", "action": "blocked",
                "actions": [{"action": "repair_evidence", "reason": str(error)}],
                "blockers": ["evidence integrity"],
                "behavior_evidence": {"cases": [], "blockers": ["evidence integrity"]}}


def _plan(task, root, checks, target):
    result = {"candidate": task["candidate"], "target": target,
              "state": "ready", "action": "review", "actions": [], "blockers": []}
    _, error = contract_status(task, root)
    if error:
        return dict(result, state="infrastructure_error", action="blocked",
                    blockers=["acceptance contract"], reason=error,
                    behavior_evidence={"cases": [], "blockers": ["acceptance contract"]})
    by_gate = {g["id"]: g for g in task["gates"]}
    statuses = {g["id"]: g for g in checks}
    required = {g["id"] for g in task["gates"]
                if target == "final" or g.get("phase") == "cheap"}
    actions = []
    forced = set()

    def add(action, reason, **fields):
        item = {"action": action, "reason": reason, **fields}
        if item not in actions:
            actions.append(item)

    state = ledger(root)
    obligations = obligations_status(task, root, checks, code=target == "code")
    result["obligations"] = obligations
    verified = {(r["kind"], r["id"]): r for r in obligations["obligations"]}
    for group, kind, mapping, gate_key in (
        ("requests", "test-request", "request_checks", "gate"),
        ("findings", "functional-finding", "regressions", "after_gate"),
    ):
        for key, original in state[group].items():
            if target == "code" and original["role"] != "CODE":
                continue
            row = verified[(kind, key)]
            if row.get("withdrawn"):
                continue
            if row.get("withdrawal_invalid"):
                add("repair_evidence", "Restore or explicitly revise the damaged withdrawal evidence",
                    obligation=key, kind=kind)
                continue
            if row.get("refutation") and not row["verified"]:
                add("review_disposition", "Have an independent reviewer acknowledge the qualified counterevidence",
                    obligation=key, kind=kind, role=original["role"])
                continue
            proof = task.get(mapping, {}).get(key)
            if not isinstance(proof, dict):
                add("configure_proof", "Map the retained obligation to controller evidence",
                    obligation=key, kind=kind)
                continue
            if "exception" in proof:
                if not row["verified"]:
                    add("configure_proof", "The referenced owner exception is not valid",
                        obligation=key, kind=kind)
                continue
            gate = proof.get(gate_key)
            if gate not in by_gate:
                add("configure_proof", "The obligation needs a configured required gate",
                    obligation=key, kind=kind)
                continue
            required.add(gate)
            check = statuses[gate]
            if kind == "functional-finding":
                try:
                    before, report = retained_artifact(root, proof["before"], proof["report"])
                    tests = test_names(proof["tests"])
                    if (before["candidate"] != original["candidate"]
                            or before["exit_code"] == 0
                            or not tests <= report_tests(report, "failed")):
                        raise ValueError("Original-product witness does not demonstrate the finding")
                    if check["status"] in ("passed", "reused", "reusable"):
                        after, _ = retained_artifact(root, str(Path(check["receipt"]).relative_to(root)),
                                                     proof["report"])
                        if before["artifacts"][proof["spec"]] != after["artifacts"][proof["spec"]]:
                            raise ValueError("Reproduce the original product using the current test/fixture specification")
                        if after["candidate"] != task["candidate"]:
                            forced.add(gate)
                except (OSError, KeyError, TypeError, ValueError) as error:
                    add("reproduce", str(error), obligation=key, kind=kind,
                        candidate=original["candidate"])
            elif check["status"] in ("passed", "reused", "reusable") and not row["verified"]:
                if (check.get("owner") != "controller"
                        or check.get("started_at", 0) < original["recorded_at"]):
                    forced.add(gate)
                else:
                    add("repair_proof", "Current evidence lacks the requested exact passing identities or assertion",
                        obligation=key, kind=kind, gate=gate)

    behavior = behavior_status(task, root, checks)
    result["behavior_evidence"] = behavior
    plan_blockers = [b for b in behavior["blockers"] if b.startswith("independent challenge")]
    if plan_blockers:
        add("plan_challenges", "Retain an independent proposal bound to the task contract")
    if target == "final":
        for row in behavior["cases"]:
            if row["verified"]:
                continue
            if row.get("withdrawal_invalid"):
                add("repair_evidence", row["reason"], obligation=row["id"], kind="challenge-case")
                continue
            if row["origin"] == "challenge" and refutation(task, root, state, "challenge-case", row["id"]):
                add("review_disposition", "Adjudicate the proposed challenge refutation",
                    obligation=row["id"], kind="challenge-case")
                continue
            gate = row.get("gate")
            if gate not in by_gate:
                add("configure_proof", "Map the required case to a configured native witness", case=row["id"])
                continue
            required.add(gate)
            check = statuses[gate]
            if check["status"] in ("passed", "reused", "reusable"):
                if check.get("owner") != "controller" or check.get("started_at", 0) < row.get("recorded_at", 0):
                    forced.add(gate)
                elif not set(row.get("tests", [])) <= set(check.get("coverage", {}).get("verified", {}).get("passed_tests", [])):
                    add("repair_proof", "Execute the exact required case identities", case=row["id"], gate=gate)
                else:
                    add("qualify_control", row.get("reason", "Qualify the expected outcome"), case=row["id"])

    for gate in sorted(required):
        check = statuses[gate]
        status = check["status"]
        if status == "pending" and check.get("reason") not in ("interrupted", "unavailable"):
            add("wait", "Reconcile the newest active attempt before continuing", gate=gate)
        elif check.get("current_failure"):
            add("repair", "The current required check failed", gate=gate)
        elif gate in forced:
            add("run", "Refresh the candidate-bound controller proof", gate=gate,
                owner="controller", refresh=True)
        elif status == "reusable":
            add("reuse", "Bind the verified unchanged-input pass to this candidate", gate=gate,
                owner="controller")
        elif status not in ("passed", "reused"):
            add("run", check.get("reason", "Required evidence is missing or stale"), gate=gate,
                owner="controller", refresh=True)

    if not actions and obligations["blockers"]:
        add("repair_proof", "Retained obligations are unresolved despite passing gates",
            obligations=obligations["blockers"])
    result["actions"] = actions
    result["blockers"] = obligations["blockers"] + sorted(
        gate for gate in required if statuses[gate]["status"] not in ("passed", "reused"))
    result["blockers"].extend(behavior["blockers"] if target == "final" else plan_blockers)
    if actions:
        if any(a["action"] == "wait" for a in actions):
            result.update(state="waiting", action="wait")
        elif any(a["action"] == "plan_challenges" for a in actions):
            result.update(state="needs_plan", action="plan_challenges")
        elif any(a["action"] in ("configure_proof", "reproduce", "repair_proof", "repair", "qualify_control", "repair_evidence") for a in actions):
            result.update(state="needs_repair", action="repair")
        elif any(a["action"] == "review_disposition" for a in actions):
            result.update(state="needs_review", action="review_disposition")
        else:
            result.update(state="needs_checks", action="run_checks")
    return result
