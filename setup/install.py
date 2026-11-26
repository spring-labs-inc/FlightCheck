"""Install and verify a complete project-local FlightCheck configuration.

Run by path with Python 3.9+ on POSIX. No network calls, package installation,
global settings, provider writes, or native project checks are performed.
"""

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import select
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
from http.client import HTTPConnection
from urllib.parse import urlsplit

UPSTREAM = "https://github.com/spring-labs-inc/FlightCheck"
MANIFEST = Path(__file__).with_name("manifest.json")
BEGIN = "<!-- FlightCheck:begin -->"
END = "<!-- FlightCheck:end -->"
STATE = ".flightcheck/installation.json"
CONFIG = ".flightcheck/project.json"
SCRIPTS = ("capture_check", "handoff", "proof", "recovery", "behavior", "disposition", "checkout_guard", "flight_lifecycle", "repository_audit")


class SetupError(ValueError):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def run(command, cwd):
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise SetupError("Command failed: " + " ".join(map(str, command)) + ": " + result.stderr.strip())
    return result.stdout.strip()


def git(root, *args):
    return run(["git", "--no-optional-locks", "-C", str(root), *args], root)


def repository(path):
    root = Path(path).expanduser().resolve(strict=True)
    if not root.is_dir() or Path(git(root, "rev-parse", "--show-toplevel")).resolve() != root:
        raise SetupError("Target must be the root of an existing Git checkout")
    return root


def safe_path(root, name):
    relative = PurePosixPath(name)
    if relative.is_absolute() or not relative.parts or any(p in ("..", ".", ".git") for p in relative.parts):
        raise SetupError("Unsafe managed path: " + name)
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise SetupError("Managed paths cannot traverse symlinks: " + name)
    if current.exists() and not current.is_file():
        raise SetupError("Managed file is not a regular file: " + name)
    return current


def load_manifest():
    value = json.loads(MANIFEST.read_text())
    if value.get("schema") != 1 or not isinstance(value.get("files"), list):
        raise SetupError("Unsupported installation manifest")
    seen = set()
    for entry in value["files"]:
        if not isinstance(entry, list) or len(entry) != 3 or entry[2] not in ("shared", "codex", "claude"):
            raise SetupError("Invalid manifest entry")
        if entry[1] in seen:
            raise SetupError("Duplicate manifest destination")
        seen.add(entry[1])
    return value


def selected(manifest, agent):
    if agent not in ("codex", "claude", "both"):
        raise SetupError("Choose codex, claude, or both explicitly")
    return [row for row in manifest["files"] if row[2] == "shared" or agent == "both" or row[2] == agent]


def source_identity(source, manifest):
    if repository(source) != source or git(source, "status", "--porcelain=v1", "--untracked-files=all"):
        raise SetupError("Use a clean, pinned FlightCheck source checkout; commit or remove source edits first")
    tracked = set(git(source, "ls-files").splitlines())
    for name in {row[0] for row in manifest["files"]}:
        if name not in tracked:
            raise SetupError("Required source is not tracked: " + name)
        safe_path(source, name).read_bytes()
    revision = git(source, "rev-parse", "HEAD")
    return {"upstream": UPSTREAM, "revision": revision,
            "tree": git(source, "rev-parse", "HEAD^{tree}"),
            "manifest_sha256": sha(MANIFEST.read_bytes())}


def inspect_project(root):
    try:
        branch = git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").removeprefix("origin/")
    except SetupError:
        branch = None
    interpreter = root / ".venv/bin/python"
    if not interpreter.is_file():
        interpreter = Path(sys.executable)
    candidates = ("AGENTS.md", "CLAUDE.md", ".claude/settings.json", ".codex/config.toml",
                  "pyproject.toml", "pytest.ini", ".pre-commit-config.yaml", "package.json", "Makefile")
    return {"target": str(root), "python": str(interpreter), "default_branch": branch,
            "existing_configuration": [name for name in candidates if (root / name).exists()],
            "defaults": {"activation": "opt-in", "delivery": "No provider writes without owner approval"},
            "required_configuration": ["evidence_dir", "nit_tracker", "checks", "policy_reference"],
            "note": "Read existing project policy; detected files are hints, not permission to replace policy or run checks."}


