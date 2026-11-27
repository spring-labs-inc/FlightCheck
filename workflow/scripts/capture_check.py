"""Run a project-native check and retain its output in a private run directory."""

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import nullcontext
from pathlib import Path

def standalone_context(worktree, task=None, phase="check"):
    """Locate selection without verifying it when only this script was copied.

    This reads the canonical Registry solely to refuse selected execution. It
    never creates state, adopts ownership, or substitutes for the real verifier.
    """
    unavailable = "Checkout verifier unavailable; restore the complete FlightCheck helpers before selected execution"
    if ((isinstance(task, dict) and "checkout_binding" in task)
            or "FLIGHTCHECK_REGISTRY" in os.environ or "FLIGHTCHECK_FLIGHT" in os.environ):
        raise ValueError(unavailable)
    context = {"schema": 1, "status": "unbound", "checkout": {"path": str(Path(worktree).resolve())},
               "limits": ["Standalone copied recorder; checkout verifier unavailable and no selected flight discovered"]}
    try:
        def git(*args):
            return subprocess.run(
                ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(worktree), *args],
                stdin=subprocess.DEVNULL, capture_output=True,
                env=dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0"), timeout=10)

        observed = git("rev-parse", "--show-toplevel")
        if observed.returncode:
            if b"not a git repository" in observed.stderr:
                return context
            raise ValueError(unavailable)
        root = Path(os.fsdecode(observed.stdout).rstrip("\n")).resolve(strict=True)
        observed = git("rev-parse", "--path-format=absolute", "--git-common-dir")
        if observed.returncode:
            raise ValueError(unavailable)
        common = Path(os.fsdecode(observed.stdout).rstrip("\n")).resolve(strict=True)
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "flightcheck"
        base = Path(os.environ.get("FLIGHTCHECK_STATE_DIR") or base).expanduser()
        if not base.is_absolute() or root in (base.resolve(), *base.resolve().parents):
            raise ValueError(unavailable)
        base = base.resolve()
        namespace = hashlib.sha256(os.fsencode(common)).hexdigest()[:24]
        directory = base / namespace / "flight-associations"
        path = directory / "associations.json"
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError(unavailable)
        if directory.exists():
            info = directory.stat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise ValueError(unavailable)
        if not path.exists():
            return context
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError(unavailable)
        value = json.loads(path.read_bytes())
        if not isinstance(value, dict) or value.get("schema") != 1 or not isinstance(value.get("records"), list):
            raise ValueError(unavailable)
        for record in value["records"]:
            state = record["lifecycle"]["state"]
            if state not in ("active", "paused", "review", "merged", "closed"):
                raise ValueError(unavailable)
            if not isinstance(record["children"], list):
                raise ValueError(unavailable)
            for item in [record["checkout"], *record["children"]]:
                owned = item["path"]
                if not isinstance(owned, str) or not Path(owned).is_absolute():
                    raise ValueError(unavailable)
                if state != "closed" and Path(owned).resolve() == root:
                    raise ValueError(unavailable)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        # Do not disclose raw Registry contents or private paths in diagnostics.
        raise ValueError(unavailable) from None
    return context


if importlib.util.find_spec("checkout_guard") is None:
    guard_context = standalone_context
else:
    # A present helper with broken dependencies is an error, never legacy use.
    from checkout_guard import guard_context, settings_execution


def checkout_identity(context):
    """Stable execution identity; unrelated Registry edits do not stale proof."""
    if not context or context.get("status") != "verified":
        return None
    return {key: context[key] for key in ("checkout_binding", "binding_digest", "head_binding")}


def same_checkout(before, after):
    return checkout_identity(before) == checkout_identity(after)


def same_pass_checkout(before, after, dependencies=None):
    """Narrow settings-only reuse; never used to excuse a mid-check change."""
    if same_checkout(before, after):
        return True
    known_roots = {"resources", "activation", "activation_reference", "nit_tracker", "policy_reference", "cleanup_policy", "checkout_policy", "protected_branches", "default_branch", "preview", "evidence_dir", "reviewer_access", "review_client", "delivery", "checks", "python", "observed_python", "required_runtimes", "status_sync"}
    if dependencies is not None and (not isinstance(dependencies, list) or any(not isinstance(key, str) or key.split(".")[0] not in known_roots for key in dependencies)):
        return False
    if (dependencies is None or not before or not after or not before.get("execution_digest")
            or before.get("execution_digest") != after.get("execution_digest")):
        return False
    current = before.get("configuration_revision")
    known = {"resources", "activation", "activation_reference", "nit_tracker", "policy_reference",
             "cleanup_policy", "checkout_policy", "protected_branches", "default_branch", "preview",
             "evidence_dir", "reviewer_access", "review_client", "delivery", "checks", "python", "observed_python", "required_runtimes", "status_sync"}
    risky = {"checks", "python", "observed_python", "required_runtimes", "status_sync", "delivery"}
    for decision in after.get("settings_adoptions", []):
        if decision.get("from_revision") != current:
            continue
        changed = set(decision.get("changed_fields", []))
        if "status_sync" in decision.get("required_revalidation", []) and any(dep.split(".")[0] == "status_sync" for dep in dependencies):
            return False
        if changed - known or changed & risky or any(key == dep or key.startswith(dep + ".") or dep.startswith(key + ".") for key in changed for dep in dependencies):
            return False
        current = decision.get("to_revision")
        if current == after.get("configuration_revision"):
            return True
    return False


