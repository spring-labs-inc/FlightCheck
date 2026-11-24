"""Offline evidence-inspection calibration; never launches model/provider sessions.

The controller owns manifests, oracle and captures.  The reader is an instrument,
not a security boundary.  Measured sessions require an external boundary report.
"""
import argparse
import base64
import copy
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time

SCHEMA = "evidence-inspection-v1"
BASELINE_PIN = "ee869f9a3c03c8c048ad778d7465d9c31e70f970"
INCREMENTAL_PIN = "c69bbfe364ac01c9a13b46cb983f0c4ffd2c5e33"
DEFAULT_SUITE = Path(__file__).with_name("evidence-inspection-v1.json")
REPO = Path(__file__).resolve().parents[1]
SCHEDULE = [{"stage": "CODE", "role": "CODE", "independent": False},
            {"stage": "FINAL", "role": "EVIDENCE", "independent": True}]
HEX = re.compile(r"[0-9a-f]{64}\Z")
IDENT = re.compile(r"[A-Za-z0-9_-]+\Z")
MAX_FILE = 16 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024
BUCKETS = ("setup", "view_preparation", "supervision", "provider_wait", "queue_wait",
           "tool_wait", "repair", "rerun")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def exact(obj, keys, label):
    if not isinstance(obj, dict) or set(obj) != set(keys):
        raise ValueError(f"{label}: expected fields {sorted(keys)}")
    return obj


def text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}: nonempty string required")
    return value


def digest_string(value):
    if not isinstance(value, str) or not HEX.fullmatch(value):
        raise ValueError("SHA-256 required")
    return value


def identifier(value):
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise ValueError("opaque identifier required")
    return value


def relative(value):
    text(value, "relative path")
    p = PurePosixPath(value)
    if p.is_absolute() or any(part in ("", ".", "..") for part in value.split("/")) or "\\" in value:
        raise ValueError("unsafe relative path")
    return value


