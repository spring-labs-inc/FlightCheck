"""Run a project-native check and retain its output in a private run directory."""

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import nullcontext
from pathlib import Path

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
PYTEST_FOOTER = re.compile(r"(?P<counts>.+) in \d+(?:\.\d+)?s(?: \([\d:]+\))?")
PYTEST_COUNT = re.compile(
    r"(\d+) (passed|failed|errors?|skipped|deselected|xfailed|xpassed|warnings?|"
    r"subtests? passed|subtests? failed|reruns?)"
)
WARNING_HEADING = re.compile(r"=+ warnings summary(?: \(final\))? =+")


def pytest_summary(log):
    """Recognize pytest's final totals. Unknown output carries no warning count."""
    footer = ""
    has_warning_section = False
    with log.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            line = ANSI.sub("", line).strip()
            if line:
                footer = line.strip("= ")
                has_warning_section |= WARNING_HEADING.fullmatch(line) is not None

    match = PYTEST_FOOTER.fullmatch(footer)
    parts = match["counts"].split(", ") if match else []
    counts = [PYTEST_COUNT.fullmatch(part) for part in parts]
    if not counts or not all(counts):
        return {}, {"status": "unavailable", "count": None}
    totals = {item[2]: int(item[1]) for item in counts}
    count = totals.get("warnings", totals.get("warning", 0))
    status = "unavailable"
    if count == 0:
        status = "none"
    elif has_warning_section:
        status = "complete"
    return totals, {"status": status, "count": count}


def write_json(path, value):
    pending = path.with_suffix(".tmp")
    pending.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    pending.replace(path)


def fingerprint_argv(raw):
    try:
        argv = json.loads(raw)
        if isinstance(argv, list) and argv and all(isinstance(arg, str) and arg for arg in argv):
            return argv
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("expected a JSON array of command arguments")


