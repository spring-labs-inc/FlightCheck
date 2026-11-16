"""Explicit terminal setup; no package-install/import-time project mutations."""
import argparse
import difflib
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys
from importlib import metadata

from . import transaction as tx
from .source import encoded, installer, load_installer, sha

PIN = ".flightcheck/distribution.json"


def target(module, value):
    path = tx.no_links(Path(value).expanduser().absolute())
    return module.repository(path)


def runtime_identity(config):
    requested = Path(config["python"]).absolute()
    if sys.prefix != sys.base_prefix and Path(sys.prefix) in requested.parents:
        raise ValueError("Select the project's existing Python, not the FlightCheck tool environment")
    resolved = requested.resolve(strict=True)
    observed = json.loads(subprocess.check_output(
        [str(requested), "-B", "-c", "import json,sys;print(json.dumps({'prefix':sys.prefix,'base_prefix':sys.base_prefix,'executable':sys.executable}))"],
        text=True, stderr=subprocess.PIPE, timeout=10))
    if sys.prefix != sys.base_prefix:
        own = Path(sys.prefix).resolve()
        selected_prefix = Path(observed["prefix"]).resolve()
        selected_executable = Path(observed["executable"]).absolute()
        if selected_prefix == own or own in selected_executable.parents:
            raise ValueError("Select the project's existing Python, not a wrapper around the FlightCheck tool environment")
    return {"requested": str(requested), "resolved": str(resolved), "sha256": sha(resolved.read_bytes()),
            "observed": {**config["observed_python"], **observed}}



def make_plan(module, source, manifest, bundle_id, root, agent, supplied):
    if tx.pending(root):
        raise ValueError("An interrupted installation needs flightcheck recover before planning")
    canonical = module.load_manifest()
    result, config, operations = module.plan_installation(source, root, canonical, agent, supplied)
    runtime = runtime_identity(config)
    pin = {"schema": 1, "distribution": manifest["distribution"], "version": manifest["version"],
           "bundle": bundle_id, "source_revision": manifest["source_revision"],
           "development": manifest["development"], "runtime": runtime}
    old, _ = tx.file_state(module, root, PIN)
    after = encoded(pin)
    operations.append({"path": PIN, "before": old, "after": after,
                       "action": "unchanged" if old == after else "update" if old is not None else "create"})
    if module.read_state(root) and any(op["action"] != "unchanged" for op in operations):
        raise ValueError("Existing installation differs. This version supports fresh setup and identical repeats; migrations/upgrades are not supported. Existing files were preserved.")
    repository = module.git(root, "rev-parse", "--git-common-dir")
    repo_path = (root / repository).resolve() if not Path(repository).is_absolute() else Path(repository).resolve()
    document = {"schema": 1, "target": str(root), "repository": str(repo_path), "agent": agent,
                "bundle": bundle_id, "distribution": pin, "source": result["source"], "configuration": config,
                "operations": tx.operation_state(module, root, operations)}
    return document, operations


def with_digest(document):
    return {**document, "plan_sha256": sha(encoded(document))}


def read_plan(path):
    path = tx.no_links(Path(path).expanduser().absolute())
    value = json.loads(path.read_text())
    digest = value.pop("plan_sha256", None)
    if value.get("schema") != 1 or sha(encoded(value)) != digest:
        raise ValueError("Reviewed plan digest mismatch")
    return value


def ask(label, default=None):
    response = input(label + (" [" + str(default) + "]" if default is not None else "") + ": ").strip()
    value = response or default
    if not value:
        raise ValueError("A value is required for " + label)
    return value


