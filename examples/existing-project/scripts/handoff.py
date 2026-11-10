"""Summarize a saved SpringDev task or build its final review packet."""

import argparse
import json
import re
from pathlib import Path

from capture_check import digest, fingerprint, latest_run, matches_pass


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def evidence_path(root, name):
    path = (root / name).resolve()
    if root not in path.parents:
        raise ValueError(f"Evidence path escapes the task evidence root: {name}")
    return path


def gate_status(root, gate, candidate, final):
    gate_id = gate["id"]
    if not isinstance(gate_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", gate_id):
        raise ValueError("Invalid gate identifier")
    latest = root / f"gate-{gate_id}.json"
    request = gate["request"]
    result = {"id": gate_id, "scope": request["scope"]}
    try:
        run, receipt = latest_run(root, latest)
        result.update(receipt=str(run / "run.json"), exit_code=receipt["exit_code"])
        if receipt["status"] != "finished":
            return dict(result, status="pending", reason=receipt["status"])
        if receipt["exit_code"] != 0:
            return dict(result, status="failed", reason="latest attempt failed")
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


def build_packet(task, root, final):
    candidate = task["candidate"]
    saved = task.get("saved_candidate")
    preview = preview_status(task["preview"])
    gates = task["gates"]
    if not isinstance(candidate, str) or not candidate.strip() or not isinstance(gates, list):
        raise ValueError("The handoff needs a candidate identity and a required gate list")
    if len({gate["id"] for gate in gates}) != len(gates):
        raise ValueError("Required gate identifiers must be unique")
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
    return packet


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("resume", "review"))
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    final = args.mode == "review"
    try:
        packet = build_packet(read_json(args.task), args.evidence_dir.resolve(strict=True), final)
    except (OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(2, f"Cannot build handoff packet: {error}\n")
    print(json.dumps(packet, indent=2))
    return int(final and not packet["ready_for_review"])


if __name__ == "__main__":
    raise SystemExit(main())
