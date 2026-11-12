"""Auditable refutation of a claim, distinct from repair or an owner waiver."""

import hashlib
import json

from capture_check import digest
from proof import identifier, nonempty, read, retained_artifact, report_tests, test_names

GROUPS = {"test-request": "requests", "functional-finding": "findings", "challenge-case": "cases"}


def key(kind, identity):
    if kind not in GROUPS:
        raise ValueError("Unknown withdrawal kind")
    return kind + ":" + identifier(identity)


def value_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def original(task, root, state, kind, identity):
    if kind == "challenge-case":
        from behavior import challenge_ledger, challenge_brief
        plan = challenge_ledger(root)
        if not plan or plan["scope_sha256"] != challenge_brief(task)["scope_sha256"]:
            raise ValueError("Withdrawal needs this task's independent challenge plan")
        item = plan["cases"][identity]
        path = root / "challenges" / (item["plan_sha256"] + ".json")
        data = read(path)
        if digest(path) != item["plan_sha256"] or item["spec"] not in data["cases"]:
            raise ValueError("Original challenge provenance is invalid")
        return dict(item, candidate=read(root / "acceptance-contract.json")["baseline_candidate"],
                    original_sha256=item["plan_sha256"])
    item = state[GROUPS[kind]][identity]
    path = root / "reviews" / (item["review_sha256"] + ".json")
    review = read(path)
    field = "test_requests" if kind == "test-request" else "findings"
    if (digest(path) != item["review_sha256"] or item["spec"] not in review[field]
            or review["candidate"] != item["candidate"] or review["role"] != item["role"]):
        raise ValueError("Original review provenance is invalid")
    return dict(item, original_sha256=item["review_sha256"])


def proposal(task, root, state, kind, identity, supplied=None):
    from behavior import challenge_brief
    original_item = original(task, root, state, kind, identity)
    value = supplied if supplied is not None else task.get("withdrawal_proposals", {})[key(kind, identity)]
    if (value["original_sha256"] != original_item["original_sha256"]
            or value["scope_sha256"] != challenge_brief(task)["scope_sha256"]):
        raise ValueError("Refutation is not bound to the original claim and task scope")
    nonempty(value["assertion"])
    nonempty(value["reference"])
    receipt, report = retained_artifact(root, value["receipt"], value["report"])
    if (receipt["candidate"] != original_item["candidate"] or receipt["exit_code"] != 0
            or receipt["started_at"] < original_item["recorded_at"]
            or not test_names(value["tests"]) <= report_tests(report, "passed")
            or value["spec"] == value["report"]
            or value["spec"] not in receipt["artifacts"]):
        raise ValueError("Refutation needs post-claim controller evidence on the original product")
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    facts = {"proposal_sha256": hashlib.sha256(raw).hexdigest(),
             "receipt_sha256": digest(root / value["receipt"]),
             "spec_sha256": receipt["artifacts"][value["spec"]],
             "original_sha256": original_item["original_sha256"]}
    return value, facts


def verified(task, root, state, kind, identity):
    saved = state.get("withdrawals", {}).get(key(kind, identity))
    if saved is None:
        return False
    try:
        _, facts = proposal(task, root, state, kind, identity, saved["proposal"])
        if facts != saved["evidence"]:
            return False
        path = root / "reviews" / (saved["review_sha256"] + ".json")
        review = read(path)
        return (digest(path) == saved["review_sha256"]
                and review["role"] in ("CODE", "EVIDENCE")
                and saved["acknowledgment"]["proposal_sha256"] == facts["proposal_sha256"]
                and key(saved["acknowledgment"]["kind"], saved["acknowledgment"]["id"]) == key(kind, identity)
                and saved["acknowledgment"] in review["withdrawals"])
    except (OSError, KeyError, TypeError, ValueError):
        return False


def acknowledge(task, root, state, review, source):
    """Validate every acknowledgment before the caller commits the ledger."""
    rows = review.get("withdrawals", [])
    if not isinstance(rows, list):
        raise ValueError("Withdrawals must be an explicit reviewer acknowledgment list")
    additions, history, seen = {}, [], set()
    for row in rows:
        identity = key(row["kind"], row["id"])
        if identity in seen:
            raise ValueError("Duplicate withdrawal acknowledgment")
        seen.add(identity)
        nonempty(row["reason"])
        value, facts = proposal(task, root, state, row["kind"], row["id"])
        if row["proposal_sha256"] != facts["proposal_sha256"]:
            raise ValueError("Reviewer did not acknowledge this exact refutation proposal")
        saved = state.get("withdrawals", {}).get(identity)
        if saved:
            if saved["evidence"] == facts and saved["proposal"] == value:
                continue
            if row.get("supersedes") != value_hash(saved):
                raise ValueError("A retained withdrawal needs an explicit independently acknowledged revision")
            history.append({"key": identity, "value": saved, "superseded_by": source})
        additions[identity] = {"proposal": value, "evidence": facts,
                               "review_sha256": source, "acknowledgment": row}
    return additions, history


def pending(task, root, state, kind, identity):
    """Counterevidence can open a disposition review, never final approval."""
    if key(kind, identity) not in task.get("withdrawal_proposals", {}):
        return None
    try:
        _, facts = proposal(task, root, state, kind, identity)
        return facts
    except (OSError, KeyError, TypeError, ValueError):
        return None


def review_packet(task, root, checks, state):
    """A bounded claim review cannot be mistaken for final approval."""
    cheap = {gate["id"] for gate in task["gates"] if gate.get("phase") == "cheap"}
    blockers = [check["id"] for check in checks
                if check["id"] in cheap and check["status"] not in ("passed", "reused")]
    rows = []
    for identity in task.get("withdrawal_proposals", {}):
        try:
            kind, name = identity.split(":", 1)
            value, facts = proposal(task, root, state, kind, name)
            rows.append({"id": name, "kind": kind, "proposal": value, "evidence": facts,
                         "original": original(task, root, state, kind, name)})
        except (OSError, KeyError, TypeError, ValueError) as error:
            blockers.append("refutation:" + identity)
            rows.append({"id": identity, "reason": str(error)})
    if not rows:
        blockers.append("withdrawal proposals")
    return {"candidate": task["candidate"], "action": "blocked" if blockers else "start",
            "purpose": "disposition", "proposals": rows, "blockers": blockers,
            "instructions": "Judge the original claim against controller counterevidence; acknowledge exact proposal hashes. Return phase disposition. A separate full final review remains required."}