def choices(module, root, agent, path):
    if path:
        config = json.loads(tx.no_links(Path(path).expanduser().absolute()).read_text())
        return agent, config
    if module.read_state(root):
        if not agent:
            agent = module.read_state(root)["agent"]
        return agent, json.loads(module.safe_path(root, module.CONFIG).read_text())
    if not sys.stdin.isatty():
        raise ValueError("Noninteractive setup requires explicit --agent and --config. Run flightcheck inspect for detected project choices.")
    detected = module.inspect_project(root)
    print("Project instructions/configuration: " + ", ".join(detected["existing_configuration"]))
    print("Confirm project choices together. Existing instructions/dependencies/settings are preserved; no provider permissions are granted.")
    agent = agent or ask("Client: codex, claude, or both")
    existing_python = root / ".venv/bin/python"
    python = str(existing_python) if existing_python.is_file() else str(Path(getattr(sys, "_base_executable", sys.executable)).resolve())
    config = {"activation": "opt-in", "delivery": "No provider writes without owner approval",
              "python": ask("Project Python (existing environment)", python),
              "default_branch": ask("Actual default branch", detected["default_branch"]),
              "evidence_dir": ask("Private evidence directory outside project", str(tx.directory(root) / "evidence")),
              "nit_tracker": ask("Nit tracker", "Private project notes; no provider writes"),
              "policy_reference": ask("Project policy/setup decision reference", "Existing project instructions and owner-confirmed terminal setup"),
              "reviewer_access": ask("Reviewer access decision/reference (no permissions are installed)", "Pending native read-only probe; no automatic grants")}
    command = shlex.split(ask("Existing non-mutating project check command"))
    if not command:
        raise ValueError("A project check command is required")
    phase = ask("Check phase: cheap or authoritative", "cheap")
    config["checks"] = [{"name": "Project checks", "command": command, "phase": phase}]
    print("Activation: explicit opt-in. Delivery: no provider writes. Checks are recorded, not run by setup. Use --config for other reviewed choices or multiple checks.")
    return agent, config


def preview(document, operations, json_output):
    if json_output:
        print(json.dumps(with_digest(document), indent=2))
        return
    print("Plan: " + document["target"] + " (" + document["agent"] + ")")
    for op, row in zip(operations, document["operations"]):
        print("  " + op["action"] + " " + op["path"] + "  " + row["after"][:12])
        if op["action"] == "update" and op["path"] in ("AGENTS.md", "CLAUDE.md"):
            print("".join(difflib.unified_diff(op["before"].decode().splitlines(True), op["after"].decode().splitlines(True), fromfile=op["path"], tofile=op["path"])), end="")
    print("Plan SHA-256: " + sha(encoded(document)))


def doctor(module, root):
    if tx.pending(root):
        raise ValueError("Interrupted installation; run flightcheck recover before verification")
    state = module.read_state(root)
    if not state:
        raise ValueError("No complete FlightCheck installation found")
    # Verify executable bytes against the recorded installation before importing.
    script = module.safe_path(root, ".flightcheck/install.py")
    expected = state["files"][".flightcheck/install.py"]["sha256"]
    if sha(script.read_bytes()) != expected:
        raise ValueError("Modified installed verifier; refusing execution")
    installed = load_installer(script)
    result = installed.verify(root, installed.load_manifest())
    pin_path = module.safe_path(root, PIN)
    if pin_path.exists():
        pin = json.loads(pin_path.read_text())
        config = json.loads(module.safe_path(root, module.CONFIG).read_text())
        if runtime_identity(config) != pin["runtime"]:
            raise ValueError("Pinned project Python changed; no replacement was selected")
        if pin["source_revision"] != result["source"]["revision"]:
            raise ValueError("Distribution pin and installed source disagree")
        result["distribution"] = pin
    return result


def execute(root, plan_path, json_output):
    reviewed = read_plan(plan_path)
    with installer() as (module, source, manifest, identity):
        root = target(module, root)
        if reviewed["target"] != str(root):
            raise ValueError("Reviewed plan targets another project")
        # Recompute under the same lock as the write transaction. No config path
        # is reread: the exact reviewed normalized values belong to the plan.
        with tx.locked(root) as state:
            actual, operations = make_plan(module, source, manifest, identity, root, reviewed["agent"], reviewed["configuration"])
            if actual != reviewed:
                raise ValueError("Reviewed plan is stale (source/package, project, configuration, mode or runtime changed); preview again")
            # Keep the same cooperating lock from plan comparison through verify.
            result = tx.apply(module, root, operations, lambda: doctor_during_apply(module, root), state=state)
    result["project"] = str(root)
    result["next"] = "Start a fresh " + reviewed["agent"] + " session in the project, verify discovery and select develop-change. Native client/reviewer/browser qualification remains pending."
    output(result, json_output)
    return 0