def verify_checkout(worktree, task=None, before=None, phase="check"):
    context = guard_context(worktree, task=task, phase=phase)
    if before is not None and not same_checkout(before, context):
        raise ValueError("Checkout execution identity changed; reconcile before continuing")
    return context


def checkout_binding(raw):
    try:
        value = json.loads(raw)
        if (isinstance(value, dict) and all(isinstance(value.get(key), str) and value[key].strip()
                                           for key in ("registry", "flight"))):
            return value
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("expected a checkout binding object with registry and flight")


def status_activity(worktree, args, run_id):
    """Optional projection bridge, never a governing receipt or test outcome."""
    # The source and installed layouts keep card helpers adjacent to the shared
    # scripts. No network lookup, arbitrary module search or archive scan occurs.
    script = Path(__file__).resolve()
    candidates = (script.parents[2] / "status-card", script.parents[1] / "status-card")
    card = next((path for path in candidates if (path / "progress.py").is_file()), None)
    if card is None:
        return None
    try:
        sys.path.insert(0, str(card))
        from progress import selected_activity
        return selected_activity(worktree, args.candidate, run_id, args.gate or args.scope)
    except Exception as error:
        print(f"Progress projection unavailable: {error}", file=sys.stderr)
        return None
    finally:
        if sys.path and sys.path[0] == str(card):
            sys.path.pop(0)


def project_activity(activity, method, *args, **kwargs):
    if activity is not None:
        try:
            return getattr(activity, method)(*args, **kwargs)
        except Exception as error:
            # Projection failure cannot change native output or command status.
            print(f"Progress projection unavailable: {error}", file=sys.stderr)

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


def matches_pass(run, packet, request, current, checkout_context=None):
    if (not same_pass_checkout(packet.get("checkout_context"), checkout_context, request.get("configuration_dependencies"))
            or not same_pass_checkout(packet.get("checkout_context_after"), checkout_context, request.get("configuration_dependencies"))):
        return False
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


def previous_pass(parent, latest, request, current, checkout_context=None):
    try:
        run, packet = latest_run(parent, latest)
        return run if matches_pass(run, packet, request, current, checkout_context) else None
    except (OSError, ValueError, TypeError, KeyError):
        return None


def run_command(command, output, env=None, activity=None, lease=None):
    """Forward terminal interrupts to the check's own process group."""
    with subprocess.Popen(
        command, stdout=output, stderr=subprocess.STDOUT, start_new_session=True,
        stdin=subprocess.DEVNULL, env=env, pass_fds=(() if lease is None else (lease,)),
    ) as child:
        def forward(signum, _frame):
            try:
                os.killpg(child.pid, signum)
            except ProcessLookupError:
                pass

        previous = {sig: signal.signal(sig, forward) for sig in (signal.SIGINT, signal.SIGTERM)}
        try:
            while True:
                try:
                    return child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    project_activity(activity, "heartbeat")
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