def fingerprint(command):
    if command is None:
        return None
    try:
        result = subprocess.run(command, check=False, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
    except OSError:
        return None
    return hashlib.sha256(result.stdout).hexdigest() if result.returncode == 0 and result.stdout.strip() else None


def latest_run(parent, latest):
    run_id = json.loads(latest.read_text(encoding="utf-8"))
    if not isinstance(run_id, str) or not re.fullmatch(r"check-[a-zA-Z0-9_]+", run_id):
        raise ValueError("Invalid check run identifier")
    run = parent / run_id
    packet = json.loads((run / "run.json").read_text(encoding="utf-8"))
    if packet["run_id"] != run_id:
        raise ValueError("Check receipt does not match the latest run")
    return run, packet


def matches_pass(run, packet, request, current):
    if (current is None or packet["request"] != request or packet["status"] != "finished"
            or packet["exit_code"] != 0 or packet["inputs_before"] != current
            or packet["inputs_after"] != current):
        return False
    output = packet["output"]
    if (output["path"] != "output.log" or output["status"] != "complete"
            or digest(run / "output.log") != output["sha256"]):
        return False
    return all(digest(run / f"artifact-{index}") == packet["artifacts"][artifact]
               for index, artifact in enumerate(request["artifacts"]))


def evidence_directory(path, worktree, create=False):
    parent = path.resolve()
    worktree = worktree.resolve()
    try:
        git = subprocess.run(["git", "-C", str(worktree), "rev-parse", "--show-toplevel"],
                             stdin=subprocess.DEVNULL, capture_output=True, text=True)
        if git.returncode == 0:
            worktree = Path(git.stdout.strip()).resolve()
    except OSError:
        pass  # Non-Git projects still use the configured working directory.
    if parent == worktree or worktree in parent.parents:
        raise ValueError("evidence directory must be outside the project checkout")
    if create:
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not parent.is_dir() or parent.stat().st_uid != os.geteuid() or parent.stat().st_mode & 0o077:
        raise ValueError("evidence directory must exist and be private to the current user")
    return parent


def previous_pass(parent, latest, request, current):
    try:
        run, packet = latest_run(parent, latest)
        return run if matches_pass(run, packet, request, current) else None
    except (OSError, ValueError, TypeError, KeyError):
        return None


def run_command(command, output, env=None):
    """Forward terminal interrupts to the check's own process group."""
    with subprocess.Popen(
        command, stdout=output, stderr=subprocess.STDOUT, start_new_session=True,
        stdin=subprocess.DEVNULL, env=env,
    ) as child:
        def forward(signum, _frame):
            try:
                os.killpg(child.pid, signum)
            except ProcessLookupError:
                pass

        previous = {sig: signal.signal(sig, forward) for sig in (signal.SIGINT, signal.SIGTERM)}
        try:
            return child.wait()
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(64 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def replay(log):
    try:
        with log.open("rb") as stream:
            shutil.copyfileobj(stream, sys.stdout.buffer)
        sys.stdout.buffer.flush()
    except BrokenPipeError:
        # The original is already committed to the run directory.
        with open(os.devnull, "wb") as sink:
            os.dup2(sink.fileno(), sys.stdout.fileno())


def capture(args, command, worktree, parent, latest, request, before):
    run = Path(tempfile.mkdtemp(prefix="check-", dir=parent))
    log = run / "output.log"
    packet = {
        "run_id": run.name,
        "candidate": args.candidate,
        "command": command,
        "cwd": str(worktree),
        "coverage": {"requested": args.scope, "reported": {}},
        "started_at": time.time(),
        "exit_code": None,
        "status": "incomplete",
        "output": {"path": log.name, "status": "incomplete", "sha256": None},
        "warnings": {"status": "incomplete", "count": None},
    }
    if latest:
        packet.update(request=request, inputs_before=before, inputs_after=None, artifacts={})
        if args.owner:
            packet["owner"] = args.owner
    write_json(run / "run.json", packet)
    if latest:
        write_json(latest, run.name)
    print(f"Check evidence: {run}", flush=True)

    environment = None
    if args.isolated_reports:
        reports = run / "reports"
        reports.mkdir(mode=0o700)
        environment = dict(os.environ, FLIGHTCHECK_REPORT_DIR=str(reports))
        packet["report_directory"] = str(reports)

    with log.open("xb") as output:
        try:
            code = run_command(command, output, environment)
        except OSError as error:
            packet.update(status="unavailable", finished_at=time.time(), error=str(error))
            packet["output"]["status"] = "unavailable"
            packet["warnings"]["status"] = "unavailable"
            write_json(run / "run.json", packet)
            print(f"Could not start check: {error}", file=sys.stderr)
            return 127

    interrupted = code < 0 or code in (130, 143) or (args.summary == "pytest" and code == 2)
    packet.update(
        exit_code=code,
        status="interrupted" if interrupted else "finished",
        finished_at=time.time(),
    )
    packet["output"].update(
        status="incomplete" if interrupted else "complete",
        sha256=digest(log),
    )
    if not interrupted and args.summary == "pytest":
        totals, warnings = pytest_summary(log)
        packet["coverage"]["reported"] = totals
        packet["warnings"] = warnings
    elif not interrupted:
        packet["warnings"]["status"] = "unclassified"
    # Retain failing reproductions as well as passes. They never qualify for reuse.
    if latest and not interrupted:
        for index, artifact in enumerate(args.artifact):
            retained = run / f"artifact-{index}"
            try:
                source = (run / "reports" / artifact) if args.isolated_reports else Path(artifact)
                if args.isolated_reports and (source.is_symlink() or (run / "reports").resolve() not in source.resolve().parents):
                    raise OSError("Report link escapes or aliases the isolated report directory")
                shutil.copyfile(source, retained)
                packet["artifacts"][artifact] = digest(retained)
            except OSError as error:
                print(f"Cannot retain {artifact}: {error}", file=sys.stderr)
        packet["inputs_after"] = fingerprint(args.fingerprint_command)
    write_json(run / "run.json", packet)
    replay(log)
    return 128 - code if code < 0 else code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--create-evidence-dir", action="store_true", help="Create the configured private evidence directory if absent")
    parser.add_argument("--candidate", required=True, help="Frozen candidate identity")
    parser.add_argument("--scope", required=True, help="Intended gate coverage")
    parser.add_argument("--summary", choices=("pytest",), help="Interpret tool-specific totals")
    parser.add_argument("--gate", help="Stable identifier for a reusable check")
    parser.add_argument("--owner", choices=("worker", "controller"), help="Role responsible for this check run")
    parser.add_argument("--fingerprint-command", type=fingerprint_argv, help="JSON argv for the gate input probe")
    parser.add_argument("--artifact", action="append", default=[], help="Report file to retain, repeatable")
    parser.add_argument("--isolated-reports", action="store_true",
                        help="Set FLIGHTCHECK_REPORT_DIR to a fresh run directory; artifacts are relative to it")
    parser.add_argument("--refresh", action="store_true", help="Run the gate even if a reusable pass exists")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if len(args.command) < 2 or args.command[0] != "--":
        parser.error("pass the exact check command after --")
    if not args.candidate.strip() or not args.scope.strip():
        parser.error("candidate and scope must be nonempty")
    command = args.command[1:]

    worktree = Path.cwd()
    try:
        parent = evidence_directory(args.evidence_dir, worktree, args.create_evidence_dir)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if args.gate and not re.fullmatch(r"[a-zA-Z0-9_-]+", args.gate):
        parser.error("--gate must contain only letters, digits, underscores or dashes")
    if bool(args.gate) != bool(args.fingerprint_command):
        parser.error("--gate and --fingerprint-command must be used together")
    if (args.artifact or args.refresh or args.owner or args.isolated_reports) and not args.gate:
        parser.error("--artifact, --refresh, --owner and --isolated-reports require --gate")
    if args.artifact and not args.isolated_reports:
        parser.error("artifacts require --isolated-reports; produce reports in FLIGHTCHECK_REPORT_DIR")
    if len(set(args.artifact)) != len(args.artifact):
        parser.error("artifact paths must be unique")
    if args.isolated_reports and any(Path(a).is_absolute() or ".." in Path(a).parts for a in args.artifact):
        parser.error("isolated artifact paths must stay inside the run's report directory")

    latest = parent / f"gate-{args.gate}.json" if args.gate else None
    lock = latest.with_suffix(".lock").open("a") if latest else nullcontext()
    request = {
        "command": command,
        "scope": args.scope,
        "summary": args.summary,
        "fingerprint_command": args.fingerprint_command,
        "artifacts": args.artifact,
    }
    if args.isolated_reports:
        request["isolated_reports"] = True
    with lock as lock_file:
        if lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
        before = fingerprint(args.fingerprint_command)
        if latest and not args.refresh:
            run = previous_pass(parent, latest, request, before)
            if run and fingerprint(args.fingerprint_command) == before:
                reuse = Path(tempfile.mkdtemp(prefix="reuse-", dir=parent))
                write_json(reuse / "reuse.json", {
                    "gate": args.gate, "candidate": args.candidate, "cwd": str(worktree),
                    "source_run_id": run.name, "source_receipt_sha256": digest(run / "run.json"),
                    "inputs": before, "reused_at": time.time(),
                })
                print(f"Check reused: {run} (decision: {reuse / 'reuse.json'})", flush=True)
                return 0
        return capture(args, command, worktree, parent, latest, request, before)


if __name__ == "__main__":
    raise SystemExit(main())
