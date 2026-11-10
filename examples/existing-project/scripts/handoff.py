"""Route a saved SpringDev task or build a review packet."""

import argparse
from collections import Counter
import hashlib
import json
import re
from pathlib import Path

from capture_check import digest, fingerprint, latest_run, matches_pass

COVERAGE_OUTCOMES = ("passed", "skipped", "expected_failures", "failed")
EARLY_CODE_CRITERIA = (
    "Run early CODE review for material risk, such as a migration, permission or trading change, "
    "a change to a shared contract or across a boundary, or an uncertain approach where early review "
    "could avoid substantial rework. Skip when the change establishes or restores one bounded invariant, "
    "the affected paths are understood, and focused checks cover the change and relevant compatibility "
    "controls. Sharing an implementation is a reason to check affected "
    "callers. If their impact or coverage is materially uncertain, run early review. Record the "
    "reason and reassess after material changes to scope, behavior, or evidence."
)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def evidence_path(root, name):
    path = (root / name).resolve()
    if root not in path.parents:
        raise ValueError(f"Evidence path escapes the task evidence root: {name}")
    return path


def coverage_report(path, expected_digest):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_digest:
        raise ValueError("Coverage report digest does not match")
    report = json.loads(raw)
    if not isinstance(report, dict) or set(report) != set(COVERAGE_OUTCOMES):
        raise ValueError("Coverage report needs all four outcome lists")
    identities = {}
    for outcome, tests in report.items():
        if not isinstance(tests, list):
            raise ValueError("Coverage outcomes must contain lists of test identities")
        for test in tests:
            if not isinstance(test, str) or not test.strip() or test in identities:
                raise ValueError("Coverage test identities must be unique and nonempty")
            identities[test] = outcome
    return identities


def verified_coverage(root, run, receipt, request, contract):
    artifact = contract["artifact"]
    report = run / f"artifact-{request['artifacts'].index(artifact)}"
    current = coverage_report(report, receipt["artifacts"][artifact])
    baseline = evidence_path(root, contract["baseline"])
    required = coverage_report(baseline, contract["baseline_sha256"])
    missing = sorted(required.keys() - current.keys())
    changed = sorted(test for test in required.keys() & current.keys() if current[test] != required[test])
    counts = Counter(current.values())
    totals = {outcome: counts[outcome] for outcome in COVERAGE_OUTCOMES}
    return {
        "complete": bool(current) and not (missing or changed or totals["failed"]),
        "tests": len(current), **totals,
        "baseline": {"required": len(required), "matched": len(required) - len(missing) - len(changed),
                     "missing": missing, "outcome_changed": changed},
        "report": str(report),
    }