def no_symlinks(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError("symlink path refused")
    return path


def read_bytes(path):
    path = no_symlinks(path)
    # O_NOFOLLOW plus fstat prevents leaf replacement from following an alias.
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE:
            raise ValueError("bounded regular file required")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(MAX_FILE + 1)
        if len(raw) > MAX_FILE:
            raise ValueError("file size limit")
        return raw
    finally:
        os.close(fd)


def read_json(path):
    def pairs(rows):
        out = {}
        for key, value in rows:
            if key in out:
                raise ValueError("duplicate JSON key")
            out[key] = value
        return out
    return json.loads(read_bytes(path), object_pairs_hook=pairs,
                      parse_constant=lambda v: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def write_json(path, value):
    Path(path).write_bytes(json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n")


def private_output(path, forbidden=()):
    path = no_symlinks(path)
    resolved = path.resolve()
    for root in (REPO, *(Path(p).resolve() for p in forbidden)):
        if resolved == root or root in resolved.parents:
            raise ValueError("output must be private and outside source roots")
    if path.exists():
        raise ValueError("output already exists")
    path.mkdir(mode=0o700, parents=False)
    return path


def _unique(items, key="id"):
    ids = [identifier(item[key]) for item in items]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("empty or duplicate identifiers")


def validate_oracle(oracle):
    exact(oracle, ("clean", "defects"), "oracle")
    if type(oracle["clean"]) is not bool or not isinstance(oracle["defects"], list):
        raise ValueError("invalid oracle")
    if oracle["clean"] != (not oracle["defects"]):
        raise ValueError("oracle clean/defects disagree")
    seen = set()
    for defect in oracle["defects"]:
        exact(defect, ("id", "claim", "category", "references", "discrepancy", "repair", "critical"), "defect")
        for field in ("id", "claim", "category"):
            identifier(defect[field])
        for field in ("discrepancy", "repair"):
            text(defect[field], field)
        if type(defect["critical"]) is not bool or not defect["references"] or not isinstance(defect["references"], list):
            raise ValueError("invalid defect references/criticality")
        if len(set(defect["references"])) != len(defect["references"]):
            raise ValueError("duplicate defect reference")
        for ref in defect["references"]:
            identifier(ref)
        if defect["id"] in seen:
            raise ValueError("duplicate defect")
        seen.add(defect["id"])
    return oracle


def validate_suite(suite):
    exact(suite, ("schema", "kind", "conditions", "schedule", "cases", "cohort_proposal"), "suite")
    if suite["schema"] != SCHEMA or suite["kind"] != "synthetic-calibration":
        raise ValueError("unknown suite schema or kind")
    if suite["conditions"] != [{"id": "baseline", "pin": BASELINE_PIN}, {"id": "incremental", "pin": INCREMENTAL_PIN}]:
        raise ValueError("actual comparison pins required")
    if suite["schedule"] != SCHEDULE:
        raise ValueError("matched CODE and independent final required")
    _unique(suite["cases"])
    for case in suite["cases"]:
        exact(case, ("id", "variant", "artifacts", "claims", "oracle"), "case")
        text(case["variant"], "variant")
        _unique(case["artifacts"])
        _unique(case["claims"])
        paths = set()
        for item in case["artifacts"]:
            exact(item, ("id", "path", "content", "necessary", "coverage"), "artifact")
            relative(item["path"])
            if item["path"] in paths or item["path"] == "view.json":
                raise ValueError("duplicate/reserved path")
            paths.add(item["path"])
            if not isinstance(item["content"], str) or type(item["necessary"]) is not bool or not isinstance(item["coverage"], list):
                raise ValueError("invalid artifact")
        aids = {a["id"] for a in case["artifacts"]}
        cids = {c["id"] for c in case["claims"]}
        for item in case["claims"]:
            exact(item, ("id", "artifact_ids"), "claim")
            if not item["artifact_ids"] or not set(item["artifact_ids"]) <= aids:
                raise ValueError("unbound claim")
        for item in case["artifacts"]:
            if not set(item["coverage"]) <= cids:
                raise ValueError("unknown coverage")
        validate_oracle(case["oracle"])
        for defect in case["oracle"]["defects"]:
            if defect["claim"] not in cids or not set(defect["references"]) <= aids:
                raise ValueError("unbound oracle")
    validate_cohort(suite["cohort_proposal"])
    return suite


def load_suite(path=DEFAULT_SUITE):
    return validate_suite(read_json(path))


def _bound(ref):
    exact(ref, ("path", "sha256"), "file binding")
    digest_string(ref["sha256"])
    path = no_symlinks(ref["path"])
    if not path.is_absolute():
        raise ValueError("absolute private source required")
    raw = read_bytes(path)
    if sha(raw) != ref["sha256"]:
        raise ValueError("bound file digest drift")
    return raw



def validate_view(view):
    exact(view, ("schema", "kind", "case_id", "condition", "artifacts", "candidate", "source_pin", "created_ns"), "view")
    if view["schema"] != SCHEMA or view["kind"] != "reviewer-view" or view["condition"] not in ("baseline", "incremental"):
        raise ValueError("invalid view schema/condition")
    identifier(view["case_id"])
    text(view["candidate"], "candidate")
    if not re.fullmatch(r"(?:[0-9a-f]{40}|synthetic:[0-9a-f]{64})", view["source_pin"]):
        raise ValueError("source pin required")
    if type(view["created_ns"]) is not int or view["created_ns"] < 0:
        raise ValueError("creation timestamp required")
    _unique(view["artifacts"])
    seen = set()
    for row in view["artifacts"]:
        exact(row, ("id", "path", "sha256", "bytes", "necessary", "coverage"), "view artifact")
        relative(row["path"])
        if row["path"] in seen or row["path"] == "view.json":
            raise ValueError("duplicate/reserved view path")
        seen.add(row["path"])
        digest_string(row["sha256"])
        if type(row["bytes"]) is not int or not 0 <= row["bytes"] <= MAX_FILE or type(row["necessary"]) is not bool:
            raise ValueError("invalid view artifact metadata")
        if not isinstance(row["coverage"], list):
            raise ValueError("invalid view coverage")
        for claim in row["coverage"]:
            identifier(claim)
    return view


def read_artifact(view_path, artifact_id, *, offset=0, length=None, role, session,
                  phase="inspection", events_path):
    """Return actual bytes and append one event per read, including repeats.

    Event log must be controller-owned OUTSIDE the reviewer view.  Its external
    immutability/ownership is a measured-session adapter responsibility.
    """
    view_path = no_symlinks(view_path)
    view = validate_view(read_json(view_path))
    identifier(artifact_id)
    identifier(session)
    if role not in ("CODE", "EVIDENCE") or phase not in ("inspection", "probe"):
        raise ValueError("invalid reader role/phase")
    if type(offset) is not int or offset < 0 or (length is not None and (type(length) is not int or length < 0)):
        raise ValueError("invalid byte range")
    rows = [row for row in view["artifacts"] if row["id"] == artifact_id]
    if len(rows) != 1:
        raise ValueError("artifact not allowlisted")
    row = rows[0]
    root = view_path.parent.resolve()
    events = no_symlinks(events_path)
    if root == events or root in events.parents or events == view_path:
        raise ValueError("events belong outside reviewer view")
    started = time.monotonic_ns()
    raw = read_bytes(root / row["path"])
    if len(raw) != row["bytes"] or sha(raw) != row["sha256"]:
        raise ValueError("artifact binding drift")
    result = raw[offset:] if length is None else raw[offset:offset + length]
    event = {"schema": SCHEMA, "kind": "read-event", "view_sha256": sha(read_bytes(view_path)),
             "artifact": artifact_id, "artifact_sha256": row["sha256"], "offset": offset,
             "requested_length": length, "bytes": len(result), "returned_sha256": sha(result),
             "role": role, "session": session, "phase": phase, "wall_time_ns": time.time_ns(),
             "started_ns": started, "finished_ns": time.monotonic_ns()}
    fd = os.open(events, os.O_APPEND | os.O_CREAT | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("regular controller log required")
        os.write(fd, canonical(event) + b"\n")
    finally:
        os.close(fd)
    return {"data": result, "event": event}


def validate_boundary(report, view_sha256, session, decision_time_ns):
    """Validate an adapter observation; this function cannot create a sandbox."""
    exact(report, ("schema", "view_sha256", "session", "observer", "synthetic", "observed_ns",
                   "boundary", "probes", "tools", "reads_instrumented"), "external boundary report")
    if report["schema"] != SCHEMA or report["view_sha256"] != view_sha256 or report["session"] != session:
        raise ValueError("wrong session/view boundary report")
    if report["synthetic"] is not False or report["observer"] != "external-reviewer-session":
        raise ValueError("actual external reviewer observation required")
    if type(report["observed_ns"]) is not int or report["observed_ns"] >= decision_time_ns:
        raise ValueError("boundary probes must precede decision")
    exact(report["boundary"], ("read_only", "write_rejected"), "boundary")
    if report["boundary"] != {"read_only": True, "write_rejected": True}:
        raise ValueError("read-only boundary unverified")
    exact(report["probes"], ("allowed_read", "oracle_denied", "other_condition_denied", "write_denied", "necessary_access"), "probes")
    if not all(report["probes"][key] is True for key in ("allowed_read", "oracle_denied", "other_condition_denied", "write_denied")):
        raise ValueError("external boundary probe failure")
    if not isinstance(report["tools"], list) or not report["tools"] or type(report["reads_instrumented"]) is not bool:
        raise ValueError("tool/read coverage declaration required")
    return {"access_sufficient": report["probes"]["necessary_access"] is True,
            "telemetry_complete": report["reads_instrumented"]}


def score_decision(oracle, review):
    """Conservative structured extraction; prose is retained separately for audit."""
    validate_oracle(oracle)
    exact(review, ("verdict", "findings", "native_output", "matcher"), "review extraction")
    if review["verdict"] not in ("APPROVE", "BLOCK", "INCOMPLETE") or review["matcher"] != "structured-exact-v1":
        raise ValueError("unknown review verdict/matcher")
    text(review["native_output"], "complete retained native output")
    if not isinstance(review["findings"], list):
        raise ValueError("findings list required")
    detected, repaired = set(), set()
    false_alarms, uncertain_findings = 0, 0
    for finding in review["findings"]:
        fields = ("claim", "category", "references", "discrepancy", "repair", "narrative")
        if isinstance(finding, dict) and "assessment" in finding:
            exact(finding, (*fields, "assessment"), "finding extraction")
            if finding["assessment"] not in ("supported", "uncertain"):
                raise ValueError("unknown additional-claim assessment")
        else:
            exact(finding, fields, "finding extraction")
        if not isinstance(finding["references"], list) or any(not isinstance(x, str) for x in finding["references"]):
            raise ValueError("references list required")
        if any(not isinstance(finding[key], str) for key in ("claim", "category", "discrepancy", "repair", "narrative")):
            raise ValueError("text extraction fields required")
        if finding.get("assessment") == "uncertain":
            uncertain_findings += 1
            continue
        matches = [d for d in oracle["defects"] if all(finding[k] == d[k] for k in ("claim", "category", "discrepancy"))
                   and set(d["references"]) <= set(finding["references"]) and finding["narrative"].strip()]
        if not matches:
            false_alarms += 1
        for defect in matches:
            detected.add(defect["id"])
            if finding["repair"] == defect["repair"]:
                repaired.add(defect["id"])
    false_approval = review["verdict"] == "APPROVE" and bool(oracle["defects"])
    critical_escape = false_approval and any(d["critical"] for d in oracle["defects"])
    clean_approval = oracle["clean"] and review["verdict"] == "APPROVE" and not false_alarms
    return {"schema": SCHEMA, "kind": "sanitized-decision-score", "specific_detected": len(detected),
            "actionable_repairs": len(repaired), "misses": len(oracle["defects"]) - len(detected),
            "false_alarms": false_alarms, "uncertain_findings": uncertain_findings, "false_approval": false_approval,
            "critical_false_approval": critical_escape, "false_block": oracle["clean"] and review["verdict"] == "BLOCK",
            "correct_clean_approval": clean_approval, "incomplete": review["verdict"] == "INCOMPLETE",
            "generic_block": review["verdict"] == "BLOCK" and not detected,
            "quality_pass": clean_approval or (not oracle["clean"] and not false_approval
                                               and len(detected) == len(oracle["defects"]) and not false_alarms),
            "quality_accepted": False, "semantic_audit_required": True, "semantic_matcher_uncertainty": "Structured exact extraction is provisional; independent prose audit is required.",
            "acceptable_efficiency_claim": False}


def normalize_historical_oracle(import_spec, case_id, crosswalk_path):
    """Validate an explicitly DERIVED private rubric crosswalk, never replace
    the preserved key or automatically interpret arbitrary historical prose."""
    verified = verify_import(import_spec)
    crosswalk = read_json(crosswalk_path)
    validate_crosswalk(crosswalk)
    original = verified["spec"]["oracle"]["sha256"]
    views = [v for v in verified["views"] if v["id"] == case_id]
    if len(views) != 1 or crosswalk["case_id"] != case_id or crosswalk["candidate"] != views[0]["candidate"] or crosswalk["original_oracle_sha256"] != original:
        raise ValueError("crosswalk is bound to another preserved oracle/candidate")
    validate_source_references(crosswalk, {row["id"]: row for row in views[0]["files"]},
                               Path(views[0]["root"]))
    return {"oracle": crosswalk["oracle"], "original_oracle_sha256": original,
            "crosswalk_sha256": sha(read_bytes(crosswalk_path)), "provisional": True,
            "semantic_audit_required": True}



def validate_source_references(crosswalk, inventory, root):
    """Bind each source location to its exact selected artifact, optionally
    with one-based physical file lines (:first or :first-last)."""
    refs = {row["artifact_id"] for row in crosswalk["source_references"]}
    if not refs <= set(inventory) or any(not set(d["references"]) <= refs for d in crosswalk["oracle"]["defects"]):
        raise ValueError("crosswalk source references are outside the selected view")
    for reference in crosswalk["source_references"]:
        artifact = inventory[reference["artifact_id"]]
        match = re.fullmatch(re.escape(artifact["path"]) + r"(?::([1-9][0-9]*)(?:-([1-9][0-9]*))?)?", reference["location"])
        if match is None:
            raise ValueError("crosswalk source location does not match its selected artifact")
        if match.group(1) is not None:
            first = int(match.group(1))
            last = int(match.group(2) or match.group(1))
            raw = read_bytes(root / artifact["path"])
            if sha(raw) != artifact["sha256"] or last < first or last > len(raw.splitlines()):
                raise ValueError("crosswalk source line range is outside its sealed artifact")


def validate_crosswalk(crosswalk):
    exact(crosswalk, ("schema", "kind", "original_oracle_sha256", "case_id", "candidate", "oracle", "source_references", "adjudication"), "derived crosswalk")
    if crosswalk["schema"] != "evidence-inspection-crosswalk-v1" or crosswalk["kind"] != "derived-private-adjudication":
        raise ValueError("unknown crosswalk schema")
    digest_string(crosswalk["original_oracle_sha256"])
    identifier(crosswalk["case_id"])
    text(crosswalk["candidate"], "crosswalk candidate")
    validate_oracle(crosswalk["oracle"])
    if not isinstance(crosswalk["source_references"], list) or not crosswalk["source_references"]:
        raise ValueError("exact original source references required")
    for row in crosswalk["source_references"]:
        exact(row, ("artifact_id", "location"), "crosswalk source reference")
        identifier(row["artifact_id"])
        text(row["location"], "source location")
    exact(crosswalk["adjudication"], ("status", "source"), "adjudication")
    if crosswalk["adjudication"]["status"] not in ("provisional", "independent-audit"):
        raise ValueError("crosswalk adjudication status required")
    text(crosswalk["adjudication"]["source"], "retained actual adjudication source")
    return crosswalk


def proof_sensitive(observations):
    """A positive witness needs a retained negative control with the defect present."""
    exact(observations, ("defect_present_passed", "repair_passed", "same_assertion_sha256"), "sensitivity")
    if any(type(observations[key]) is not bool for key in observations):
        raise ValueError("sensitivity booleans required")
    return observations["same_assertion_sha256"] and not observations["defect_present_passed"] and observations["repair_passed"]


def _intervals(rows):
    if rows is None:
        return None
    if not isinstance(rows, list):
        raise ValueError("interval list or null required")
    out = []
    for row in rows:
        if not isinstance(row, list) or len(row) != 2 or any(type(x) not in (int, float) or not math.isfinite(x) for x in row) or row[1] < row[0]:
            raise ValueError("invalid interval")
        out.append(tuple(row))
    return out


def _union(rows):
    total, stop = 0, None
    for start, end in sorted(rows):
        total += end - max(start, stop if stop is not None else start) if stop is None or end > stop else 0
        stop = max(end, stop if stop is not None else end)
    return total


def account(attempts, events):
    """All attempts retained. Unknown counters/intervals propagate as null."""
    if not isinstance(attempts, list) or not attempts:
        raise ValueError("nonempty attempt ledger required")
    seen, per, all_active, session_active = set(), [], [], {}
    session_buckets = {key: {} for key in BUCKETS}
    for attempt in attempts:
        exact(attempt, ("id", "status", "role", "session", "active_intervals", "wall_interval", "buckets",
                        "tool_calls", "requests", "tokens", "quota", "presented_bytes"), "attempt")
        identifier(attempt["id"])
        if attempt["id"] in seen or attempt["status"] not in ("completed", "failed", "interrupted", "incomplete") or attempt["role"] not in ("CODE", "EVIDENCE"):
            raise ValueError("invalid/duplicate attempt")
        seen.add(attempt["id"])
        identifier(attempt["session"])
        exact(attempt["buckets"], BUCKETS, "accounting buckets")
        active = _intervals(attempt["active_intervals"])
        wall = _intervals([attempt["wall_interval"]]) if attempt["wall_interval"] is not None else None
        for key in ("tool_calls", "requests", "tokens", "quota", "presented_bytes"):
            value = attempt[key]
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                raise ValueError("nonnegative observed counter or null required")
        bucket_intervals = {key: _intervals(rows) for key, rows in attempt["buckets"].items()}
        buckets = {key: None if rows is None else _union(rows) for key, rows in bucket_intervals.items()}
        for key, rows in bucket_intervals.items():
            if rows is not None:
                session_buckets[key].setdefault(attempt["session"], []).extend(rows)
        per.append({"id": attempt["id"], "status": attempt["status"], "role": attempt["role"], "session": attempt["session"],
                    "active_seconds": None if active is None else _union(active),
                    "elapsed_seconds": None if wall is None else _union(wall), "buckets": buckets,
                    **{key: attempt[key] for key in ("tool_calls", "requests", "tokens", "quota", "presented_bytes")}})
        if active is not None:
            all_active.extend(active)
            session_active.setdefault(attempt["session"], []).extend(active)
    def summed(key):
        return None if any(row[key] is None for row in per) else sum(row[key] for row in per)
    inspection = [e for e in events if e.get("phase") == "inspection"] if events is not None else None
    probes = [e for e in events if e.get("phase") == "probe"] if events is not None else None
    unique = {}
    if events is not None:
        for event in events:
            if event.get("schema") != SCHEMA or event.get("kind") != "read-event" or event.get("phase") not in ("inspection", "probe"):
                raise ValueError("invalid read event")
            if type(event.get("bytes")) is not int or event["bytes"] < 0 or type(event.get("offset")) is not int or event["offset"] < 0:
                raise ValueError("invalid returned byte range")
            digest_string(event["artifact_sha256"])
            if event["phase"] == "inspection":
                unique.setdefault(event["artifact_sha256"], []).append([event["offset"], event["offset"] + event["bytes"]])
    walls = [_intervals([a["wall_interval"]]) for a in attempts if a["wall_interval"] is not None]
    return {"schema": SCHEMA, "kind": "accounting", "attempts": per, "attempt_count": len(per),
            "session_launches": len({a["session"] for a in attempts}),
            "session_active_seconds": None if any(a["active_intervals"] is None for a in attempts) else sum(_union(rows) for rows in session_active.values()),
            "active_critical_path_seconds": None if any(a["active_intervals"] is None for a in attempts) else _union(all_active),
            "critical_path_elapsed_seconds": None if len(walls) != len(attempts) else _union([x for rows in walls for x in rows]),
            "buckets": {key: None if any(p["buckets"][key] is None for p in per) else sum(_union(rows) for rows in session_buckets[key].values()) for key in BUCKETS},
            **{key: summed(key) for key in ("tool_calls", "requests", "tokens", "quota", "presented_bytes")},
            "read_calls": None if inspection is None else len(inspection),
            "read_bytes": None if inspection is None else sum(e["bytes"] for e in inspection),
            "unique_read_bytes": None if inspection is None else sum(_union(rows) for rows in unique.values()),
            "repeat_read_bytes": None if inspection is None else sum(e["bytes"] for e in inspection) - sum(_union(rows) for rows in unique.values()),
            "probe_bytes": None if probes is None else sum(e["bytes"] for e in probes),
            "units": "seconds, bytes and native counters; no token, dollar or quota conversion"}



def validate_event_attribution(events, attempts, decision_time_ns):
    """Attribute reader observations only to declared reviewer role/session
    pairs before the frozen decision; accounting seconds have no epoch anchor."""
    if type(decision_time_ns) is not int or decision_time_ns < 0:
        raise ValueError("decision cutoff must be a nonnegative wall timestamp")
    declared = {(attempt["session"], attempt["role"]) for attempt in attempts}
    for event in events:
        if (event.get("session"), event.get("role")) not in declared:
            raise ValueError("read event does not belong to a declared reviewer session and role")
        observed = event.get("wall_time_ns")
        if type(observed) is not int or observed < 0 or observed > decision_time_ns:
            raise ValueError("read event is outside the decision cutoff")


def validate_cohort(cohort, *, approval=None):
    exact(cohort, ("schema", "kind", "conditions", "cases", "repetitions", "order", "schedule", "limits",
                   "model", "effort", "tools", "assistance", "cache", "endpoint", "exclusions", "oracle_sha256",
                   "prompt_sha256", "environment_sha256", "source_sha256", "workflow_sha256", "evidence_sha256"), "frozen cohort")
    if cohort["schema"] != SCHEMA or cohort["kind"] != "measured-cohort-proposal":
        raise ValueError("unknown cohort schema")
    if cohort["conditions"] != [{"id": "baseline", "pin": BASELINE_PIN}, {"id": "incremental", "pin": INCREMENTAL_PIN}] or cohort["schedule"] != SCHEDULE:
        raise ValueError("unmatched pinned conditions/stages")
    _unique(cohort["cases"])
    if not any(c.get("clean") is True for c in cohort["cases"]) or not any(c.get("clean") is False for c in cohort["cases"]):
        raise ValueError("clean and defective matrix required")
    for case in cohort["cases"]:
        exact(case, ("id", "clean", "private_variant_sha256"), "cohort case")
        if type(case["clean"]) is not bool:
            raise ValueError("case clean flag required")
        if case["private_variant_sha256"] is not None:
            digest_string(case["private_variant_sha256"])
    if type(cohort["repetitions"]) is not int or cohort["repetitions"] < 1:
        raise ValueError("positive repetition count required")
    expected = []
    for rep in range(cohort["repetitions"]):
        for case in cohort["cases"]:
            order = ["baseline", "incremental"] if (rep + len(expected) // 2) % 2 == 0 else ["incremental", "baseline"]
            expected.extend({"case": case["id"], "repetition": rep, "condition": arm} for arm in order)
    if cohort["order"] != expected:
        raise ValueError("complete frozen alternating pair order required")
    exact(cohort["limits"], ("seconds_per_attempt", "sessions_per_decision", "tool_calls_per_attempt", "attempts_per_cell"), "ceilings")
    if any(type(v) is not int or v < 1 for v in cohort["limits"].values()) or cohort["limits"]["sessions_per_decision"] < 2:
        raise ValueError("positive matched ceilings required")
    for key in ("model", "effort", "assistance", "cache", "endpoint", "exclusions"):
        text(cohort[key], key)
    if not isinstance(cohort["tools"], list) or not cohort["tools"]:
        raise ValueError("tool set required")
    for key in ("oracle_sha256", "prompt_sha256", "environment_sha256", "source_sha256", "workflow_sha256", "evidence_sha256"):
        if cohort[key] is not None:
            digest_string(cohort[key])
    frozen = all(cohort[key] is not None for key in ("oracle_sha256", "prompt_sha256", "environment_sha256", "source_sha256", "workflow_sha256", "evidence_sha256")) and all(c["private_variant_sha256"] is not None for c in cohort["cases"])
    authorized = False
    if approval is not None:
        exact(approval, ("schema", "authority", "grant", "cohort_sha256", "source"), "cohort approval")
        if not frozen:
            raise ValueError("unresolved cohort identities cannot authorize execution")
        authorized = approval["schema"] == SCHEMA and approval["authority"] == "owner" and approval["grant"] == "measured-cohort" and approval["cohort_sha256"] == sha(canonical(cohort)) and bool(text(approval["source"], "actual approval source"))
        if not authorized:
            raise ValueError("separate exact-cohort approval required")
    return {"valid": True, "frozen": frozen, "authorized": authorized, "cohort_sha256": sha(canonical(cohort)),
            "execution": "not implemented; external approved session adapter required"}


def _git(repo, *args):
    proc = subprocess.run(["git", "-C", str(repo), *args], stdin=subprocess.DEVNULL,
                          capture_output=True, timeout=20, check=False)
    if proc.returncode:
        raise ValueError("pinned git object unavailable")
    if len(proc.stdout) > MAX_TOTAL:
        raise ValueError("git object size limit")
    return proc.stdout


def snapshot_runtime(repo, pin, destination):
    if pin not in (BASELINE_PIN, INCREMENTAL_PIN):
        raise ValueError("unsupported workflow pin")
    resolved = _git(repo, "rev-parse", "--verify", pin + "^{commit}").decode().strip()
    if resolved != pin:
        raise ValueError("runtime pin mismatch")
    names = _git(repo, "ls-tree", "-r", "--name-only", pin, "workflow/scripts", "workflow/reviewers",
                 "workflow/docs/development-workflow.md", "workflow/skills/develop-change/SKILL.md").decode().splitlines()
    files = []
    for name in names:
        relative(name)
        raw = _git(repo, "show", f"{pin}:{name}")
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        files.append({"path": name, "sha256": sha(raw), "bytes": len(raw)})
    if not {"workflow/scripts/handoff.py", "workflow/scripts/proof.py", "workflow/scripts/capture_check.py"} <= {r["path"] for r in files}:
        raise ValueError("incomplete pinned runtime")
    return {"pin": pin, "files": files, "workflow_sha256": sha(canonical(files)),
            "python": {"executable_sha256": sha(read_bytes(Path(sys.executable).resolve())),
                       "version": sys.version, "implementation": sys.implementation.name}}


def exercise_runtime(repo, pin, output):
    """Bounded deterministic native CLI fixture, with ORIGINAL per-pin schemas.

    Access records and reviews here are controller-generated synthetic fixtures.
    They test runtime routing and are never real reviewer/boundary observations.
    """
    root = private_output(output)
    runtime = root / "runtime"
    runtime.mkdir()
    identity = snapshot_runtime(repo, pin, runtime)
    scripts = runtime / "workflow/scripts"
    checkout = root / "subject"
    checkout.mkdir()
    evidence = root / "evidence"
    evidence.mkdir(mode=0o700)
    manifest = evidence / "task.json"
    (evidence / "candidate.diff").write_text("Synthetic current full diff\n")
    for name in ("one", "two"):
        (checkout / name).write_text("original")
    gates = []
    for name in ("one", "two"):
        request = {"command": [sys.executable, "-B", "-c", "import sys; from pathlib import Path; sys.exit(Path('" + name + "').read_text()=='failure')"],
                   "scope": "Synthetic policy " + name, "summary": None,
                   "fingerprint_command": [sys.executable, "-B", "-c", "from pathlib import Path; print(Path('" + name + "').read_text())"],
                   "artifacts": []}
        gates.append({"id": name, "phase": "cheap", "request": request})
    task = {"candidate": "synthetic-A", "saved_candidate": "synthetic-A", "preview": None,
            "gates": gates, "diff": "candidate.diff", "scope": "Synthetic native runtime calibration",
            "acceptance": [{"id": name, "kind": "policy", "description": "Synthetic policy " + name,
                            "proofs": [{"kind": "check", "gate": name, "assertion": "Actual exit code is successful"}]} for name in ("one", "two")],
            "delivery": "Synthetic local-only fixture; no real review or landing"}
    calls, observations, states = [], {}, {}
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONDONTWRITEBYTECODE": "1",
           "LC_ALL": "C", "TMPDIR": tempfile.gettempdir()}

    def invoke(mode, label=None, extra=()):
        write_json(manifest, task)
        command = [sys.executable, "-B", str(scripts / "handoff.py"), mode,
                   "--task", str(manifest), "--evidence-dir", str(evidence), *extra]
        return run(command, mode, label)

    def run(command, mode, label):
        started = time.monotonic_ns()
        proc = subprocess.run(command, cwd=checkout, env=env, stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=20, check=False)
        index = len(calls)
        for suffix, raw in (("stdout", proc.stdout), ("stderr", proc.stderr)):
            (root / f"call-{index:03d}.{suffix}").write_bytes(raw)
        row = {"mode": mode, "label": label, "exit_code": proc.returncode,
               "command": command, "stdout": proc.stdout.decode(errors="replace"),
               "stderr": proc.stderr.decode(errors="replace"), "started_ns": started,
               "finished_ns": time.monotonic_ns(), "stdout_sha256": sha(proc.stdout),
               "stderr_sha256": sha(proc.stderr), "synthetic": True}
        calls.append(row)
        if proc.returncode not in (0, 1, 2) or (proc.returncode == 2 and label not in ("wrong_candidate", "wrong_basis")):
            raise ValueError(f"unexpected native {mode} status {proc.returncode}; inspect retained captures")
        try:
            value = json.loads(proc.stdout)
        except (ValueError, UnicodeError):
            value = {"exit_code": proc.returncode, "stdout": row["stdout"], "stderr": row["stderr"]}
        if label:
            observations[label] = value
            if label in ("initial", "unchanged_resume", "covered_duplicate", "navigation", "changed_input", "changed_claim", "contradiction", "unresolved", "necessary_missing", "tampered", "current_diff"):
                state = root / "states" / label
                state.mkdir(parents=True)
                shutil.copytree(evidence, state / "evidence")
                shutil.copytree(checkout, state / "source")
                packets = {}
                for stage_mode in ("code-review", "review"):
                    state_cmd = [sys.executable, "-B", str(scripts / "handoff.py"), stage_mode, "--task", str(manifest), "--evidence-dir", str(evidence)]
                    state_run = subprocess.run(state_cmd, cwd=checkout, env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=20)
                    if state_run.returncode not in (0, 1):
                        raise ValueError("native lifecycle state packet failed")
                    (state / (stage_mode + ".stdout")).write_bytes(state_run.stdout)
                    (state / (stage_mode + ".stderr")).write_bytes(state_run.stderr)
                    packets[stage_mode] = {"exit_code": state_run.returncode, "stdout_sha256": sha(state_run.stdout), "stderr_sha256": sha(state_run.stderr)}
                states[label] = {"root": str(state), "original_evidence_root": str(evidence), "original_source_root": str(checkout), "packets": packets,
                                 "synthetic_history": True, "real_review_observations": False}
        return value

    def capture(name, refresh=False):
        request = next(g for g in gates if g["id"] == name)["request"]
        return run([sys.executable, "-B", str(scripts / "capture_check.py"), "--gate", name,
                    "--scope", request["scope"], "--candidate", task["candidate"], "--owner", "controller",
                    "--fingerprint-command", json.dumps(request["fingerprint_command"]),
                    "--evidence-dir", str(evidence), *(["--refresh"] if refresh else []), "--", *request["command"]], "capture", None)

    def access(mode="review", *, unreadable=None):
        packet = invoke(mode)
        inc = packet.get("incremental_evidence")
        if inc is not None:
            rows = []
            for item in inc["access_manifest"]["files"]:
                path = Path(item["path"])
                raw = path.read_bytes() if path.is_file() else None
                rows.append({"path": str(path), "sha256": sha(raw) if raw is not None else None,
                             "readable": raw is not None and str(path) != unreadable})
            write_json(evidence / "reviewer-access.json", {"manifest_sha256": inc["access_manifest_sha256"],
                       "session": "synthetic-controller-probe-NOT-real-reviewer", "boundary": {"read_only": True, "write_rejected": True}, "files": rows})
        return invoke(mode)

    def native(role="EVIDENCE", *, packet=None, **changes):
        row = {"candidate": task["candidate"], "role": role, "verdict": "APPROVE",
               "coverage": "SYNTHETIC SCRIPTED fixture: native command and policy outputs only",
               "criteria": [{"id": c["id"], "sufficient": True, "reason": "Synthetic policy receipt inspected"} for c in task["acceptance"]],
               "case_assessments": [], "challenge": "Synthetic fixture control only, no independent model review",
               "findings": [], "test_requests": []}
        if packet and packet.get("incremental_evidence"):
            row["decision_basis_sha256"] = packet["incremental_evidence"]["decision_basis_sha256"]
            if role == "CODE":
                row["phase"] = "code"
        row.update(changes)
        path = evidence / "synthetic-native-review.json"
        write_json(path, row)
        return ("--review", str(path))

    def amend():
        path = evidence / "synthetic-owner-amendment.json"
        write_json(path, {"candidate": task["candidate"], "authority": "owner", "accepted": True,
                         "source": "SYNTHETIC fixture setup, never an actual owner approval",
                         "reason": "Controlled additional-witness claim fixture", "previous_contract_sha256": sha(read_bytes(evidence / "acceptance-contract.json"))})
        return invoke("preflight", extra=("--amend-contract", path.name))

    observations["preflight"] = invoke("preflight", "preflight")
    for name in ("one", "two"):
        capture(name)
    code = access("code-review")
    observations["code"] = code
    invoke("requests", "code_result", native("CODE", packet=code))
    initial = access()
    observations["initial"] = initial
    verdict = invoke("verdict", "accepted", native(packet=initial))
    # The new runtime retains this automatically; keep ORIGINAL task mutation.
    task = read_json(manifest)
    if not verdict.get("ready_for_approval"):
        raise ValueError("synthetic native seed did not validate; inspect retained captures")
    access()
    for index in range(2):
        invoke("resume", f"unchanged_resume_{index}")
    observations["unchanged_resume"] = invoke("review", "unchanged_resume")
    moved = evidence / "relocated.diff"
    moved.write_bytes(read_bytes(evidence / "candidate.diff"))
    task["diff"] = moved.name
    access()
    invoke("review", "navigation")
    task["diff"] = "candidate.diff"
    access()
    task.setdefault("incremental", {})["navigation"] = [{"path": "missing-covered-duplicate.log", "dependency_ids": ["criterion-one"]}]
    observations["covered_duplicate"] = invoke("review", "covered_duplicate")
    task["incremental"].pop("navigation")
    extra = evidence / "scoped-dependency.txt"
    extra.write_text("Synthetic effective input applies to claim one only")
    task["incremental"]["required_evidence"] = [{"reference": extra.name, "sha256": sha(read_bytes(extra)), "criteria": ["one"]}]
    invoke("review", "selective_dependency")
    task["incremental"].pop("required_evidence")
    (checkout / "one").write_text("changed")
    invoke("review", "changed_input")
    (checkout / "one").write_text("original")
    capture("one", refresh=True)
    packet = access()
    invoke("verdict", "input_repaired", native(packet=packet))
    task = read_json(manifest)
    access()
    invoke("resume", "input_repaired_resume")
    task["acceptance"][0]["description"] = "Synthetic policy one requiring an additional witness"
    amend()
    invoke("review", "changed_claim")
    task["acceptance"][0]["description"] = "Synthetic policy one"
    amend()
    packet = access()
    invoke("verdict", "claim_repaired", native(packet=packet))
    task = read_json(manifest)
    invoke("resume", "claim_repaired_resume")
    packet = access()
    old_basis = initial.get("incremental_evidence", {}).get("decision_basis_sha256")
    task["candidate"] = "synthetic-B"
    invoke("verdict", "wrong_candidate", native(packet=packet, candidate="synthetic-A"))
    task["candidate"] = "synthetic-A"
    full_diff = (evidence / "candidate.diff").read_bytes()
    (evidence / "candidate.diff").write_text("Synthetic current diff contains a new defect")
    invoke("review", "current_diff")
    if old_basis:
        invoke("verdict", "wrong_basis", native(packet=initial))
    (evidence / "candidate.diff").write_bytes(full_diff)
    packet = access()
    access(unreadable=str((evidence / "candidate.diff").resolve()))
    invoke("review", "necessary_missing")
    access()
    output = Path(packet["checks"][0]["output"])
    old_output = output.read_bytes()
    output.write_text("Synthetic contradictory retained native output")
    invoke("review", "tampered")
    invoke("review", "contradiction")
    output.write_bytes(old_output)
    access()
    invoke("resume", "contradiction_repaired_resume")
    (checkout / "one").write_text("failure")
    capture("one", refresh=True)
    invoke("review", "new_failure")
    (checkout / "one").write_text("original")
    capture("one", refresh=True)
    packet = access()
    invoke("verdict", "failure_repaired", native(packet=packet))
    task = read_json(manifest)
    packet = access("code-review")
    finding = {"id": "unresolved-fixture", "kind": "functional", "severity": "BLOCKER",
               "reference": "synthetic governed evidence", "impact": "Retained obligation must remain visible", "dependency_ids": ["criterion-one"]}
    request = {"id": "unresolved-witness", "criterion": "one", "input": "Synthetic alternate input", "expected": "Retain a sensitive native witness", "reason": "Synthetic unresolved witness obligation", "dependency_ids": ["criterion-one"]}
    invoke("requests", extra=native("CODE", packet=packet, verdict="REVISE", findings=[finding], test_requests=[request]))
    invoke("review", "unresolved")
    # An empty later synthetic response must not erase the retained finding.
    packet = access("code-review")
    invoke("requests", extra=native("CODE", packet=packet))
    invoke("resume", "unresolved_resume")
    if not any("unresolved-fixture" in str(x) for x in observations["unresolved_resume"].get("blockers", [])):
        raise ValueError("native obligation persistence calibration failed")
    if pin == INCREMENTAL_PIN:
        for name in ("accepted", "input_repaired", "claim_repaired", "failure_repaired"):
            if not observations[name].get("ready_for_approval"):
                raise ValueError("native repair acceptance calibration failed")
        if [d["state"] for d in observations["selective_dependency"]["incremental_evidence"]["dependencies"]] != ["changed", "accepted"]:
            raise ValueError("native selective dependency calibration failed")
    result = {"schema": SCHEMA, "kind": "native-runtime-calibration", "pin": pin,
              "identity": identity, "synthetic": True, "measured_review_observations": False,
              "schedule": copy.deepcopy(SCHEDULE), "calls": calls, "observations": observations, "states": states,
              "fixture_adaptations": ["Two policy-only gates avoid fabricating behavioral coverage.",
                                      "Controller-scripted native reviews/access records are explicitly synthetic.",
                                      "Each pin retains its own default preflight protocol and native output schemas."]}
    write_json(root / "native.json", result)
    return result


def _verify_generic_import(spec_path, spec):
    exact(spec, ("schema", "kind", "lineage", "source_manifest", "oracle", "views", "dependencies"), "historical import")
    if spec["schema"] != SCHEMA or spec["kind"] != "historical-import":
        raise ValueError("unknown import schema")
    exact(spec["lineage"], ("id", "subject_pin", "limitations"), "historical lineage")
    identifier(spec["lineage"]["id"])
    if not re.fullmatch(r"[0-9a-f]{40}", spec["lineage"]["subject_pin"]) or not spec["lineage"]["limitations"]:
        raise ValueError("subject pin and limitations required")
    source = json.loads(_bound(spec["source_manifest"]))
    if not isinstance(source, dict) or not isinstance(source.get("files"), dict):
        raise ValueError("source manifest inventory required")
    originals = source["files"]
    oracle_raw = _bound(spec["oracle"])
    oracle = json.loads(oracle_raw)
    if not isinstance(oracle, list) or not oracle:
        raise ValueError("preserved independent oracle list required")
    _unique(spec["views"])
    if not isinstance(spec["dependencies"], list) or not spec["dependencies"]:
        raise ValueError("dependency lineage required")
    inventories = [originals]
    dependencies = []
    for ref in spec["dependencies"]:
        raw = _bound(ref)
        try:
            payload = json.loads(raw)
        except ValueError:
            raise ValueError("dependency provenance JSON required")
        dependencies.append((ref, payload))
        if isinstance(payload, dict) and isinstance(payload.get("files"), dict):
            # The original pilot's independently pinned manifest covers its
            # immutable oracle; corrected-view manifest covers current views.
            bound = {}
            for name, value in payload["files"].items():
                candidate = Path(name)
                if not candidate.is_absolute():
                    relative(name)
                    candidate = Path(ref["path"]).parent / name
                bound[str(candidate)] = digest_string(value)
            inventories.append(bound)
    def covered(path, expected):
        return any(inventory.get(path) == expected for inventory in inventories)
    for ref, payload in dependencies:
        if not covered(ref["path"], ref["sha256"]) and not isinstance(payload.get("files"), dict):
            raise ValueError("dependency absent from pinned original manifests")
        if "original_source_only" in payload:
            if payload["original_source_only"] is not True or payload.get("no_findings_or_expected_answers_copied") is not True or not payload.get("ranges") or not payload.get("extracted_payloads"):
                raise ValueError("dependency excerpt provenance is insufficient")
    if not covered(spec["oracle"]["path"], spec["oracle"]["sha256"]):
        raise ValueError("oracle absent from pinned original manifests")
    verified = []
    total = 0
    for view in spec["views"]:
        exact(view, ("id", "root", "seal", "files"), "imported view")
        root = no_symlinks(view["root"])
        if not root.is_absolute() or not root.is_dir() or root == REPO or REPO in root.parents:
            raise ValueError("private view root required")
        seal = json.loads(_bound(view["seal"]))
        if originals.get(view["seal"]["path"]) != view["seal"]["sha256"]:
            raise ValueError("seal absent from original manifest")
        if not isinstance(seal, dict) or not seal:
            raise ValueError("nonempty seal required")
        _unique(view["files"])
        if {r["path"] for r in view["files"]} != set(seal):
            raise ValueError("import must match exactly the preserved selected view")
        for row in view["files"]:
            exact(row, ("id", "path", "sha256", "bytes", "necessary", "coverage"), "imported file")
            relative(row["path"])
            digest_string(row["sha256"])
            path = no_symlinks(root / row["path"])
            raw = read_bytes(path)
            if seal[row["path"]] != row["sha256"] or (str(path) in originals and originals[str(path)] != row["sha256"]) or sha(raw) != row["sha256"] or len(raw) != row["bytes"]:
                raise ValueError("original view/source binding drift")
            if type(row["necessary"]) is not bool or not isinstance(row["coverage"], list):
                raise ValueError("invalid required coverage")
            total += len(raw)
            if total > MAX_TOTAL:
                raise ValueError("import size ceiling")
        entry_row = next((r for r in view["files"] if r["path"] == "ENTRY.json"), None)
        diff_row = next((r for r in view["files"] if r["path"] == "candidate.diff"), None)
        if entry_row is None or diff_row is None or not any(r["path"].startswith("source/") for r in view["files"]):
            raise ValueError("preserved source/entry/diff missing")
        entry = read_json(root / "ENTRY.json")
        # Historical key shape is retained rather than projected into public schema.
        key = next((k for k in oracle if k.get("case") == view["id"]), None)
        if key is None or not key.get("candidate"):
            raise ValueError("view has no frozen independent oracle identity")
        if entry.get("candidate") != key["candidate"] or entry.get("case") != view["id"] or entry.get("source_pin") != spec["lineage"]["subject_pin"]:
            raise ValueError("view/oracle source, candidate or case mismatch")
        verified.append({**view, "candidate": key["candidate"], "source_pin": spec["lineage"]["subject_pin"]})
    if {v["id"] for v in verified} != {k.get("case") for k in oracle}:
        raise ValueError("selected oracle/view matrix mismatch")
    return {"schema": SCHEMA, "kind": "verified-private-import", "spec": spec,
            "spec_sha256": sha(read_bytes(spec_path)), "views": verified}


def verify_import(spec_path):
    """Verify an externally frozen selected import; hashes establish integrity,
    not authenticity of an arbitrary caller's trust root."""
    spec = read_json(spec_path)
    return _verify_generic_import(spec_path, spec)


def case_packets(runtime_root, controller_root, view_root, artifacts, candidate, source_pin, claim):
    """Adapt one preserved source-only view to the actual pinned packet helper.

    These are unaccepted review-only claims. Native policy, schemas and pending
    access remain intact; no historical execution/acceptance is manufactured.
    """
    evidence = controller_root / "case-evidence"
    evidence.mkdir(mode=0o700)
    subject = controller_root / "case-subject"
    subject.mkdir()
    links = {}
    for row in artifacts:
        target = evidence / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(read_bytes(view_root / row["path"]))
        links[str(target.resolve())] = "artifact:" + row["id"]
    diff = next((r["path"] for r in artifacts if r["path"] == "candidate.diff"), None)
    if diff is None:
        diff = "candidate.diff"
        (evidence / diff).write_text("Explicit synthetic calibration candidate diff; inspect source and witness artifacts.\n")
    bindings = [{"id": r["id"], "sha256": r["sha256"]} for r in artifacts]
    assertion = "Inspect the actual source and original retained evidence for this claim. Artifact bindings: " + canonical(bindings).decode()
    inventory_path = subject / "view-bindings.json"
    write_json(inventory_path, [{"path": str((evidence / r["path"]).resolve()), "sha256": r["sha256"]} for r in artifacts])
    integrity_script = "import hashlib,json; from pathlib import Path; rows=json.loads(Path('view-bindings.json').read_text()); assert all(hashlib.sha256(Path(r['path']).read_bytes()).hexdigest()==r['sha256'] for r in rows); print('Source-view integrity verified; no product-behavior assertion')"
    fingerprint_script = "import hashlib,json; from pathlib import Path; rows=json.loads(Path('view-bindings.json').read_text()); print(json.dumps([(r['path'],hashlib.sha256(Path(r['path']).read_bytes()).hexdigest()) for r in rows]))"
    request = {"command": [sys.executable, "-B", "-c", integrity_script], "scope": "Exact selected source-view integrity only, not product behavior", "summary": None,
               "fingerprint_command": [sys.executable, "-B", "-c", fingerprint_script], "artifacts": []}
    gate = {"id": "view-integrity", "phase": "cheap", "request": request}
    task = {"candidate": candidate, "saved_candidate": candidate, "diff": diff,
            "scope": "Evidence-inspection source-only adaptation; subject pin " + source_pin,
            "preview": None, "gates": [gate], "delivery": "Read-only benchmark proposal; no product or provider writes",
            "acceptance": [{"id": "inspection", "kind": "policy", "automatable": False,
                            "reason": "This benchmark decision judges semantic sufficiency of retained source/evidence; it is not a new product test execution.",
                            "description": text(claim, "source-only claim"), "proofs": [{"kind": "review", "assertion": assertion}]}]}
    # Default protocol is left to the actual pin. Explicit incremental opt-in
    # would change the baseline treatment and is deliberately absent.
    task_path = evidence / "task.json"
    write_json(task_path, task)
    scripts = runtime_root / "workflow/scripts"
    captures = []
    packets = []
    for mode in ("preflight", "code-review", "review"):
        command = [sys.executable, "-B", str(scripts / "handoff.py"), mode, "--task", str(task_path), "--evidence-dir", str(evidence)]
        result = subprocess.run(command, cwd=subject, stdin=subprocess.DEVNULL, capture_output=True,
                                timeout=20, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONDONTWRITEBYTECODE": "1"})
        (controller_root / ("case-" + mode + ".stdout")).write_bytes(result.stdout)
        (controller_root / ("case-" + mode + ".stderr")).write_bytes(result.stderr)
        if result.returncode not in (0, 1):
            raise ValueError("case-bound native packet helper rejected adaptation: " + result.stderr.decode(errors="replace").strip())
        packet = json.loads(result.stdout)
        captures.append({"mode": mode, "exit_code": result.returncode, "stdout_sha256": sha(result.stdout), "stderr_sha256": sha(result.stderr)})
        if mode == "preflight":
            capture_command = [sys.executable, "-B", str(scripts / "capture_check.py"), "--gate", "view-integrity", "--scope", request["scope"], "--candidate", candidate,
                               "--owner", "controller", "--fingerprint-command", json.dumps(request["fingerprint_command"]), "--evidence-dir", str(evidence), "--", *request["command"]]
            captured = subprocess.run(capture_command, cwd=subject, stdin=subprocess.DEVNULL, capture_output=True, timeout=20,
                                      env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONDONTWRITEBYTECODE": "1"})
            (controller_root / "case-capture.stdout").write_bytes(captured.stdout)
            (controller_root / "case-capture.stderr").write_bytes(captured.stderr)
            captures.append({"mode": "capture", "exit_code": captured.returncode, "stdout_sha256": sha(captured.stdout), "stderr_sha256": sha(captured.stderr)})
            if captured.returncode != 0:
                raise ValueError("native source-view integrity check failed")
            continue
        # Keep the native packet byte-for-byte privately. Reviewer navigation
        # replaces only controller path prefixes, with an explicit adaptation.
        rendered = result.stdout.decode()
        for old, mapped in sorted(links.items(), key=lambda item: len(item[0]), reverse=True):
            rendered = rendered.replace(old, mapped)
        rendered = rendered.replace(str(evidence.resolve()), "controller-private:evidence")
        rendered = rendered.replace(str(controller_root.resolve()), "controller-private")
        name = "packet-code.json" if mode == "code-review" else "packet-final.json"
        (view_root / name).write_text(rendered)
        raw = read_bytes(view_root / name)
        packets.append({"id": "native-code-packet" if mode == "code-review" else "native-final-packet", "path": name,
                        "sha256": sha(raw), "bytes": len(raw), "necessary": True, "coverage": ["workflow"]})
    write_json(controller_root / "case-packet-adaptation.json", {
        "schema": SCHEMA, "candidate": candidate, "source_pin": source_pin,
        "claim_sha256": sha(claim.encode()), "evidence_bindings_sha256": sha(canonical(bindings)),
        "native_calls": captures, "accepted": False, "measured_review_observations": False,
        "adaptation": "Review-only semantic acceptance, no invented historical gates or prior approvals; reviewer navigation maps private paths to opaque artifact IDs; original outputs retained.",
        "access": "Pending actual external session boundary and required-evidence probes before decision."})
    return packets


def lifecycle_view(runtime, case_id, view_root):
    mapping = {"c01": "unchanged_resume", "c02": "navigation", "c06": "changed_input",
               "c07": "contradiction", "c08": "unresolved", "c09": "necessary_missing",
               "c10": "covered_duplicate", "c11": "tampered", "c12": "current_diff"}
    state = runtime["states"][mapping[case_id]]
    root = Path(state["root"])
    artifacts, paths = [], {}
    for index, path in enumerate(sorted(p for directory in ("evidence", "source") for p in (root / directory).rglob("*") if p.is_file())):
        name = str(path.relative_to(root))
        raw = read_bytes(path)
        destination = view_root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
        aid = f"n{index:04d}"
        necessary = name in ("evidence/task.json", "evidence/candidate.diff", "source/one", "source/two") or name.endswith(("run.json", "output.log"))
        artifacts.append({"id": aid, "path": name, "sha256": sha(raw), "bytes": len(raw), "necessary": necessary, "coverage": ["native-inspection"]})
        old = name.replace("evidence/", state["original_evidence_root"] + "/", 1) if name.startswith("evidence/") else name.replace("source/", state["original_source_root"] + "/", 1)
        paths[old] = "artifact:" + aid
    # Only navigation is adapted. The complete native packets remain private.
    for mode, aid, name in (("code-review", "native-code-packet", "packet-code.json"), ("review", "native-final-packet", "packet-final.json")):
        rendered = read_bytes(root / (mode + ".stdout")).decode()
        for old, mapped in sorted(paths.items(), key=lambda kv: len(kv[0]), reverse=True):
            rendered = rendered.replace(old, mapped)
        rendered = rendered.replace(state["original_evidence_root"], "controller-private:evidence").replace(state["original_source_root"], "controller-private:source")
        raw = rendered.encode()
        (view_root / name).write_bytes(raw)
        artifacts.append({"id": aid, "path": name, "sha256": sha(raw), "bytes": len(raw), "necessary": True, "coverage": ["native-inspection"]})
    write_json(root / "controller-state.json", {"schema": SCHEMA, "kind": "controller-intervention",
                                              "case_id": case_id, "actual_native_state": mapping[case_id]})
    premise = {"schema": SCHEMA, "kind": "synthetic-common-history",
               "scripted_prior_reviews": True, "real_review_observations": False,
               "meaning": "Actual pinned helper state from an explicitly scripted common calibration history, never historical or model acceptance."}
    raw = canonical(premise)
    (view_root / "history-premise.json").write_bytes(raw)
    artifacts.append({"id": "common-history", "path": "history-premise.json", "sha256": sha(raw), "bytes": len(raw), "necessary": True, "coverage": ["native-inspection"]})
    if case_id == "c09":
        # An actual reviewer read fails; controller accessibility alone is not
        # substituted for the required-evidence access experiment.
        (view_root / "evidence/candidate.diff").unlink()
    frozen_task = read_json(root / "evidence/task.json")
    identity = sha(canonical({"source": [{"path": a["path"], "sha256": a["sha256"]} for a in artifacts if a["path"].startswith("source/")],
                              "diff": sha(read_bytes(root / "evidence/candidate.diff")), "claims": frozen_task["acceptance"]}))
    return artifacts, frozen_task["candidate"], "synthetic:" + identity


def prepare(suite, case_id, runtime_repo, output, *, condition="incremental", import_spec=None):
    validate_suite(suite)
    if condition not in ("baseline", "incremental"):
        raise ValueError("unknown condition")
    pin = BASELINE_PIN if condition == "baseline" else INCREMENTAL_PIN
    imported = verify_import(import_spec) if import_spec else None
    forbidden = []
    if imported:
        found = [v for v in imported["views"] if v["id"] == case_id]
        if len(found) != 1:
            raise ValueError("choose one preserved view case")
        original = found[0]
        source_root = Path(original["root"])
        artifacts = original["files"]
        candidate, source_pin = original["candidate"], original["source_pin"]
        claim = read_json(source_root / "ENTRY.json")["claim"]
        forbidden = [v["root"] for v in imported["views"]]
    else:
        found = [c for c in suite["cases"] if c["id"] == case_id]
        if len(found) != 1:
            raise ValueError("unknown synthetic calibration case")
        case = found[0]
        artifacts = []
        for a in case["artifacts"]:
            raw = a["content"].encode()
            artifacts.append({k: a[k] for k in ("id", "path", "necessary", "coverage")}
                             | {"sha256": sha(raw), "bytes": len(raw)})
        identity = sha(canonical({"claims": case["claims"], "artifacts": artifacts}))
        candidate, source_pin = "synthetic-" + identity, "synthetic:" + identity
        claim = "Explicit synthetic calibration: assess claim k1 using original source and native witness; no model effectiveness inference."
    root = private_output(output, forbidden)
    controller = root / "controller"
    controller.mkdir(mode=0o700)
    view_root = root / "view"
    view_root.mkdir(mode=0o700)
    for a in artifacts:
        raw = read_bytes(source_root / a["path"]) if imported else next(x["content"].encode() for x in case["artifacts"] if x["id"] == a["id"])
        target = view_root / a["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        target.chmod(0o400)
    runtime = exercise_runtime(runtime_repo, pin, controller / "runtime-calibration")
    # Expose the actual selected policy bytes as an opaque allowlisted artifact.
    policy_path = "workflow/docs/development-workflow.md"
    policy_raw = read_bytes(controller / "runtime-calibration/runtime" / policy_path)
    policy_name = "policy.txt"
    if policy_name in {a["path"] for a in artifacts}:
        raise ValueError("reserved policy path")
    (view_root / policy_name).write_bytes(policy_raw)
    artifacts = copy.deepcopy(artifacts)
    if not imported and case_id not in ("c03", "c04", "c05"):
        for path in list(view_root.iterdir()):
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        artifacts, candidate, source_pin = lifecycle_view(runtime, case_id, view_root)
        # policy was removed with the fresh placeholder view above.
        (view_root / policy_name).write_bytes(policy_raw)
    else:
        artifacts += case_packets(controller / "runtime-calibration/runtime", controller, view_root,
                                  artifacts, candidate, source_pin, claim)
    artifacts += [{"id": "workflow-policy", "path": policy_name, "sha256": sha(policy_raw),
                   "bytes": len(policy_raw), "necessary": True, "coverage": ["workflow"]}]
    view = {"schema": SCHEMA, "kind": "reviewer-view", "case_id": case_id, "condition": condition,
            "artifacts": artifacts, "candidate": candidate, "source_pin": source_pin, "created_ns": time.time_ns()}
    validate_view(view)
    write_json(view_root / "view.json", view)
    # The oracle never enters the view. Synthetic calibration answers stay controller-only too.
    if not imported:
        prepared_oracle = copy.deepcopy(case["oracle"])
        if case_id not in ("c03", "c04", "c05"):
            refs = ["native-final-packet", next(a["id"] for a in artifacts if a["path"] == "source/one")]
            for defect in prepared_oracle["defects"]:
                defect["claim"] = "one"
                defect["references"] = refs
                defect["discrepancy"] = "The current native packet reopens claim one: " + case["variant"] + "."
                defect["repair"] = "Resolve the specific native blocker and revalidate the affected claim without clearing unrelated obligations."
        write_json(controller / "synthetic-oracle.json", prepared_oracle)
    oracle_sha256 = imported["spec"]["oracle"]["sha256"] if imported else sha(canonical(prepared_oracle))
    # Identity groups are distinct. Native absolute paths stay in PRIVATE controller captures.
    manifests = {"source": {"pin": source_pin, "candidate": candidate},
                 "workflow": runtime["identity"], "evidence": {"artifacts": artifacts},
                 "prompt": {"schedule": SCHEDULE, "instruction": "Inspect each claim with the actual pinned policy; preserve findings and requests."},
                 "environment": {"python": sys.version, "platform": sys.platform, "tools": ["instrumented-reader"], "provider": None},
                 "lineage": {"kind": "preserved-private" if imported else "synthetic-calibration",
                             "import_spec_sha256": imported["spec_sha256"] if imported else None,
                             "suite_sha256": sha(canonical(suite)), "tool_sha256": sha(read_bytes(__file__)), "oracle_sha256": oracle_sha256}}
    run = {"schema": SCHEMA, "kind": "prepared-run", "condition": condition, "pin": pin, "case_id": case_id,
           "synthetic": not bool(imported), "schedule": SCHEDULE, "manifests": manifests,
           "manifest_sha256": {k: sha(canonical(v)) for k, v in manifests.items()},
           "view_sha256": sha(read_bytes(view_root / "view.json")), "boundary": "pending-external-reviewer-probes",
           "measured_review_observations": False}
    write_json(controller / "run.json", run)
    return {"run": run, "run_path": str(controller / "run.json"), "view_path": str(view_root / "view.json")}


def validate_run(run):
    exact(run, ("schema", "kind", "condition", "pin", "case_id", "synthetic", "schedule", "manifests",
                "manifest_sha256", "view_sha256", "boundary", "measured_review_observations"), "prepared run")
    if run["schema"] != SCHEMA or run["kind"] != "prepared-run" or run["schedule"] != SCHEDULE:
        raise ValueError("invalid run schema/stages")
    identifier(run["case_id"])
    if run["condition"] not in ("baseline", "incremental") or run["pin"] != (BASELINE_PIN if run["condition"] == "baseline" else INCREMENTAL_PIN):
        raise ValueError("wrong runtime condition pin")
    fields = ("source", "workflow", "evidence", "prompt", "environment", "lineage")
    exact(run["manifests"], fields, "identity manifests")
    exact(run["manifest_sha256"], fields, "manifest seals")
    for key in fields:
        if sha(canonical(run["manifests"][key])) != run["manifest_sha256"][key]:
            raise ValueError("manifest drift")
    workflow = run["manifests"]["workflow"]
    exact(workflow, ("pin", "files", "workflow_sha256", "python"), "workflow identity")
    if workflow["pin"] != run["pin"] or workflow["workflow_sha256"] != sha(canonical(workflow["files"])):
        raise ValueError("substituted workflow identity")
    required_files = _git(REPO, "ls-tree", "-r", "--name-only", run["pin"], "workflow/scripts", "workflow/reviewers",
                          "workflow/docs/development-workflow.md", "workflow/skills/develop-change/SKILL.md").decode().splitlines()
    if sorted(r["path"] for r in workflow["files"]) != sorted(required_files):
        raise ValueError("incomplete/substituted workflow inventory")
    for row in workflow["files"]:
        exact(row, ("path", "sha256", "bytes"), "runtime source")
        raw = _git(REPO, "show", run["pin"] + ":" + relative(row["path"]))
        if sha(raw) != row["sha256"] or len(raw) != row["bytes"]:
            raise ValueError("actual pinned helper bytes mismatch")
    exact(run["manifests"]["source"], ("pin", "candidate"), "source identity")
    exact(run["manifests"]["evidence"], ("artifacts",), "evidence identity")
    exact(run["manifests"]["prompt"], ("schedule", "instruction"), "prompt identity")
    exact(run["manifests"]["environment"], ("python", "platform", "tools", "provider"), "environment identity")
    exact(run["manifests"]["lineage"], ("kind", "import_spec_sha256", "suite_sha256", "tool_sha256", "oracle_sha256"), "lineage identity")
    digest_string(run["view_sha256"])
    return run


def verify_prepared(run, run_path):
    """Recheck actual prepared artifacts before scoring. The externally frozen
    run digest is still a controller trust-root responsibility."""
    root = no_symlinks(Path(run_path).parent.parent / "view")
    view_path = root / "view.json"
    if sha(read_bytes(view_path)) != run["view_sha256"]:
        raise ValueError("prepared view manifest drift")
    view = validate_view(read_json(view_path))
    if view["case_id"] != run["case_id"] or view["condition"] != run["condition"] or view["artifacts"] != run["manifests"]["evidence"]["artifacts"] or view["candidate"] != run["manifests"]["source"]["candidate"] or view["source_pin"] != run["manifests"]["source"]["pin"]:
        raise ValueError("prepared source/evidence identity mismatch")
    for row in view["artifacts"]:
        raw = read_bytes(root / row["path"])
        if sha(raw) != row["sha256"] or len(raw) != row["bytes"]:
            raise ValueError("prepared original artifact drift")
    return view


def smoke(output=None, suite_path=DEFAULT_SUITE, runtime_repo=REPO):
    suite = load_suite(suite_path)
    temporary = None
    if output is None:
        temporary = tempfile.TemporaryDirectory(prefix="evidence-inspection-smoke-")
        root = Path(temporary.name).resolve()
    else:
        root = private_output(output)
    try:
        runtimes = {name: exercise_runtime(runtime_repo, pin, root / name) for name, pin in (("baseline", BASELINE_PIN), ("incremental", INCREMENTAL_PIN))}
        oracle = next(c["oracle"] for c in suite["cases"] if c["oracle"]["defects"])
        generic = score_decision(oracle, {"verdict": "BLOCK", "findings": [], "native_output": "Synthetic generic block", "matcher": "structured-exact-v1"})
        escaped = score_decision(oracle, {"verdict": "APPROVE", "findings": [], "native_output": "Synthetic false approval", "matcher": "structured-exact-v1"})
        result = {"schema": SCHEMA, "kind": "provider-free-smoke", "machinery_only": True, "synthetic": True,
                  "measured_review_observations": False, "acceptable_efficiency_claim": False,
                  "pins": {name: r["identity"]["workflow_sha256"] for name, r in runtimes.items()},
                  "native_call_counts": {name: len(r["calls"]) for name, r in runtimes.items()},
                  "default_protocols": {name: r["observations"]["preflight"].get("review_protocol", "legacy") for name, r in runtimes.items()},
                  "generic_block_detection_credit": generic["specific_detected"],
                  "critical_false_approval_gates_efficiency": escaped["critical_false_approval"] and not escaped["acceptable_efficiency_claim"],
                  "scope": "Scripted calibration only. No provider/model/reviewer effectiveness or efficiency observations."}
        write_json(root / "smoke.json", result)
        report_dir = os.environ.get("FLIGHTCHECK_REPORT_DIR")
        if report_dir:
            report = no_symlinks(report_dir)
            if not report.is_dir():
                raise ValueError("report directory missing")
            write_json(report / "smoke.json", result)
        return result
    finally:
        if temporary:
            temporary.cleanup()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    p = commands.add_parser("prepare")
    p.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    p.add_argument("--case", required=True)
    p.add_argument("--runtime", type=Path, default=REPO)
    p.add_argument("--condition", choices=("baseline", "incremental"), default="incremental")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--import-spec", type=Path)
    p = commands.add_parser("read")
    p.add_argument("--view", type=Path, required=True)
    p.add_argument("--artifact", required=True)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--length", type=int)
    p.add_argument("--role", choices=("CODE", "EVIDENCE"), required=True)
    p.add_argument("--session", required=True)
    p.add_argument("--phase", choices=("inspection", "probe"), default="inspection")
    p.add_argument("--events", type=Path, required=True)
    p = commands.add_parser("score")
    for name in ("run", "reviews", "events", "oracle", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    p = commands.add_parser("smoke")
    p.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    p.add_argument("--output", type=Path)
    p.add_argument("--runtime", type=Path, default=REPO)
    args = parser.parse_args(argv)
    try:
        if args.mode == "prepare":
            result = prepare(load_suite(args.suite), args.case, args.runtime, args.output, condition=args.condition, import_spec=args.import_spec)
            print(json.dumps({"schema": SCHEMA, "prepared": True, "run_path": result["run_path"], "view_path": result["view_path"]}))
        elif args.mode == "read":
            result = read_artifact(args.view, args.artifact, offset=args.offset, length=args.length, role=args.role, session=args.session, phase=args.phase, events_path=args.events)
            # Exact returned bytes, no injected event metadata in the reviewed evidence.
            sys.stdout.buffer.write(result["data"])
        elif args.mode == "score":
            run = validate_run(read_json(args.run))
            verify_prepared(run, args.run)
            reviews = read_json(args.reviews)
            exact(reviews, ("review", "attempts", "boundary", "session", "decision_time_ns"), "score capture")
            observation = validate_boundary(reviews["boundary"], run["view_sha256"], reviews["session"], reviews["decision_time_ns"])
            if not observation["access_sufficient"]:
                raise ValueError("necessary reviewer evidence inaccessible")
            events = [json.loads(line) for line in read_bytes(args.events).splitlines()]
            accounting = account(reviews["attempts"], events)
            if reviews["session"] not in {attempt["session"] for attempt in accounting["attempts"]}:
                raise ValueError("decision boundary session is absent from the attempt ledger")
            validate_event_attribution(events, accounting["attempts"], reviews["decision_time_ns"])
            inventory = {a["id"]: a for a in run["manifests"]["evidence"]["artifacts"]}
            for event in events:
                row = inventory.get(event.get("artifact"))
                if row is None or event.get("view_sha256") != run["view_sha256"] or event.get("artifact_sha256") != row["sha256"]:
                    raise ValueError("read event has wrong view/artifact binding")
                if type(event.get("offset")) is not int or type(event.get("bytes")) is not int or min(event["offset"], event["bytes"]) < 0 or event["offset"] + event["bytes"] > row["bytes"]:
                    raise ValueError("read range exceeds bound artifact")
            oracle_capture = read_json(args.oracle)
            if run["synthetic"]:
                oracle = validate_oracle(oracle_capture)
                if sha(canonical(oracle)) != run["manifests"]["lineage"]["oracle_sha256"]:
                    raise ValueError("wrong frozen synthetic oracle")
            else:
                crosswalk = validate_crosswalk(oracle_capture)
                if crosswalk["original_oracle_sha256"] != run["manifests"]["lineage"]["oracle_sha256"] or crosswalk["case_id"] != run["case_id"] or crosswalk["candidate"] != run["manifests"]["source"]["candidate"]:
                    raise ValueError("wrong original oracle crosswalk binding")
                validate_source_references(crosswalk, inventory, args.run.parent.parent / "view")
                oracle = crosswalk["oracle"]
            result = {"schema": SCHEMA, "kind": "sanitized-run-score",
                      "case_id": run["case_id"], "condition": run["condition"], "pin": run["pin"],
                      "view_sha256": run["view_sha256"], "run_sha256": sha(canonical(run)),
                      "manifest_sha256": copy.deepcopy(run["manifest_sha256"]),
                      "decision": score_decision(oracle, reviews["review"]),
                      "accounting": accounting, "observability": observation,
                      "acceptable_efficiency_claim": False, "synthetic": run["synthetic"],
                      "native_review_audit_sha256": sha(canonical(reviews["review"]))}
            out = private_output(args.output)
            write_json(out / "score.json", result)
            # Keep complete original prose in PRIVATE audit; sanitized score contains no prose/key/paths.
            write_json(out / "audit.json", {"run": run, "capture": reviews, "events": events})
            print(json.dumps(result, sort_keys=True))
        else:
            print(json.dumps(smoke(args.output, args.suite, args.runtime), sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        parser.exit(2, f"Evidence inspection refused: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