def project_model():
    """Load the same model from source or a verified project-local install."""
    base = Path(__file__).resolve().parent
    installed = base / "scripts/project_config.py"
    path = installed if installed.is_file() else base.parent / "workflow/scripts/project_config.py"
    if installed.is_file():
        state = json.loads((base / "installation.json").read_text())
        expected = state["files"][".flightcheck/scripts/project_config.py"]["sha256"]
        if sha(path.read_bytes()) != expected:
            raise SetupError("Modified installed configuration model; refusing execution")
    namespace = {"__file__": str(path), "__name__": "flightcheck_project_config"}
    exec(compile(path.read_bytes(), str(path), "exec"), namespace)
    from types import SimpleNamespace
    return SimpleNamespace(**namespace)


def configuration(root, supplied):
    try:
        saved = safe_path(root, CONFIG)
        trusted = saved.exists() and json.loads(saved.read_bytes()) == supplied
        return project_model().normalize(root, supplied, inspect_project(root), origin="setup", trusted_metadata=trusted)
    except ValueError as error:
        raise SetupError(str(error)) from error


def render(data, source_name, destination, config):
    if not destination.endswith((".md", ".toml")):
        return data
    text = data.decode()
    text = re.sub(r"(?<![\w./-])status-card/reply\.py", ".flightcheck/status-card/reply.py", text)
    for name in SCRIPTS:
        text = re.sub(r"(?<!\.flightcheck/)scripts/" + re.escape(name) + r"\.py",
                      ".flightcheck/scripts/" + name + ".py", text)
    text = text.replace("workflow/docs/development-workflow.md", ".flightcheck/docs/development-workflow.md")
    if destination.endswith("docs/development-workflow.md"):
        text = text.replace("](../../docs/checkout-verification.md)", "](checkout-verification.md)")
        text = text.replace("](../../docs/flight-lifecycle.md)", "](flight-lifecycle.md)")
        text = text.replace("](../../docs/status-synchronization.md)", "](status-synchronization.md)")
        text = text.replace("](../../examples/existing-project/docs/first-flight.md)", "](first-flight.md)")
        text = text.replace("](../../examples/existing-project/examples/evidence-bootstrap/README.md)", "](../examples/evidence-bootstrap/README.md)")
        text = text.replace("](../.flightcheck/scripts/", "](../scripts/")
        text = text.replace("separate read-only Codex session", "separate read-only session in the selected client")
        text += "\n## Installed project configuration\n\nUse `.flightcheck/project.json` for the recorded project choices. Configure each flight's task contract and evidence gates using this guide; installation does not manufacture receipts or reviewer approval.\n"
    if destination.endswith("examples/evidence-bootstrap/README.md"):
        text = text.replace("](../../../../.flightcheck/docs/development-workflow.md", "](../../docs/development-workflow.md")
    if destination.endswith("docs/first-flight.md"):
        text = text.replace("](../../../.flightcheck/docs/development-workflow.md", "](development-workflow.md")
    if destination.endswith("SKILL.md"):
        text = text.replace("](../../../docs/checkout-verification.md)", "](../../../.flightcheck/docs/checkout-verification.md)")
        text = text.replace("](../../../docs/flight-lifecycle.md)", "](../../../.flightcheck/docs/flight-lifecycle.md)")
        text = text.replace("](../../../docs/status-synchronization.md)", "](../../../.flightcheck/docs/status-synchronization.md)")
        if "/.claude/" in "/" + destination and config["activation"] == "opt-in":
            text = text.replace("description: Run", "disable-model-invocation: true\ndescription: Run", 1)
        text += "\n## Installed status card\n\nThe standard card is installed. Read `.flightcheck/docs/status.md`; start or restore it for each selected flight. A terminal session can use the live browser card through its task URL. Record unavailable capabilities instead of silently omitting the card.\n"
    if destination.startswith(".claude/agents/"):
        name = re.search(r'^name = (".*")$', text, re.M)
        description = re.search(r'^description = (".*")$', text, re.M)
        instructions = re.search(r'developer_instructions = (""".*""")\s*$', text, re.S)
        if not all((name, description, instructions)):
            raise SetupError("Unsupported canonical reviewer definition: " + source_name)
        text = ("---\nname: " + name.group(1) + "\ndescription: " + description.group(1)
                + "\ntools: Read, Grep, Glob\n---\n\n" + ast.literal_eval(instructions.group(1)).strip()
                + "\n\nReturn the native JSON object as your entire final message. The controller retains the original response; do not write it yourself.\n")
    if destination.endswith("docs/setup.md"):
        text = text.replace("](manifest.json)", "](../manifest.json)")
        text = text.replace("](../workflow/docs/project-resources.md)", "](project-resources.md)")
    return text.encode()


