"""Terminal entry points for the shared project card and browser-machine SSH connector."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from . import transaction as tx
from .source import installer, sha


def execute(action, project, arguments):
    with installer() as (module, source, manifest, identity):
        if action == "connect":
            # The browser machine needs only the installed CLI. Its remote
            # project owns the persistent worker helper and interpreter.
            command = [sys.executable, "-B", str(source / "status-card/connect.py"), *arguments]
            return subprocess.run(command, capture_output=True, text=True)
        from .cli import PIN, runtime_identity, target
        root = target(module, project)
        if tx.pending(root):
            raise ValueError("Interrupted installation; run flightcheck recover first")
        state = module.read_state(root)
        if not state or ".flightcheck/status-card/connect.py" not in state["files"]:
            raise ValueError("This project needs an installation with the shared status-card startup helpers")
        for name, record in state["files"].items():
            if name.startswith(".flightcheck/status-card/") or name == module.CONFIG:
                if sha(module.safe_path(root, name).read_bytes()) != record["sha256"]:
                    raise ValueError("Modified required status-card component: " + name)
        config = json.loads(module.safe_path(root, module.CONFIG).read_text())
        pin_path = module.safe_path(root, PIN)
        if pin_path.exists() and runtime_identity(config) != json.loads(pin_path.read_text())["runtime"]:
            raise ValueError("Pinned project Python changed; restore its configured runtime")
        env = dict(os.environ)
        env.setdefault("FLIGHTCHECK_STATE_DIR", str(Path(config["evidence_dir"]) / "status-card"))
        command = [config["python"], "-B", str(root / ".flightcheck/status-card/reply.py"), action, *arguments]
        return subprocess.run(command, cwd=root, env=env, capture_output=True, text=True)


def main(argv):
    arguments = list(argv)
    action = arguments.pop(0) if arguments and arguments[0] in ("prepare", "check", "connect") else "prepare"
    parser = argparse.ArgumentParser(
        prog="flightcheck card " + action,
        description="Start/verify a project card, check a reply, or connect from the browser machine over SSH. Shared helper options follow --project/--json.",
        epilog="Local: flightcheck card --project . --task TASK --details /private/details.json. SSH: flightcheck card connect --ssh WORKER --checkout /remote/project --task TASK --remote-python /configured/python --remote-state-dir /private/state.",
    )
    parser.add_argument("--project", default=".", help="Installed local project (prepare/check)")
    parser.add_argument("--json", action="store_true", help="Return the helper's complete structured result")
    args, forwarded = parser.parse_known_args(arguments)
    try:
        run = execute(action, args.project, forwarded)
        try:
            result = json.loads(run.stdout)
            if not isinstance(result, dict):
                raise ValueError("Status helper did not return an object")
        except ValueError:
            raise ValueError("Status helper failed: " + (run.stderr.strip() or "invalid startup response")) from None
        code = run.returncode
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        result = {"status": "unavailable", "error": str(error), "footer": "FlightCheck: &lt; status /&gt;"}
        code = 1
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        diagnostic = result.get("error") or result.get("guidance")
        if diagnostic:
            print(diagnostic, file=sys.stderr if code else sys.stdout)
        print(result.get("footer", "FlightCheck: &lt; status /&gt;"))
    return code
