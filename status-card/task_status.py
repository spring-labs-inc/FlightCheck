"""Publish a curated SpringDev task snapshot and format flight boundary text."""

import argparse
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
VERDICTS = ("APPROVE", "APPROVE_WITH_NITS", "APPROVE_WITH_OBSERVATIONS", "REVISE")


def task_path(task):
    if not isinstance(task, str) or not TASK_ID.fullmatch(task):
        raise ValueError("Invalid task ID")
    return f"/task/{task}/"


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
    current = candidate and data.get("verdict_candidate") == candidate and verdict in VERDICTS
    return {
        "snapshot": "live",
        "task": task,
        **fields,
        "candidate": candidate,
        "verdict": verdict if current else "Pending",
        "verdict_candidate": candidate if current else None,
    }


def read_task(path):
    return normalize(json.loads(path.read_text(encoding="utf-8")))


def chat_status(data, url, phase):
    label = "&lt; status /&gt;"
    if url:
        route = urlsplit(url)
        if (route.scheme != "http" or route.hostname != "127.0.0.1" or not route.port
                or route.path != task_path(data["task"]) or route.netloc != f"127.0.0.1:{route.port}"
                or route.query or route.fragment):
            raise ValueError("Use the published loopback URL for this task")
        label = f"[{label}]({url})"
    if phase is None:
        return ""
    status = f"SpringDev: {label}"
    if phase == "end" and data["verdict"] in VERDICTS:
        status += f"\n\nVerdict: {data['verdict']}"
    return status


def publish(path, data):
    parent = path.parent
    if parent.stat().st_uid != os.geteuid() or parent.stat().st_mode & 0o077:
        raise ValueError("Snapshot directory must be private to the current user")
    if path.exists() and read_task(path)["task"] != data["task"]:
        raise ValueError("A snapshot belongs to one task")
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
    parser.add_argument("--verdict", choices=VERDICTS)
    parser.add_argument("--verdict-candidate")
    parser.add_argument("--url", help="Published loopback URL for this task")
    parser.add_argument("--chat-phase", choices=("start", "end"), help="Print chat text for a flight boundary")
    args = parser.parse_args()
    try:
        data = normalize(vars(args))
        status = chat_status(data, args.url, args.chat_phase)
        publish(args.file, data)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    if status:
        print(status)


if __name__ == "__main__":
    main()