def instruction_block(agent, config):
    activation = ("Use FlightCheck for coding tasks unless the owner explicitly opts out."
                  if config["activation"] == "default-for-coding" else
                  "Use FlightCheck when the owner explicitly selects or resumes a bounded flight.")
    entry = "$develop-change" if agent == "codex" else "/develop-change"
    return (BEGIN + "\n## FlightCheck\n\n" + activation
            + " Ordinary questions and reviews use their normal entry points.\n"
            + "Start with `.flightcheck/project.json` and `.flightcheck/docs/development-workflow.md`; the entry point is `" + entry + "`.\n"
            + "Preserve this project's existing policy and execution boundaries. Never infer provider-write authority from a passing verdict.\n"
            + "The standard status card is installed: follow `.flightcheck/docs/status.md` before every controller reply. Put its exact task link last, with any actual verdict above it. Proactively tell TUI users to open it in their regular browser. Ordinary chat and raw reviewer JSON are excluded. Keep private evidence outside the checkout.\n"
            + "FlightCheck-derived material is covered by `.flightcheck/LICENSE`; its pinned source and file hashes are recorded in `.flightcheck/installation.json`.\n"
            + END + "\n").encode()


def block_from(data):
    text = data.decode()
    text = text.replace("status-card/reply.py", ".flightcheck/status-card/reply.py")
    if text.count(BEGIN) != 1 or text.count(END) != 1 or text.index(BEGIN) > text.index(END):
        raise SetupError("Missing or ambiguous managed FlightCheck instruction block")
    start, end = text.index(BEGIN), text.index(END) + len(END)
    if text[end:end + 1] == "\n":
        end += 1
    return text[start:end].encode()