def doctor_during_apply(module, root):
    # The active journal is expected here; never recursively enter doctor/pending.
    result = module.verify(root, module.load_manifest())
    pin = json.loads(module.safe_path(root, PIN).read_text())
    config = json.loads(module.safe_path(root, module.CONFIG).read_text())
    if runtime_identity(config) != pin["runtime"]:
        raise ValueError("Project runtime changed during installation")
    result["distribution"] = pin
    return result


def output(value, json_output):
    if json_output:
        print(json.dumps(value, indent=2))
    else:
        print(value.get("status", "complete"))
        if "required_components" in value:
            print("Verified components: " + str(value["required_components"]))
        if value.get("next"):
            print(value["next"])
        if value.get("client_qualification"):
            print(value["client_qualification"])


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="Run from your normal terminal to configure FlightCheck. No project changes occur when installing the application.")
    parser.add_argument("--version", action="version", version="flightcheck " + metadata.version("flightcheck"))
    parser.add_argument("command", choices=("inspect", "init", "doctor", "recover"))
    parser.add_argument("target", nargs="?", default=".")
    parser.add_argument("--agent", choices=("codex", "claude", "both"))
    parser.add_argument("--config", help="Reviewed project configuration JSON")
    parser.add_argument("--plan", help="Write a preview plan outside the project")
    parser.add_argument("--apply", metavar="PLAN", help="Apply exactly this reviewed plan; never an implicit upgrade")
    parser.add_argument("--json", action="store_true", help="Structured output")
    args = parser.parse_args(argv)
    try:
        if os.name != "posix" or sys.version_info < (3, 9):
            raise ValueError("Use Python 3.9+ on POSIX; native Windows is not supported")
        if args.command != "init" and any((args.agent, args.config, args.plan, args.apply)):
            raise ValueError("Setup options apply only to init")
        if args.apply:
            if any((args.agent, args.config, args.plan)):
                raise ValueError("--apply uses only the saved reviewed plan; do not override it")
            return execute(args.target, args.apply, args.json)
        with installer() as (module, source, manifest, identity):
            root = target(module, args.target)
            if args.command == "inspect":
                result = module.inspect_project(root)
                if args.json:
                    output(result, True)
                else:
                    print(json.dumps(result, indent=2))
                return 0
            if args.command == "doctor":
                output(doctor(module, root), args.json)
                return 0
            if args.command == "recover":
                with tx.locked(root) as state:
                    record = tx.journal(state)
                    if record and record["status"] in ("prepared", "rollback_required"):
                        tx.restore(module, root, state, record)
                    result = {"status": record["status"] if record else "nothing_to_recover", "journal": str(state / "transaction.json")}
                output(result, args.json)
                return 0
            agent, supplied = choices(module, root, args.agent, args.config)
            document, operations = make_plan(module, source, manifest, identity, root, agent, supplied)
            if args.plan:
                path = tx.no_links(Path(args.plan).expanduser().absolute())
                if root == path or root in path.parents:
                    raise ValueError("Keep the review plan outside the target project")
                tx.private_dir(path.parent)
            else:
                path = tx.directory(root) / ("plan-" + sha(encoded(document)) + ".json")
            tx.atomic(path, encoded(with_digest(document)))
            preview(document, operations, args.json)
            if not args.json:
                print("Saved plan: " + str(path))
                print("Apply: flightcheck init " + shlex.quote(str(root)) + " --apply " + shlex.quote(str(path)))
            if sys.stdin.isatty() and not args.json and input("Apply this complete installation? [y/N]: ").strip().lower() in ("y", "yes"):
                return execute(root, path, False)
            return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        message = str(error)
        if isinstance(error, PermissionError) or isinstance(error.__cause__, PermissionError):
            message += ". Run the installer in a normal terminal outside the AI command sandbox; do not omit protected adapters or change global sandbox settings."
        if args.json:
            print(json.dumps({"status": "incomplete", "error": message}))
        else:
            print("incomplete: " + message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
