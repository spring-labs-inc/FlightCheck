"""Publish maintainer cards and check implementation reply footers."""

import argparse
import fcntl
import hashlib
import json
import os
import re
import select
import signal
import subprocess
import sys
import tempfile
import time
from http.client import HTTPConnection, HTTPException
from pathlib import Path

from task_details import task_id
from task_status import VERDICTS, chat_status, normalize, publish, read_task, task_path

FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def git(cwd, *args):
    return subprocess.check_output(["git", "--no-optional-locks", *args], cwd=cwd)


def git_path(cwd, *args):
    return Path(os.fsdecode(git(cwd, "rev-parse", *args).rstrip(b"\n"))).resolve()


def checkout_details(checkout):
    git_dir = git_path(checkout, "--path-format=absolute", "--git-dir")
    common_dir = git_path(checkout, "--path-format=absolute", "--git-common-dir")
    if git_dir != common_dir:
        return {"worktree": checkout.name}
    branch = os.fsdecode(git(checkout, "branch", "--show-current").rstrip(b"\n"))
    return {"branch": branch or None}


def candidate(checkout):
    digest = hashlib.sha256()
    for args in (
        ("rev-parse", "HEAD"),
        ("diff", "--no-ext-diff", "--no-textconv", "--binary", "HEAD", "--"),
        ("diff", "--cached", "--raw", "HEAD", "--"),
    ):
        digest.update(git(checkout, *args))
        digest.update(b"\0")
    for name in git(checkout, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0"):
        if name:
            metadata = (checkout / os.fsdecode(name)).lstat()
            digest.update(name + b"\0")
            digest.update(repr((metadata.st_mode, metadata.st_size, metadata.st_mtime_ns,
                                metadata.st_ctime_ns)).encode() + b"\0")
    return digest.hexdigest()


def private_dir(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = path.stat()
    if path.is_symlink() or metadata.st_uid != os.geteuid() or metadata.st_mode & 0o077:
        raise ValueError("FlightCheck state directories must be private to the current user")
    return path


def state_dir(checkout):
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "flightcheck"
    base = Path(os.environ.get("FLIGHTCHECK_STATE_DIR") or base).expanduser()
    if not base.is_absolute() or checkout in (base.resolve(), *base.resolve().parents):
        raise ValueError("FlightCheck state must use an absolute path outside the checkout")
    common = git_path(checkout, "--path-format=absolute", "--git-common-dir")
    namespace = hashlib.sha256(os.fsencode(common)).hexdigest()[:24]
    return private_dir(private_dir(base) / namespace)


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def write_json(path, value):
    fd, pending = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream)
        os.replace(pending, path)
    finally:
        Path(pending).unlink(missing_ok=True)


def task_dir(state, task):
    return private_dir(private_dir(state / "tasks") / task_id(task))


def turn_file(state, session):
    name = hashlib.sha256(session.encode()).hexdigest()
    return private_dir(state / "turns") / f"{name}.json"


def card_url(task, port):
    return f"http://127.0.0.1:{port}{task_path(task)}"


def current_card(task, port, expected_candidate):
    connection = HTTPConnection("127.0.0.1", port, timeout=0.75)
    try:
        connection.request("GET", task_path(task) + "status.json")
        response = connection.getresponse()
        if response.status != 200:
            return None
        status = json.loads(response.read(1024 * 1024))
        if (
            isinstance(status, dict) and status.get("snapshot") == "live" and status.get("task") == task
            and status.get("publicationPort") == port and status.get("candidate") == expected_candidate
        ):
            return status
    except (OSError, ValueError, HTTPException):
        return None
    finally:
        connection.close()
    return None


def checkout_matches(status, data):
    return all(status.get(key) == data.get(key) for key in ("branch", "worktree"))


def stop_outdated_listener(snapshot, data, endpoint):
    pid, port = endpoint.get("pid"), endpoint["port"]
    if type(pid) is not int or pid < 2:
        raise ValueError("The outdated card listener has no recorded process ID")
    process = subprocess.run(
        ["ps", "-ww", "-p", str(pid), "-o", "uid=", "-o", "command="],
        capture_output=True, text=True,
    )
    if process.returncode == 1 and not process.stdout.strip() and not process.stderr.strip():
        return
    process.check_returncode()
    fields = process.stdout.strip().split(maxsplit=1)
    suffixes = tuple(f"/status-card/serve.py --port {argument} --task-status {snapshot}"
                     for argument in (0, port))
    if len(fields) != 2 or fields[0] != str(os.geteuid()) or not fields[1].endswith(suffixes):
        raise ValueError("The recorded process does not match the outdated card listener")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if current_card(data["task"], port, data["candidate"]) is None:
            return
        time.sleep(0.05)
    raise ValueError("The outdated card listener did not stop")


def start_listener(snapshot, data, port):
    server = Path(__file__).with_name("serve.py")
    with (snapshot.parent / "listener.log").open("ab") as log:
        process = subprocess.Popen(
            [sys.executable, "-B", str(server), "--port", str(port), "--task-status", str(snapshot)],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=log, start_new_session=True,
        )
    try:
        line = process.stdout.readline() if select.select([process.stdout], [], [], 5)[0] else b""
        prefix = b"FlightCheck status card at http://127.0.0.1:"
        actual, _, _ = line[len(prefix):].partition(b"/")
        if not line.startswith(prefix) or not actual.isdigit():
            raise ValueError("Card listener could not start. Check listener.log in the task directory")
        actual_port = int(actual)
        status = current_card(data["task"], actual_port, data["candidate"])
        if (port and actual_port != port) or not status or not checkout_matches(status, data):
            raise ValueError("Card listener did not serve the current task")
        return {"port": actual_port, "pid": process.pid}
    except BaseException:
        process.terminate()
        process.wait(timeout=5)
        raise
    finally:
        process.stdout.close()


def show_card(checkout, state, args):
    directory = task_dir(state, args.task)
    snapshot = directory / "status.json"
    endpoint_file = directory / "endpoint.json"
    with (directory / "card.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = read_task(snapshot) if snapshot.exists() else {}
        current = candidate(checkout)
        data = normalize({
            "task": args.task, "title": args.title,
            "summary": args.summary if args.summary is not None else previous.get("summary", ""),
            "candidate": current,
            "verdict": args.verdict or previous.get("verdict"),
            "verdict_candidate": args.verdict_candidate if args.verdict else previous.get("verdict_candidate"),
        })
        details = json.loads(args.details.read_text(encoding="utf-8")) if args.details else {}
        if not isinstance(details, dict):
            raise ValueError("Expected a details object")
        details.pop("branch", None)
        details.pop("worktree", None)
        details.update(checkout_details(checkout))
        publish(snapshot, data, details)
        endpoint = read_json(endpoint_file)
        port = endpoint.get("port", 0)
        status = current_card(args.task, port, current) if port else None
        if status and not checkout_matches(status, data):
            stop_outdated_listener(snapshot, data, endpoint)
            status = None
        if not status:
            endpoint = start_listener(snapshot, data, port)
            write_json(endpoint_file, endpoint)
            port = endpoint["port"]

    if args.session:
        record_path = turn_file(state, args.session)
        record = read_json(record_path)
        if record:
            record.update(task=args.task, checkout=str(checkout))
            write_json(record_path, record)
    return chat_status(data, card_url(args.task, port), "start")


def has_footer(reply, footer):
    lines = reply.rstrip().splitlines()
    if not lines or lines[-1] != footer or (len(lines) > 1 and lines[-2].strip()):
        return False
    fence = ""
    for line in lines[:-1]:
        match = FENCE.match(line)
        if match:
            marker, suffix = match.groups()
            if not fence:
                fence = marker
            elif marker.startswith(fence) and not suffix.strip():
                fence = ""
    return not fence


def check_turn(checkout, state, event):
    session, turn = event.get("session_id"), event.get("turn_id")
    if not session or not turn:
        return {}
    record_path = turn_file(state, session)
    record = read_json(record_path)
    if event["hook_event_name"] == "UserPromptSubmit":
        if record.get("turn") != turn:
            write_json(record_path, {"turn": turn, "baseline": candidate(checkout)})
        return {}
    if event["hook_event_name"] != "Stop" or record.get("turn") != turn:
        return {}

    task = record.get("task")
    current = candidate(Path(record["checkout"]) if task else checkout)
    if not task and current == record["baseline"]:
        return {}
    if task:
        port = read_json(task_dir(state, task) / "endpoint.json").get("port")
        if port and current_card(task, port, current):
            footer = chat_status({"task": task}, card_url(task, port), "start")
            if has_footer(event.get("last_assistant_message") or "", footer):
                return {}

    reason = (
        "This turn contains FlightCheck implementation work. Run the maintainer card command "
        "for the current task and put its exact clickable link on the last line of your reply."
    )
    if event.get("stop_hook_active"):
        return {"systemMessage": "FlightCheck could not verify the implementation footer after a retry."}
    return {"decision": "block", "reason": reason}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    card = commands.add_parser("card")
    card.add_argument("--task", type=task_id, required=True)
    card.add_argument("--title", required=True)
    card.add_argument("--summary")
    card.add_argument("--details", type=Path)
    card.add_argument("--verdict", choices=VERDICTS)
    card.add_argument("--verdict-candidate")
    card.add_argument("--session", default=os.environ.get("CODEX_THREAD_ID"))
    commands.add_parser("hook")
    args = parser.parse_args()
    try:
        if args.command == "hook":
            event = json.load(sys.stdin)
            checkout = git_path(event["cwd"], "--show-toplevel")
            print(json.dumps(check_turn(checkout, state_dir(checkout), event)))
        else:
            if bool(args.verdict) != bool(args.verdict_candidate):
                raise ValueError("Pass --verdict and --verdict-candidate together")
            checkout = git_path(Path.cwd(), "--show-toplevel")
            print(show_card(checkout, state_dir(checkout), args))
    except (KeyError, OSError, ValueError, subprocess.SubprocessError) as error:
        if args.command == "hook":
            print(json.dumps({"systemMessage": f"FlightCheck could not verify this turn: {error}"}))
        else:
            parser.error(str(error))


if __name__ == "__main__":
    main()