def desired_files(source, manifest, agent, config, root=None):
    result = {}
    sources = {}
    for name, destination, _ in selected(manifest, agent):
        data = safe_path(source, name).read_bytes()
        result[destination] = ("file", render(data, name, destination, config))
        sources[destination] = {"source": name, "source_sha256": sha(data)}
    status = ("# FlightCheck status\n\nStart or resume a selected flight from the project root:\n\n```sh\n"
              + "FLIGHTCHECK_STATE_DIR=" + shlex.quote(str(Path(config["evidence_dir"]) / "status-card")) + " "
              + shlex.quote(config["python"]) + " -B .flightcheck/status-card/reply.py prepare --task TASK_ID --title \"Task title\" --details /private/flight-details.json\n```\n\n"
              + "The command returns JSON with footer and guidance, publishes outside the checkout and verifies the task page and current candidate. Keep the prepared task URL stable on resume. Auto execution detection uses SSH/container hints; override --execution when needed. Remote mode withholds the clickable footer and returns nonzero until a browser-facing route is supplied. Run the installed .flightcheck/status-card/connect.py on the browser machine with --ssh WORKER_ALIAS --checkout /absolute/remote/project --task TASK_ID --remote-python /configured/remote/python --remote-state-dir /same/remote/private/state. It restores the worker service and verifies the forwarded task/candidate before offering a link. For client-managed forwarding, record its observed route with --user-url. Never bind beyond loopback. TUI users can open this live card in a regular web browser while continuing in the terminal. For remote sessions, arrange approved localhost forwarding; do not claim the browser rendered just because the checkout host returned HTTP 200.\n\n"
              + "Initialize --details with all nine stages (one current), check_plan and current pending check rows. Include known issue/PR links, or links_unavailable reasons when they do not exist. An empty check_plan requires checks_unavailable. Missing sections make prepare/check fail with actionable completeness diagnostics; HTTP availability alone does not mean a ready flight. See the installed controller status instructions for the full JSON example. Record only real receipts and actual verdicts for the current candidate. Before every controller reply (start, update, approval, blocker, repair, resume and end), run prepare and then reply.py check with --task, --phase and --reply-file pointing to the exact private draft. Put the returned footer last, with any actual current verdict above it. Proactively tell TUI users to open the card in their regular browser. Native reviewer replies stay raw JSON; never run controller lifecycle commands or hooks in reviewer contexts.\n\n"
              + "Run Python scripts by path with -B, not -I. Verify new client definitions in a fresh session; inspect effective tools, required evidence access and active hooks. File installation does not prove a reviewer boundary.\n")
    result[".flightcheck/docs/status.md"] = ("file", status.encode())
    result[CONFIG] = ("file", encoded(config))
    existing_ignore = safe_path(root, ".flightcheck/.gitignore").read_bytes() if root is not None and safe_path(root, ".flightcheck/.gitignore").exists() else b""
    ignore = existing_ignore + (b"\n" if existing_ignore and not existing_ignore.endswith(b"\n") else b"")
    privacy_rules = b"/project.json\n/docs/status.md\n"
    if not ignore.endswith(privacy_rules):
        ignore += privacy_rules
    result[".flightcheck/.gitignore"] = ("file", ignore)
    if agent in ("codex", "both"):
        result["AGENTS.md"] = ("block", instruction_block("codex", config))
    if agent in ("claude", "both"):
        result["CLAUDE.md"] = ("block", instruction_block("claude", config))
    return result, sources


def read_state(root):
    path = safe_path(root, STATE)
    if not path.exists():
        return None
    state = json.loads(path.read_text())
    if state.get("schema") != 1 or not isinstance(state.get("files"), dict):
        raise SetupError("Unsupported installed state; preserve it and reconcile manually")
    return state


def prepare(root, desired, previous):
    operations, conflicts = [], []
    for name, (kind, wanted) in desired.items():
        path = safe_path(root, name)
        before = path.read_bytes() if path.exists() else None
        old = (previous or {}).get("files", {}).get(name)
        after = wanted
        if kind == "block" and before is not None:
            if BEGIN.encode() in before or END.encode() in before:
                actual = block_from(before)
                if actual != wanted and (not old or sha(actual) != old["sha256"]):
                    conflicts.append(name)
                after = before.replace(actual, wanted, 1)
            else:
                if old:
                    conflicts.append(name)
                separator = b"" if not before or before.endswith(b"\n\n") else b"\n" if before.endswith(b"\n") else b"\n\n"
                after = before + separator + wanted
        elif before is not None and before != wanted and not (name == ".flightcheck/.gitignore" and wanted.startswith(before)) and (not old or sha(before) != old["sha256"]):
            conflicts.append(name)
        operations.append({"path": name, "before": before, "after": after,
                           **({"after_mode": 0o600} if name in (CONFIG, ".flightcheck/docs/status.md") else {}),
                           "action": "unchanged" if before == after else "create" if before is None else "update"})
    if conflicts:
        raise SetupError("Preserve and reconcile modified/unmanaged files before applying: " + ", ".join(conflicts))
    return operations


