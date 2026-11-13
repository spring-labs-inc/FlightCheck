"""Publish a curated FlightCheck task snapshot and format controller status text."""

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from task_details import STAGE_NAMES, normalize_details, task_id, update_details

VERDICTS = ("APPROVE", "APPROVE_WITH_NITS", "APPROVE_WITH_OBSERVATIONS", "REVISE")


def completeness(data):
    """Derive readiness from curated observations, never a caller's ready flag."""
    if data["mode"] == "minimal":
        return {"state": "minimal", "ready": False,
                "issues": ["Minimal transport snapshot; initialize --mode flight with complete --details for an active flight."]}
    issues = []
    if not data["candidate"]:
        issues.append("Supply the current candidate identity.")
    stages = data.get("stages", {})
    terminal = (len(stages) == len(STAGE_NAMES) and stages.get("Final Verdict") == "completed"
                and all(state in ("completed", "skipped") for state in stages.values()))
    if (set(data.get("stages_declared", [])) != set(STAGE_NAMES)
            or not stages or ("current" not in stages.values() and not terminal)):
        issues.append("Supply all nine stages with one honest current stage, or a completed terminal flight.")
    plan = data.get("check_plan")
    unavailable = data.get("checks_unavailable")
    if plan is None or (not plan and not unavailable) or (plan and unavailable):
        issues.append("Declare check_plan with applicable names, or an empty plan and checks_unavailable reason.")
    for name in plan or []:
        rows = [row for row in data.get("checks", []) if row["name"] == name
                and row["candidate"] == data["candidate"] and not row["stale"]]
        if len(rows) != 1:
            issues.append(f"Supply one current observation for check {name}; pending means not run.")
        elif rows[0]["state"] == "unavailable" and not rows[0].get("reason"):
            issues.append(f"Explain why check {name} is unavailable.")
    for kind in ("issue", "pr"):
        known = any(row["kind"] == kind for row in data.get("links", []))
        explained = kind in data.get("links_unavailable", {})
        if known == explained:
            issues.append(f"Supply the known {kind} link or a links_unavailable.{kind} reason, exclusively.")
    return {"state": "incomplete" if issues else "ready", "ready": not issues, "issues": issues}


def evidence_identity(data):
    fields = ("candidate", "check_plan", "checks_unavailable", "checks", "ci")
    return hashlib.sha256(json.dumps({key: data.get(key) for key in fields}, sort_keys=True).encode()).hexdigest()


def task_path(task):
    return f"/task/{task_id(task)}/"


def normalize(data):
    """Return only the fields published to the browser."""
    if not isinstance(data, dict):
        raise ValueError("Expected a task object")
    task = data.get("task")
    task_path(task)
    fields = {name: data.get(name, "") for name in ("title", "summary", "candidate")}
    if not all(isinstance(value, str) and len(value) <= 500 for value in fields.values()):
        raise ValueError("Task fields must be short strings")
    if not fields["title"].strip():
        raise ValueError("A task title is required")
    candidate = fields["candidate"].strip()
    verdict = data.get("verdict")
    details = normalize_details(data)
    stage_map = details.get("stages")
    mode = data.get("mode", "minimal")
    if mode not in ("minimal", "flight"):
        raise ValueError("Expected mode minimal or flight")
    state = {"mode": mode, "candidate": candidate, **details}
    ready = completeness(state)
    current = (ready["ready"] and candidate and data.get("verdict_candidate") == candidate
               and verdict in VERDICTS and data.get("verdict_evidence") == evidence_identity(state))
    if stage_map is not None:
        current = current and stage_map["Final Verdict"] in ("current", "completed")
    return {
        "snapshot": "live" if mode == "flight" else "minimal",
        "mode": mode,
        "completeness": ready,
        "task": task,
        **fields,
        "candidate": candidate,
        "verdict": verdict if current else "Pending",
        "verdict_candidate": candidate if current else None,
        "verdict_evidence": data.get("verdict_evidence") if current else None,
        **details,
    }


def read_task(path):
    return normalize(json.loads(path.read_text(encoding="utf-8")))


def validate_task_url(url, task):
    if not isinstance(url, str) or any(char.isspace() or ord(char) < 32 for char in url):
        raise ValueError("Task URLs cannot contain whitespace or control characters")
    route = urlsplit(url)
    port = route.port
    if (route.scheme != "http" or route.hostname not in ("127.0.0.1", "localhost", "::1")
            or not port or route.path != task_path(task) or route.query or route.fragment
            or route.username is not None or route.password is not None
            or route.netloc not in (f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}")):
        raise ValueError("Use an explicit loopback HTTP URL and port with the exact task route")
    return url


def chat_status(data, url, phase):
    label = "&lt; status /&gt;"
    if url:
        validate_task_url(url, data["task"])
        label = f"[{label}]({url})"
    if phase is None:
        return ""
    status = f"FlightCheck: {label}"
    if phase == "end" and data["verdict"] in VERDICTS:
        status = f"Verdict: {data['verdict']}\n\n" + status
    return status


def publish(path, data, details, record_verdict=False):
    parent = path.parent
    if parent.stat().st_uid != os.geteuid() or parent.stat().st_mode & 0o077:
        raise ValueError("Snapshot directory must be private to the current user")
    previous = read_task(path) if path.exists() else {}
    if previous and previous["task"] != data["task"]:
        raise ValueError("A snapshot belongs to one task")
    data.update(update_details(previous, details, data["candidate"]))
    if record_verdict:
        data["verdict_evidence"] = evidence_identity(data)
    data.update(normalize(data))
    fd, pending = tempfile.mkstemp(prefix=".status-", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream)
            stream.write("\n")
        os.replace(pending, path)
    finally:
        Path(pending).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--task", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--summary", default="")
    parser.add_argument("--candidate", default="")
    parser.add_argument("--mode", choices=("minimal", "flight"), default="minimal",
                        help="Minimal is a labeled transport fixture, never active-flight readiness")
    parser.add_argument("--verdict", choices=VERDICTS)
    parser.add_argument("--verdict-candidate")
    parser.add_argument("--details", type=Path, help="Private JSON with curated task status details")
    parser.add_argument("--url", help="Published loopback URL for this task")
    parser.add_argument("--chat-phase", choices=("start", "update", "end"), help="Print status text with the link last")
    args = parser.parse_args()
    try:
        data = {key: getattr(args, key) for key in
                ("task", "title", "summary", "candidate", "mode", "verdict", "verdict_candidate")}
        # Validate the route before replacing the snapshot.
        chat_status(data, args.url, args.chat_phase)
        details = json.loads(args.details.read_text(encoding="utf-8")) if args.details else {}
        publish(args.file, data, details, record_verdict=bool(args.verdict))
        status = chat_status(data, args.url, args.chat_phase)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    if status:
        print(status)


if __name__ == "__main__":
    main()
