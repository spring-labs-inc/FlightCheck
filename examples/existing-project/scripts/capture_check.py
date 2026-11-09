"""Run a project-native check and retain its output in a private run directory."""

import argparse
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


def write_packet(run, packet):
    pending = run / "run.json.tmp"
    pending.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")
    pending.replace(run / "run.json")


def run_command(command, output):
    """Forward terminal interrupts to the check's own process group."""
    with subprocess.Popen(
        command, stdout=output, stderr=subprocess.STDOUT, start_new_session=True,
        stdin=subprocess.DEVNULL,
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--candidate", required=True, help="Frozen candidate identity")
    parser.add_argument("--scope", required=True, help="Intended gate coverage")
    parser.add_argument("--summary", choices=("pytest",), help="Interpret tool-specific totals")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if len(args.command) < 2 or args.command[0] != "--":
        parser.error("pass the exact check command after --")
    if not args.candidate.strip() or not args.scope.strip():
        parser.error("candidate and scope must be nonempty")
    command = args.command[1:]

    parent = args.evidence_dir.resolve()
    worktree = Path.cwd()
    if parent == worktree or worktree in parent.parents:
        parser.error("evidence directory must be outside the project checkout")
    if not parent.is_dir() or parent.stat().st_uid != os.geteuid() or parent.stat().st_mode & 0o077:
        parser.error("evidence directory must exist and be private to the current user")
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
    write_packet(run, packet)
    print(f"Check evidence: {run}", flush=True)

    with log.open("xb") as output:
        try:
            code = run_command(command, output)
        except OSError as error:
            packet.update(status="unavailable", finished_at=time.time(), error=str(error))
            packet["output"]["status"] = "unavailable"
            packet["warnings"]["status"] = "unavailable"
            write_packet(run, packet)
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
    write_packet(run, packet)
    replay(log)
    return 128 - code if code < 0 else code


if __name__ == "__main__":
    raise SystemExit(main())