def write_file(root, name, before, after, temporary=None, mode=None):
    path = safe_path(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_path(root, name)
    actual = path.read_bytes() if path.exists() else None
    if actual != before:
        raise SetupError("Concurrent edit detected; preserved file: " + name)
    requested_mode = mode
    mode = stat.S_IMODE(path.stat().st_mode) if before is not None else 0o644
    if requested_mode is not None:
        if type(requested_mode) is not int or requested_mode < 0 or requested_mode & ~0o777:
            raise SetupError("Invalid file publication mode")
        mode = requested_mode
    elif name in (CONFIG, ".flightcheck/docs/status.md"):
        mode = 0o600
    if temporary is None:
        fd, pending = tempfile.mkstemp(prefix=".flightcheck-", dir=path.parent)
    else:
        pending = safe_path(root, temporary)
        if pending.parent != path.parent:
            raise SetupError("Temporary file must share the destination directory")
        fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(after)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(pending, mode)
        if before is None:
            os.link(pending, path)
        else:
            os.replace(pending, path)
    finally:
        Path(pending).unlink(missing_ok=True)


def apply_plan(root, operations, rollback_on_error=True, temporary_paths=None):
    written = []
    try:
        for op in operations:
            if op["action"] != "unchanged":
                if temporary_paths is None:
                    write_file(root, op["path"], op["before"], op["after"])
                else:
                    write_file(root, op["path"], op["before"], op["after"], temporary=temporary_paths[op["path"]])
                written.append(op)
    except BaseException:
        if not rollback_on_error:
            raise
        for op in reversed(written):
            path = safe_path(root, op["path"])
            if path.read_bytes() == op["after"]:
                if op["before"] is None:
                    path.unlink()
                else:
                    write_file(root, op["path"], op["after"], op["before"])
        raise


def plan_installation(source, root, manifest, agent, supplied):
    """Shared nonwriting plan API for the source and packaged terminal channels."""
    identity = source_identity(source, manifest)
    config = configuration(root, supplied)
    desired, sources = desired_files(source, manifest, agent, config, root)
    state = {"schema": 1, "agent": agent, "source": identity,
             "files": {name: {"kind": kind, "sha256": sha(data), **sources.get(name, {})}
                       for name, (kind, data) in desired.items()}}
    previous = read_state(root)
    if previous and previous["agent"] != agent:
        raise SetupError("Agent selection changed; reconcile the prior installation explicitly")
    operations = prepare(root, desired, previous)
    old_state = safe_path(root, STATE).read_bytes() if previous else None
    operations.append({"path": STATE, "before": old_state, "after": encoded(state),
                       "action": "unchanged" if old_state == encoded(state) else "create" if old_state is None else "update"})
    result = {"status": "planned", "source": identity, "agent": agent,
              "operations": [{k: op[k] for k in ("path", "action")} for op in operations]}
    return result, config, operations


def interrupt_probe(signum, frame):
    raise SetupError("Runtime verification interrupted at its overall deadline")


def runtime_probe(root, config, revision):
    evidence = Path(config["evidence_dir"])
    evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
    if evidence.is_symlink() or evidence.stat().st_uid != os.geteuid() or stat.S_IMODE(evidence.stat().st_mode) & 0o077:
        raise SetupError("Evidence directory is not owner-only")
    # Socket/read timeouts reset as bytes arrive. Isolate the whole smoke check
    # so even partial startup lines or trickled HTTP cannot extend this deadline.
    with tempfile.TemporaryDirectory(prefix="setup-check-", dir=evidence) as scratch:
        process = subprocess.Popen([config["python"], "-B", str(Path(__file__).resolve()), "--runtime-worker"],
                                   cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            payload = json.dumps({"root": str(root), "config": config, "revision": revision, "scratch": scratch})
            try:
                stdout, stderr = process.communicate(payload, timeout=15)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.communicate(timeout=6)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate(timeout=1)
                raise SetupError("Runtime/card verification exceeded its 15-second overall deadline; check the interpreter, card startup and loopback HTTP access")
            if process.returncode:
                raise SetupError("Runtime/card verification failed: " + (stdout + stderr).strip()[:2000])
            return json.loads(stdout)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate(timeout=1)
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


def runtime_checks(root, config, revision, scratch):
    python = config["python"]
    for entry in ("scripts/handoff.py", "scripts/capture_check.py", "status-card/maintainer.py", "status-card/reply.py", "status-card/connect.py"):
        run([python, "-B", str(root / ".flightcheck" / entry), "--help"], root)
    folder = Path(scratch)
    details = folder / "details.json"
    details.write_bytes(encoded({"stages": {"Plan": "current"}}))
    publisher = root / ".flightcheck/status-card/task_status.py"
    base = [python, "-B", str(publisher), "--file", str(folder / "status.json"),
            "--task", "setup-check", "--title", "FlightCheck setup check",
            "--candidate", revision, "--mode", "minimal", "--details", str(details)]
    run(base, root)
    process = subprocess.Popen([python, "-B", str(root / ".flightcheck/status-card/serve.py"),
                                "--port", "0", "--task-status", str(folder / "status.json")],
                               cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    try:
        if not select.select([process.stdout], [], [], 5)[0]:
            raise SetupError("Card startup timed out")
        startup = process.stdout.readline().strip()
        prefix = "FlightCheck status card at "
        if not startup.startswith(prefix):
            process.terminate()
            _, diagnostic = process.communicate(timeout=5)
            raise SetupError("Card listener did not report a task route; check loopback permission and runtime: " + diagnostic.strip()[:1000])
        url = startup[len(prefix):]
        route = urlsplit(url)
        if route.scheme != "http" or route.hostname != "127.0.0.1" or route.path != "/task/setup-check/":
            raise SetupError("Unexpected verification card route")
        connection = HTTPConnection("127.0.0.1", route.port, timeout=5)
        try:
            connection.request("GET", route.path + "status.json")
            response = connection.getresponse()
            snapshot = json.loads(response.read())
            if snapshot.get("mode") != "minimal" or snapshot.get("completeness", {}).get("ready") is not False:
                raise SetupError("Runtime probe must remain a labeled minimal snapshot, not a ready flight")
            if response.status != 200 or snapshot.get("candidate") != revision or snapshot.get("task") != "setup-check" or len(snapshot.get("stages", {})) != 9:
                raise SetupError("Card snapshot did not match verification task/candidate/stages")
        finally:
            connection.close()
        footer = run(base + ["--url", url, "--chat-phase", "start"], root)
        if url not in footer:
            raise SetupError("Card publisher omitted the task link")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        process.stdout.close()
        process.stderr.close()
    return {"python_tools": "passed", "card_http": "passed", "interpreter": config["observed_python"],
            "browser_rendering": "pending owner/client observation"}


def verify(root, manifest):
    state = read_state(root)
    if state is None:
        raise SetupError("No installation manifest; run plan and apply first")
    config = configuration(root, json.loads(safe_path(root, CONFIG).read_text()))
    agent = state["agent"]
    required = {row[1] for row in selected(manifest, agent)} | {CONFIG, ".flightcheck/docs/status.md", ".flightcheck/.gitignore"}
    required |= ({"AGENTS.md"} if agent in ("codex", "both") else set())
    required |= ({"CLAUDE.md"} if agent in ("claude", "both") else set())
    if set(state["files"]) != required:
        raise SetupError("Installed manifest omits or adds unexpected required components")
    if state["source"]["manifest_sha256"] != sha(MANIFEST.read_bytes()):
        raise SetupError("Installer manifest differs from the installed source revision")
    for name, record in state["files"].items():
        data = safe_path(root, name).read_bytes()
        actual = block_from(data) if record["kind"] == "block" else data
        if sha(actual) != record["sha256"]:
            raise SetupError("Missing or modified required component: " + name)
    return {"status": "ready_for_client_probe", "source": state["source"], "agent": agent,
            "required_components": len(required), "runtime": runtime_probe(root, config, state["source"]["revision"]),
            "client_qualification": "pending fresh-session instruction, skill, reviewer-boundary and browser probes"}


def checkout_main(argv):
    """Run the shared checkout operations without installing into the target."""
    try:
        base = Path(__file__).resolve().parent
        installed = base / "scripts/checkout_guard.py"
        helper = installed if installed.is_file() else base.parent / "workflow/scripts/checkout_guard.py"
        if installed.is_file():
            state = json.loads((base / "installation.json").read_text())
            for name, record in state["files"].items():
                if name.startswith(".flightcheck/scripts/") and name.endswith(".py"):
                    path = safe_path(base.parent, name)
                    if sha(path.read_bytes()) != record["sha256"]:
                        raise SetupError("Modified installed checkout dependency: " + name)
            if ".flightcheck/scripts/checkout_guard.py" not in state["files"]:
                raise SetupError("Checkout helper is not part of the pinned installation")
        return subprocess.run([sys.executable, "-B", str(helper), *argv], check=False).returncode
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"status": "incomplete", "error": str(error)}))
        return 1