def capture(args, command, worktree, parent, latest, request, before, checkout_context=None, checkout_task=None, lease=None):
    # Input probes are executable too. Verify again after the probe and before
    # creating an attempt that could launch a native command.
    checkout_context = verify_checkout(worktree, checkout_task, checkout_context)
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
        "checkout_context": checkout_context,
    }
    if latest:
        packet.update(request=request, inputs_before=before, inputs_after=None, artifacts={})
        if args.owner:
            packet["owner"] = args.owner
    write_json(run / "run.json", packet)
    if latest:
        write_json(latest, run.name)
    print(f"Check evidence: {run}", flush=True)
    activity = status_activity(worktree, args, run.name)
    project_activity(activity, "begin")

    environment = None
    if args.isolated_reports:
        reports = run / "reports"
        reports.mkdir(mode=0o700)
        environment = dict(os.environ, FLIGHTCHECK_REPORT_DIR=str(reports))
        packet["report_directory"] = str(reports)

    with log.open("xb") as output:
        try:
            code = run_command(command, output, environment, activity, lease)
        except OSError as error:
            packet.update(status="unavailable", finished_at=time.time(), error=str(error))
            packet["output"]["status"] = "unavailable"
            packet["warnings"]["status"] = "unavailable"
            write_json(run / "run.json", packet)
            project_activity(activity, "end", "unavailable")
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
    checkout_error = None
    try:
        packet["checkout_context_after"] = verify_checkout(worktree, checkout_task, checkout_context)
    except (OSError, ValueError) as error:
        checkout_error = str(error)
        packet.update(status="checkout-drift", checkout_error=checkout_error)
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
        if checkout_error is None:
            packet["inputs_after"] = fingerprint(args.fingerprint_command)
            try:
                packet["checkout_context_after"] = verify_checkout(worktree, checkout_task, checkout_context)
            except (OSError, ValueError) as error:
                checkout_error = str(error)
                packet.update(status="checkout-drift", checkout_error=checkout_error)
    write_json(run / "run.json", packet)
    counts = {key: value for key, value in packet["coverage"]["reported"].items()
              if key in ("passed", "failed", "errors", "skipped", "warnings")}
    project_activity(activity, "end", "interrupted" if interrupted else "completed" if code == 0 else "failed", counts=counts)
    replay(log)
    if checkout_error:
        print("Checkout verification failed: " + checkout_error, file=sys.stderr)
        return 2
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
    parser.add_argument("--adopt-project-settings", action="store_true", help="Controller-owned execution boundary; never a read-only review admission")
    parser.add_argument("--configuration-dependencies", type=json.loads, help="Frozen known configuration dependencies for settings-only pass reuse; absent is conservative")
    parser.add_argument("--fingerprint-command", type=fingerprint_argv, help="JSON argv for the gate input probe")
    parser.add_argument("--artifact", action="append", default=[], help="Report file to retain, repeatable")
    parser.add_argument("--isolated-reports", action="store_true",
                        help="Set FLIGHTCHECK_REPORT_DIR to a fresh run directory; artifacts are relative to it")
    parser.add_argument("--refresh", action="store_true", help="Run the gate even if a reusable pass exists")
    parser.add_argument("--checkout-binding", type=checkout_binding,
                        help="Explicit selected flight binding JSON (registry and flight)")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if len(args.command) < 2 or args.command[0] != "--":
        parser.error("pass the exact check command after --")
    if not args.candidate.strip() or not args.scope.strip():
        parser.error("candidate and scope must be nonempty")
    command = args.command[1:]

    worktree = Path.cwd()
    checkout_task = ({"checkout_binding": args.checkout_binding} if args.checkout_binding is not None else None)
    if args.configuration_dependencies is not None and (not isinstance(args.configuration_dependencies, list) or any(not isinstance(key, str) or not key for key in args.configuration_dependencies)):
        parser.error("configuration dependencies must be a JSON array of known field names")
    boundary = settings_execution(worktree, checkout_task, adopt=args.owner == "worker" or args.adopt_project_settings) if importlib.util.find_spec("checkout_guard") is not None else nullcontext(None)
    with boundary as lease:
        return selected_capture(args, command, worktree, checkout_task, lease, parser)


def selected_capture(args, command, worktree, checkout_task, lease, parser):
    try:
        checkout_task = ({"checkout_binding": args.checkout_binding}
                         if args.checkout_binding is not None else None)
        checkout_context = verify_checkout(worktree, checkout_task)
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
    if args.configuration_dependencies is not None:
        request["configuration_dependencies"] = args.configuration_dependencies
    if args.isolated_reports:
        request["isolated_reports"] = True
    with lock as lock_file:
        if lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            checkout_context = verify_checkout(worktree, checkout_task, checkout_context)
            before = fingerprint(args.fingerprint_command)
            verify_checkout(worktree, checkout_task, checkout_context)
        except (OSError, ValueError) as error:
            parser.error(str(error))
        if latest and not args.refresh:
            run = previous_pass(parent, latest, request, before, checkout_context)
            if run and fingerprint(args.fingerprint_command) == before:
                try:
                    verify_checkout(worktree, checkout_task, checkout_context)
                except (OSError, ValueError) as error:
                    parser.error(str(error))
                reuse = Path(tempfile.mkdtemp(prefix="reuse-", dir=parent))
                write_json(reuse / "reuse.json", {
                    "gate": args.gate, "candidate": args.candidate, "cwd": str(worktree),
                    "source_run_id": run.name, "source_receipt_sha256": digest(run / "run.json"),
                    "inputs": before, "reused_at": time.time(),
                    "checkout_context": checkout_context,
                })
                print(f"Check reused: {run} (decision: {reuse / 'reuse.json'})", flush=True)
                return 0
        try:
            return capture(args, command, worktree, parent, latest, request, before,
                           checkout_context, checkout_task, lease)
        except (OSError, ValueError) as error:
            parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