def gate_status(root, gate, candidate, final):
    gate_id = gate["id"]
    if not isinstance(gate_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", gate_id):
        raise ValueError("Invalid gate identifier")
    latest = root / f"gate-{gate_id}.json"
    request = gate["request"]
    result = {"id": gate_id, "scope": request["scope"]}
    try:
        run, receipt = latest_run(root, latest)
        owner = receipt.get("owner", "controller")
        result.update(receipt=str(run / "run.json"), exit_code=receipt["exit_code"], owner=owner)
        if owner not in (gate.get("owner", "controller"), "controller"):
            return dict(result, status="unverified", reason="receipt owner does not match the gate assignment")
        if receipt["status"] != "finished":
            return dict(result, status="pending", reason=receipt["status"])
        if receipt["exit_code"] != 0:
            output = receipt["output"]
            current_failure = (receipt["candidate"] == candidate and receipt.get("request") == request
                               and receipt.get("inputs_before") is not None
                               and fingerprint(request["fingerprint_command"]) == receipt["inputs_before"]
                               and output["path"] == "output.log" and output["status"] == "complete"
                               and digest(run / "output.log") == output["sha256"])
            if read_json(latest) != run.name:
                return dict(result, status="pending", reason="latest attempt changed during validation")
            return dict(result, status="failed", reason="latest attempt failed", current_failure=current_failure)
        current = fingerprint(request["fingerprint_command"])
        if current is None:
            return dict(result, status="unverified", reason="current fingerprint unavailable")
        if receipt["inputs_before"] != current or receipt["inputs_after"] != current:
            return dict(result, status="stale", reason="gate inputs or runtime changed")
        if not matches_pass(run, receipt, request, current):
            return dict(result, status="unverified", reason="request or retained output does not match")

        result.update(output=str(run / "output.log"), coverage=receipt["coverage"],
                      artifacts={name: str(run / f"artifact-{index}")
                                 for index, name in enumerate(request["artifacts"])})
        if "coverage" in gate:
            verified = verified_coverage(root, run, receipt, request, gate["coverage"])
            result["coverage"]["verified"] = verified
            if not verified["complete"]:
                return dict(result, status="unverified", reason="required test coverage did not pass")
        status = "reusable"
        if final:
            if gate.get("reuse"):
                reuse_path = evidence_path(root, gate["reuse"])
                reuse = read_json(reuse_path)
                expected = {"gate": gate_id, "candidate": candidate, "source_run_id": run.name,
                            "source_receipt_sha256": digest(run / "run.json"), "inputs": current}
                if any(reuse[key] != value for key, value in expected.items()):
                    return dict(result, status="unverified", reason="reuse decision does not match the latest pass")
                result["reuse"] = str(reuse_path)
                status = "reused"
            elif receipt["candidate"] == candidate:
                status = "passed"
        if read_json(latest) != run.name:
            return dict(result, status="pending", reason="latest attempt changed during validation")
        return dict(result, status=status)
    except FileNotFoundError:
        if not latest.exists():
            return dict(result, status="missing", reason="no recorded attempt")
        return dict(result, status="unverified", reason="receipt or original output missing")
    except (OSError, KeyError, TypeError, ValueError):
        return dict(result, status="unverified", reason="invalid receipt or unavailable evidence")


def preview_status(preview):
    if preview is None:
        return {"status": "not-applicable"}
    surface = preview["surface"]
    approved = preview.get("approved_surface")
    if not isinstance(surface, str) or not surface.strip():
        raise ValueError("A UI handoff needs a current surface fingerprint")
    status = "current" if approved == surface else "stale" if approved else "missing"
    return {"status": status, "surface": surface, "approved_surface": approved,
            "waiver": preview.get("waiver"), "decision_reference": preview.get("decision_reference")}


def resume_route(task, packet):
    state = task.get("resume_state")
    preview = packet["preview"]
    preview_current = (preview["status"] == "not-applicable" or
                       (preview["status"] == "current" and preview["decision_reference"]))
    if (isinstance(state, dict) and state.get("phase") == "awaiting_final_review"
            and all(state.get(key) is False for key in ("pending_work", "pending_decisions", "active_processes"))
            and not packet["candidate_changed"] and not packet["blockers"] and preview_current):
        return "final_review"
    return "resume_work"


def configured_gates(gates):
    if not isinstance(gates, list):
        raise ValueError("The handoff needs a required gate list")
    if len({gate["id"] for gate in gates}) != len(gates):
        raise ValueError("Required gate identifiers must be unique")
    if any(gate.get("phase", "authoritative") not in ("cheap", "authoritative") for gate in gates):
        raise ValueError("Gate phase must be cheap or authoritative")
    if any(gate.get("owner", "controller") not in ("worker", "controller") for gate in gates):
        raise ValueError("Gate owner must be worker or controller")
    return gates


def check_plan(task, root):
    candidate = task["candidate"]
    if not isinstance(candidate, str) or not candidate.strip():
        raise ValueError("The check plan needs a candidate identity")
    checks = []
    for gate in configured_gates(task["gates"]):
        check = gate_status(root, gate, candidate, final=True)
        action = {"passed": "carry", "reused": "carry", "reusable": "reuse"}.get(check["status"], "run")
        if check.get("current_failure"):
            action = "repair"
        elif check["status"] == "pending" and check["reason"] not in ("interrupted", "unavailable"):
            action = "wait"
        checks.append(dict(check, action=action, assigned_owner=gate.get("owner", "controller")))
    return {"candidate": candidate, "checks": checks}


def implementation_brief(task):
    brief = {"scope": task["scope"], "acceptance": task["acceptance"], "delivery": task["delivery"]}
    checks = []
    for gate in configured_gates(task["gates"]):
        owner = gate.get("owner", "controller")
        check = {"id": gate["id"], "phase": gate.get("phase", "authoritative"),
                 "owner": owner, "scope": gate["request"]["scope"]}
        if owner == "worker" and "invocation" in gate:
            check["invocation"] = gate["invocation"]
        checks.append(check)
    brief["checks"] = checks
    brief["early_code"] = EARLY_CODE_CRITERIA if task.get("early_code") is None else task["early_code"]
    if task.get("preview") is not None:
        brief["preview"] = task["preview"]
    return brief


def code_review_packet(task, root):
    candidate = task["candidate"]
    if not isinstance(candidate, str) or not candidate.strip():
        raise ValueError("The CODE review needs a candidate identity")
    diff = evidence_path(root, task["diff"])
    packet = {"action": "start", "candidate": candidate, "diff": {"path": str(diff), "sha256": digest(diff)}}
    packet.update({key: task[key] for key in ("scope", "acceptance") if key in task})
    cheap = [gate_status(root, gate, candidate, final=True)
             for gate in configured_gates(task.get("gates", [])) if gate.get("phase") == "cheap"]
    if cheap:
        packet["cheap_checks"] = cheap
        blockers = [check["id"] for check in cheap if check["status"] not in ("passed", "reused")]
        if blockers:
            return dict(packet, action="blocked", blockers=blockers)
    prior = task.get("early_review")
    if (not isinstance(prior, dict) or prior.get("scope_unchanged") is not True
            or prior.get("verdict") != "REVISE"):
        return packet
    session = prior.get("session")
    reviewed = prior.get("candidate")
    if (not all(isinstance(value, str) and value.strip() for value in (session, reviewed))
            or reviewed == candidate):
        return packet
    try:
        findings = evidence_path(root, prior["findings"])
        repair = evidence_path(root, prior["repair_diff"])
        if not findings.stat().st_size or not repair.stat().st_size:
            return packet
        repair_sha = digest(repair)
        findings_sha = digest(findings)
    except (OSError, KeyError, TypeError, ValueError):
        return packet
    packet.update(action="resume", session=session, reviewed_candidate=reviewed,
                  findings={"path": str(findings), "sha256": findings_sha},
                  repair_diff={"path": str(repair), "sha256": repair_sha})
    return packet


def build_packet(task, root, final):
    candidate = task["candidate"]
    saved = task.get("saved_candidate")
    preview = preview_status(task["preview"])
    gates = configured_gates(task["gates"])
    if not isinstance(candidate, str) or not candidate.strip():
        raise ValueError("The handoff needs a candidate identity")
    checks = [gate_status(root, gate, candidate, final) for gate in gates]
    accepted = {"passed", "reused"} if final else {"reusable"}
    blockers = [check["id"] for check in checks if check["status"] not in accepted]
    if preview["status"] in ("stale", "missing") and not preview["waiver"]:
        blockers.append("preview approval")
    packet = {
        "candidate": candidate, "saved_candidate": saved, "candidate_changed": saved != candidate,
        "preview": preview, "checks": checks, "blockers": blockers,
    }
    if final:
        diff = evidence_path(root, task["diff"])
        packet.update(diff={"path": str(diff), "sha256": digest(diff)},
                      acceptance=task["acceptance"], decisions=task.get("decisions", []),
                      findings=task.get("findings", []), delivery=task["delivery"],
                      ready_for_review=not blockers)
        if "scope" in task:
            packet["scope"] = task["scope"]
    else:
        packet["route"] = resume_route(task, packet)
    return packet


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("resume", "review", "code-review", "checks", "brief"))
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path)
    args = parser.parse_args()
    if args.mode != "brief" and args.evidence_dir is None:
        parser.error("--evidence-dir is required for receipt and review commands")
    final = args.mode == "review"
    try:
        task = read_json(args.task)
        if args.mode == "brief":
            packet = implementation_brief(task)
        else:
            root = args.evidence_dir.resolve(strict=True)
            if args.mode == "checks":
                packet = check_plan(task, root)
            elif args.mode == "code-review":
                packet = code_review_packet(task, root)
            else:
                packet = build_packet(task, root, final)
    except (OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(2, f"Cannot build handoff packet: {error}\n")
    print(json.dumps(packet, indent=2))
    return int(packet.get("action") == "blocked" or (final and not packet["ready_for_review"]))


if __name__ == "__main__":
    raise SystemExit(main())