def _lifecycle_operation_main(helper_name, argv):
    """Run a pinned shared operation; never install or upgrade a project."""
    try:
        base = Path(__file__).resolve().parent
        installation = base / "installation.json"
        if installation.is_file():
            state = json.loads(installation.read_text())
            selected = ".flightcheck/scripts/" + helper_name + ".py"
            if selected not in state["files"]:
                raise SetupError("Operation is unavailable in this pinned installation")
            for name, record in state["files"].items():
                if name.startswith(".flightcheck/scripts/") and name.endswith(".py"):
                    path = safe_path(base.parent, name)
                    if sha(path.read_bytes()) != record["sha256"]:
                        raise SetupError("Modified installed operation dependency: " + name)
            helper = safe_path(base.parent, selected)
        else:
            helper = base.parent / "workflow/scripts" / (helper_name + ".py")
            if not helper.is_file():
                raise SetupError("Operation helper is unavailable in the selected source")
        return subprocess.run([sys.executable, "-B", str(helper), *argv], check=False).returncode
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"status": "incomplete", "error": str(error)}))
        return 1


def lifecycle_main(argv):
    return _lifecycle_operation_main("flight_lifecycle", argv)


def audit_main(argv):
    return _lifecycle_operation_main("repository_audit", argv)


def status_sync_main(argv):
    return _lifecycle_operation_main("status_sync", argv)


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("lifecycle", "audit", "status-sync"):
        return {"lifecycle": lifecycle_main, "audit": audit_main, "status-sync": status_sync_main}[sys.argv[1]](sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "checkout":
        return checkout_main(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "config":
        source = Path(__file__).resolve().parents[1] / "src"
        if not (source / "flightcheck_cli/cli.py").is_file():
            print(json.dumps({"status": "incomplete", "error": "Use the source checkout setup/install.py config command or an updated CLI; installed workflow remains pinned"}))
            return 1
        sys.path.insert(0, str(source))
        from flightcheck_cli.cli import configuration_main
        return configuration_main(sys.argv[2:], engine=sys.modules[__name__])
    if sys.argv[1:] == ["--runtime-worker"]:
        signal.signal(signal.SIGTERM, interrupt_probe)
        try:
            payload = json.load(sys.stdin)
            result = runtime_checks(Path(payload["root"]), payload["config"], payload["revision"], payload["scratch"])
            print(json.dumps(result))
            return 0
        except (SetupError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            print(str(error), file=sys.stderr)
            return 1
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inspect", "plan", "apply", "verify"))
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--agent", choices=("codex", "claude", "both"))
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    try:
        if os.name != "posix" or sys.version_info < (3, 9):
            raise SetupError("Use Python 3.9+ on a POSIX host")
        root = repository(args.target)
        if args.command == "inspect":
            result = inspect_project(root)
        else:
            manifest = load_manifest()
            if args.command == "verify":
                result = verify(root, manifest)
            else:
                source = MANIFEST.parent.parent.resolve()
                if source == root:
                    raise SetupError("Install into an adopter checkout, not the FlightCheck source checkout")
                if not args.config:
                    raise SetupError("Supply the reviewed project configuration with --config; inspect lists unresolved fields")
                result, config, operations = plan_installation(
                    source, root, manifest, args.agent, json.loads(args.config.read_text()))
                if args.command == "apply":
                    apply_plan(root, operations)
                    result = verify(root, manifest)
        print(json.dumps(result, indent=2))
        return 0
    except (SetupError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "incomplete", "error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
