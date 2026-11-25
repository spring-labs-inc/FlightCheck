"""Bounded flight disposition through existing ownership and explicit grants.

Native clients remove their own worktrees. This module records a request and
observes its result; it is neither a worktree manager nor a retention scheduler.
Read-only planning/integration helpers never fetch or prune repository state.
"""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import time

import launch_detection
from flight_associations import AssociationError, Registry, encoded, repository_identity

PROTOCOL = "required-v1"
KINDS = {"worktree": "worktree", "temporary worktree": "worktree",
         "local_branch": "local_branch", "local branch": "local_branch",
         "remote_branch": "remote_branch", "actual remote branch": "remote_branch"}
MAX_FILES = 10000


class LifecycleError(ValueError):
    pass


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        raise LifecycleError(name + " must be explicit nonempty text")
    return value


def _hash(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def _oid(value, name="commit"):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value):
        raise LifecycleError(name + " must be an exact object id")
    return value


def _registry(value):
    return value if isinstance(value, Registry) else Registry(Path(value).expanduser().resolve())


def _git(root, *args, required=True, timeout=10):
    try:
        result = subprocess.run(["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(root), *args],
                                stdin=subprocess.DEVNULL, capture_output=True,
                                env=dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0", GIT_NO_LAZY_FETCH="1", GIT_NO_REPLACE_OBJECTS="1"), timeout=timeout)
    except (OSError, subprocess.SubprocessError) as error:
        raise LifecycleError("Git observation/action unavailable: " + str(error)) from error
    if required and result.returncode:
        raise LifecycleError("Git " + args[0] + " failed: " + os.fsdecode(result.stderr).strip())
    return result


def _out(root, *args):
    return os.fsdecode(_git(root, *args).stdout).strip()


def _resolve(root, reference):
    result = _git(root, "rev-parse", "--verify", "--end-of-options", reference + "^{commit}", required=False)
    return os.fsdecode(result.stdout).strip() if result.returncode == 0 else None


def _local_ref(root, reference):
    probe = _git(root, "show-ref", "--verify", "--quiet", reference, required=False)
    if probe.returncode == 1:
        return None
    if probe.returncode:
        raise LifecycleError("Local ref state is unavailable; absence is not established")
    symbolic = _git(root, "symbolic-ref", "--quiet", reference, required=False)
    if symbolic.returncode == 0:
        raise LifecycleError("Symbolic branch ownership is ambiguous; preserve it")
    return _oid(_out(root, "show-ref", "--verify", "--hash", reference))


def _ancestor(root, previous, current):
    return _git(root, "merge-base", "--is-ancestor", previous, current, required=False).returncode == 0


def _root(checkout, record):
    root = Path(checkout).resolve(strict=True)
    if _out(root, "rev-parse", "--show-toplevel") != str(root):
        raise LifecycleError("Control checkout must be the actual repository root")
    if repository_identity(root, record["repository"]["id"]) != record["repository"]:
        raise LifecycleError("Control checkout belongs to another repository/common Git directory")
    return root


def _read(registry, flight):
    registry = _registry(registry)
    state = registry.read()
    record = next((row for row in state["records"] if row["flight"] == flight), None)
    if record is None:
        raise LifecycleError("Flight ownership record is unavailable")
    return registry, state, copy.deepcopy(record)


def initialize(record):
    """Mark genuinely new adoption; no cleanup authority is created."""
    value = copy.deepcopy(record)
    value.setdefault("cleanup", {"protocol": PROTOCOL, "state": "pending_authorization", "inventory": [], "operations": []})
    if not isinstance(value["cleanup"], dict) or value["cleanup"].get("protocol") != PROTOCOL:
        raise LifecycleError("New adoption cannot downgrade required cleanup")
    return value


def launch(checkout, registry, repository_id, *, issues=(), pull_requests=(), current_flight=None):
    return launch_detection.detect(checkout, registry, repository_id, issues=issues,
                                   pull_requests=pull_requests, current_flight=current_flight)


def _ref(value):
    _text(value, "branch ref")
    if not value.startswith("refs/heads/"):
        raise LifecycleError("Cleanup branch must name an actual refs/heads/ ref, not a tracking ref")
    result = subprocess.run(["git", "check-ref-format", value], capture_output=True)
    if result.returncode:
        raise LifecycleError("Invalid branch ref")
    return value


def _relative(value):
    _text(value, "relative file")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) != value or value == ".":
        raise LifecycleError("Preservation paths must be normalized relative files")
    return value


def _prefixes(values):
    if not isinstance(values, list):
        raise LifecycleError("owned_ignored_prefixes must be an explicit list")
    result = []
    for value in values:
        _relative(value.rstrip("/"))
        if any(char in value for char in "*?[\\"):
            raise LifecycleError("Ignored ownership prefixes cannot be globs")
        result.append(value)
    return sorted(set(result))


def _artifact(value):
    if not isinstance(value, dict) or value.get("kind") not in KINDS:
        raise LifecycleError("Cleanup inventory requires explicit artifact kinds")
    kind = KINDS[value["kind"]]
    identity = value.get("identity") or value.get("path" if kind == "worktree" else "ref")
    if kind == "worktree":
        _text(identity, "worktree path")
        if not Path(identity).is_absolute():
            raise LifecycleError("Worktree identity must be absolute")
        identity = str(Path(identity).resolve())
    else:
        identity = _ref(identity)
    remote = _text(value.get("remote"), "remote") if kind == "remote_branch" else None
    key = {"kind": kind, "identity": identity, "remote": remote}
    identifier = value.get("id") or "artifact-" + _hash(key)[:16]
    if not isinstance(identifier, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", identifier):
        raise LifecycleError("Artifact id is invalid")
    return dict(key, id=identifier, owned_ignored_prefixes=_prefixes(value.get("owned_ignored_prefixes", [])))


def _key(value):
    return value["kind"], value["identity"], value.get("remote")


def _grant(record, reference):
    matches = [grant for grant in record["grants"].get("cleanup", [])
               if isinstance(grant, dict) and grant.get("authority") == "owner" and grant.get("reference") == reference]
    if len(matches) != 1 or not isinstance(matches[0].get("inventory"), list) or not matches[0]["inventory"]:
        raise LifecycleError("Concrete cleanup inventory is not covered by an explicit current owner grant")
    return matches[0]


def _endpoint_repository(endpoint):
    """Canonical provider identity, never a branch prefix or fetch alias."""
    from urllib.parse import urlparse
    match = re.fullmatch(r"git@github\.com:([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?", endpoint)
    if match:
        return match.group(1)
    parsed = urlparse(endpoint)
    try:
        port = parsed.port
    except ValueError as error:
        raise LifecycleError("Invalid remote endpoint port") from error
    if (parsed.hostname != "github.com" or parsed.scheme not in ("https", "ssh")
            or parsed.password is not None or parsed.query or parsed.fragment
            or parsed.username not in ((None,) if parsed.scheme == "https" else (None, "git"))
            or port not in (None, 443 if parsed.scheme == "https" else 22)):
        raise LifecycleError("Cleanup requires a canonical, credential-free supported push endpoint")
    name = parsed.path.lstrip("/")
    if name.endswith(".git"):
        name = name[:-4]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", name) or any(p in (".", "..") for p in name.split("/")):
        raise LifecycleError("Remote endpoint repository is invalid")
    return name


def _push_endpoint(root, remote, repository):
    urls = _out(root, "remote", "get-url", "--push", "--all", remote).splitlines()
    if len(urls) != 1 or _endpoint_repository(urls[0]).lower() != repository.lower():
        raise LifecycleError("Actual push endpoint does not uniquely match the authorized repository")
    return urls[0]


def _advertised(root, endpoint, ref):
    result = _git(root, "ls-remote", "--refs", endpoint, ref)
    rows = [row.split("\t") for row in os.fsdecode(result.stdout).splitlines()]
    if any(len(row) != 2 or row[1] != ref for row in rows) or len(rows) > 1:
        raise LifecycleError("Ambiguous actual remote ref observation")
    return _oid(rows[0][0]) if rows else None


def register_cleanup(checkout, registry, flight, *, inventory, reference):
    registry, state, record = _read(registry, flight)
    root = _root(checkout, record)
    if record["lifecycle"]["state"] not in ("active", "review"):
        raise LifecycleError("Only this active flight may register its cleanup contract")
    _text(reference, "owner cleanup reference")
    grant = _grant(record, reference)
    if not isinstance(inventory, list) or not inventory:
        raise LifecycleError("Cleanup inventory must be concrete and nonempty")
    requested, authorized = [_artifact(row) for row in inventory], [_artifact(row) for row in grant["inventory"]]
    if (len({_key(row) for row in requested}) != len(requested)
            or len({row["id"] for row in requested}) != len(requested)
            or {_key(row) for row in requested} != {_key(row) for row in authorized}):
        raise LifecycleError("Registration cannot add or omit the owner's concrete cleanup artifacts")
    by_key = {_key(row): row for row in authorized}
    for item in requested:
        if not set(item["owned_ignored_prefixes"]) <= set(by_key[_key(item)]["owned_ignored_prefixes"]):
            raise LifecycleError("Ignored-file ownership exceeds the explicit cleanup grant")
    existing = record.get("cleanup", {})
    if existing.get("inventory"):
        if existing.get("registration", {}).get("requested") != requested or existing["reference"] != reference:
            raise LifecycleError("Registered cleanup scope is frozen; a later inventory requires an explicit separate decision")
        return {"schema": 1, "status": "registered", "flight": flight, "record": record, "idempotent": True}
    record = initialize(record)
    for item in requested:
        if item["kind"] == "worktree":
            owned = next((row for row in [record["checkout"], *record["children"]] if row["path"] == item["identity"]), None)
            if owned is None:
                raise LifecycleError("Worktree lacks an explicit owning-flight association")
            actual = launch_detection._state(item["identity"], record["repository"]["git_common_dir"])
            if not actual.get("available"):
                raise LifecycleError(actual["reason"])
            item.update(git_dir=_out(item["identity"], "rev-parse", "--path-format=absolute", "--git-dir"),
                        management=owned["management"], classification=owned["kind"], initial_oid=owned["commit"],
                        branch=owned["branch"], client=record["client"]["name"])
        elif item["kind"] == "local_branch":
            item["initial_oid"] = _local_ref(root, item["identity"])
        else:
            endpoint = _push_endpoint(root, item["remote"], record["repository"]["id"])
            item.update(endpoint=endpoint, initial_oid=_advertised(root, endpoint, item["identity"]))
    # Save the input shape separately from enriched observed facts for exact,
    # idempotent registration; neither prefixes nor discovery expand this list.
    record["cleanup"].update(state="registered", inventory=requested, reference=reference,
                             grant_sha256=_hash(grant), registration={"requested": [_artifact(row) for row in inventory],
                                                                    "repository": record["repository"]})
    saved = registry.save(record, expected_revision=state["revision"])
    return {"schema": 1, "status": "registered", "flight": flight, "record": saved["record"], "registry_revision": saved["revision"]}


def _target_branch(reference):
    _text(reference, "target ref")
    if reference.startswith("refs/heads/"):
        return reference[len("refs/heads/"):]
    if reference.startswith("refs/remotes/"):
        parts = reference.split("/", 3)
        if len(parts) == 4:
            return parts[3]
    if reference.startswith("origin/"):
        return reference[len("origin/"):]
    if reference.startswith("refs/"):
        raise LifecycleError("Unsupported delivery target ref")
    return reference


def _normalize_delivery(value, source_base=None):
    if not isinstance(value, dict):
        raise LifecycleError("Actual merged delivery metadata is unavailable")
    base = value.get("base")
    head = value.get("head")
    repository = value.get("repository")
    if isinstance(base, dict):
        repository = base.get("repo", {}).get("full_name")
        target = base.get("ref")
    else:
        target = value.get("target")
    head_repository = head.get("repo", {}).get("full_name") if isinstance(head, dict) else repository
    result = {"repository": repository, "merged": value.get("merged") is True,
              "source_base": value.get("source_base") or source_base or (base if isinstance(base, str) else None),
              "head": head.get("sha") if isinstance(head, dict) else head,
              "merge_commit": value.get("merge_commit") or value.get("merge_commit_sha"),
              "target": target, "method": value.get("method", "provider-preservation"),
              "pull_request": value.get("pull_request") or value.get("number")}
    if not result["merged"] or not repository or head_repository != repository:
        raise LifecycleError("PR is not actually merged in the authorized head/base repository")
    for name in ["source_base", "head", "merge_commit"]:
        _oid(result[name], name)
    _text(result["target"], "actual target")
    return result


def _discover_delivery(root, record, source_tip):
    import checkout_guard
    repository = record["repository"]["id"] if record else checkout_guard._remote_repository(root)
    if checkout_guard._remote_repository(root).lower() != repository.lower():
        raise LifecycleError("Actual provider repository does not match the flight")
    deadline = time.monotonic() + 30
    numbers = record.get("pull_requests", []) if record else []
    if numbers:
        if len(numbers) != 1:
            raise LifecycleError("Multiple PRs require explicit delivery reconciliation")
        value = checkout_guard._gh("repos/" + repository + "/pulls/" + str(numbers[0]), deadline)
    else:
        rows = checkout_guard._gh("repos/" + repository + "/commits/" + source_tip + "/pulls?per_page=100", deadline)
        if not isinstance(rows, list) or len(rows) >= 100:
            raise LifecycleError("Delivery lookup exceeds bounded or available provider coverage")
        candidates = [row for row in rows if row.get("merged_at") and row.get("head", {}).get("sha") == source_tip]
        if len(candidates) != 1:
            raise LifecycleError("No unique actual merged PR identifies this source head")
        value = checkout_guard._gh("repos/" + repository + "/pulls/" + str(candidates[0]["number"]), deadline)
    base = record.get("checkout_guard", {}).get("base", {}).get("commit") if record else None
    return _normalize_delivery(value, base)


def _tree_entries(root, commit):
    entries = {}
    result = _git(root, "ls-tree", "-r", "-z", commit)
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        header, path = raw.split(b"\t", 1)
        mode, kind, oid = header.split()
        entries[os.fsdecode(path)] = {"mode": mode.decode(), "oid": oid.decode(), "type": kind.decode()}
    return entries


def integration_status(checkout, source_tip, target_ref, *, delivery=None, remote_observation=None):
    """Read-only exact preservation at the pinned integration commit.

    An injected delivery is a trusted provider boundary for adapters/tests; public
    CLI paths always discover provider facts. This helper never fetches objects.
    """
    report = {"schema": 1, "status": "unavailable", "verified": False, "source_head": source_tip,
              "source_base": None, "target_tip": None, "merge_commit": None, "method": None,
              "changed_paths": [], "blockers": [],
              "coverage": {"objects": "Local objects only; no fetch/prune", "provider": "Unavailable until observed"}}
    try:
        root = Path(checkout).resolve(strict=True)
        source_tip = _oid(source_tip, "source head")
        value = _normalize_delivery(delivery) if delivery is not None else _discover_delivery(root, None, source_tip)
        report.update(source_base=value["source_base"], merge_commit=value["merge_commit"], method=value["method"])
        report["delivery"] = value
        report["coverage"]["provider"] = "Explicit provider observation" if delivery is not None else "Bounded current GitHub GET"
        if value["head"] != source_tip:
            raise LifecycleError("Source branch advanced or differs from the frozen merged PR head")
        if _target_branch(target_ref) != _target_branch(value["target"]):
            raise LifecycleError("Actual merged target differs from the authorized target")
        if remote_observation is not None:
            if remote_observation.get("available") is not True:
                raise LifecycleError("Actual remote target state is unavailable")
            target = remote_observation.get("target_tip")
            report["coverage"]["target"] = "Actual advertised target observation"
        else:
            target = _resolve(root, target_ref)
            report["coverage"]["target"] = "Locally available target ref; remote freshness not established"
        report["target_tip"] = target
        for name, oid in [("source base", value["source_base"]), ("source head", source_tip),
                          ("integration commit", value["merge_commit"]), ("target tip", target)]:
            if oid is None or _resolve(root, oid) != oid:
                raise LifecycleError(name + " objects are unavailable locally; fetch is not performed")
        if not _ancestor(root, value["source_base"], source_tip):
            raise LifecycleError("Source base does not establish the frozen source history")
        if not _ancestor(root, value["merge_commit"], target):
            raise LifecycleError("Actual target no longer contains the pinned integration commit")
        base, source, merged = [_tree_entries(root, x) for x in [value["source_base"], source_tip, value["merge_commit"]]]
        paths = sorted(path for path in base.keys() | source.keys() if base.get(path) != source.get(path))
        for path in paths:
            expected, observed = source.get(path), merged.get(path)
            same = expected == observed
            row = {"path": path, "mode": expected.get("mode") if expected else None,
                   "oid": expected.get("oid") if expected else None,
                   "observed_mode": observed.get("mode") if observed else None,
                   "observed_oid": observed.get("oid") if observed else None, "verified": same}
            report["changed_paths"].append(row)
            if not same:
                report["blockers"].append("Source bytes/mode/deletion not preserved at integration: " + path)
        if report["blockers"]:
            report["status"] = "blocked"
        else:
            report.update(status="verified", verified=True)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        report["blockers"].append(str(error))
    return report


def _private_file(path, roots):
    raw = Path(path).expanduser()
    if raw.is_symlink():
        raise LifecycleError("Preservation evidence cannot be a symlink")
    path = raw.resolve(strict=True)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
        raise LifecycleError("Preservation evidence must be an owned regular file")
    if any(path == root or root in path.parents for root in roots):
        raise LifecycleError("Preservation proof and copies must be outside disposable worktrees")
    if not any(parent.stat().st_uid == os.geteuid() and not stat.S_IMODE(parent.stat().st_mode) & 0o077
               for parent in path.parents):
        raise LifecycleError("Preservation evidence requires private external storage")
    return path


def _file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ignored(root):
    raw = _git(root, "ls-files", "--others", "--ignored", "--exclude-standard", "-z").stdout
    files = [os.fsdecode(name) for name in raw.split(b"\0") if name]
    if len(files) > MAX_FILES or len(raw) > 2 * 1024 * 1024:
        raise LifecycleError("Ignored-file inventory exceeds bounded coverage; preserve the worktree")
    return files


def _preserved(record, item, files, preservation):
    if not files:
        return {"verified": True, "files": []}
    roots = [Path(row["identity"]) for row in record["cleanup"]["inventory"] if row["kind"] == "worktree"]
    receipts = preservation if isinstance(preservation, list) else [preservation]
    receipts = [row for row in receipts if isinstance(row, dict) and row.get("checkout") == item["identity"]]
    if len(receipts) != 1:
        raise LifecycleError("Ignored/private files require one exact external preservation receipt")
    receipt = receipts[0]
    if receipt.get("flight") != record["flight"]:
        raise LifecycleError("Preservation receipt belongs to another flight")
    producer = receipt.get("producer", {})
    producer_path = _private_file(producer.get("reference", ""), roots)
    if _file_hash(producer_path) != producer.get("sha256"):
        raise LifecycleError("Producer provenance digest differs")
    original = json.loads(producer_path.read_bytes())
    if (original.get("schema") != 1 or original.get("kind") != "generated-private-assets"
            or original.get("flight") != record["flight"] or original.get("checkout") != item["identity"]
            or not original.get("source") or not original.get("reference")):
        raise LifecycleError("Producer provenance does not establish this flight's generated assets")
    rows = receipt.get("files")
    if not isinstance(rows, list) or {row.get("path") for row in rows} != set(files) or len(rows) != len(files):
        raise LifecycleError("Unknown ignored/private files are not covered by producer preservation")
    expected = [{key: row.get(key) for key in ("path", "sha256", "mode")} for row in rows]
    if original.get("files") != expected:
        raise LifecycleError("Preservation cannot invent ownership for files absent from producer provenance")
    observed = []
    for row in rows:
        name = _relative(row["path"])
        if not any(name == prefix.rstrip("/") or prefix.endswith("/") and name.startswith(prefix)
                   for prefix in item.get("owned_ignored_prefixes", [])):
            raise LifecycleError("Ignored file is outside the launch-authorized owned scope: " + name)
        source = Path(item["identity"]) / name
        if source.is_symlink() or not source.is_file():
            raise LifecycleError("Ignored source type is uncertain: " + name)
        target = _private_file(row.get("copy", ""), roots)
        if (_file_hash(source) != row.get("sha256") or _file_hash(target) != row.get("sha256")
                or stat.S_IMODE(source.stat().st_mode) != row.get("mode")
                or stat.S_IMODE(target.stat().st_mode) != row.get("mode")):
            raise LifecycleError("Generated private source/copy bytes or modes changed: " + name)
        observed.append({"path": name, "sha256": row["sha256"], "mode": row["mode"], "copy": str(target)})
    return {"verified": True, "producer": producer, "files": observed, "receipt_sha256": _hash(receipt)}


def _saved_preservation(record, item):
    """After native removal, verify the actual external copies bound beforehand."""
    intent = next((row for row in reversed(_events(record, item["id"])) if row.get("event") == "intent"), None)
    if not intent or not isinstance(intent.get("preservation"), dict):
        raise LifecycleError("Native removal lacks its pre-action preservation observation")
    proof = intent["preservation"]
    if not proof.get("verified"):
        raise LifecycleError("Private preservation was not verified before native removal")
    roots = [Path(row["identity"]) for row in record["cleanup"]["inventory"] if row["kind"] == "worktree"]
    files = proof.get("files", [])
    if files:
        producer = proof["producer"]
        path = _private_file(producer["reference"], roots)
        if _file_hash(path) != producer["sha256"]:
            raise LifecycleError("Retained producer proof changed after removal")
        for row in files:
            target = _private_file(row["copy"], roots)
            if _file_hash(target) != row["sha256"] or stat.S_IMODE(target.stat().st_mode) != row["mode"]:
                raise LifecycleError("Retained private copy changed after removal: " + row["path"])
    return proof


def _current_policy(root, record, supplied):
    import checkout_guard
    if supplied is None:
        names = {row.get("branch") for row in record["cleanup"]["inventory"] if row["kind"] == "worktree"}
        names |= {row["identity"][len("refs/heads/"):] for row in record["cleanup"]["inventory"] if row["kind"] != "worktree"}
        names.discard(None)
        return checkout_guard.resolve_policy(root, record["repository"]["id"], branch_names=sorted(names))
    return checkout_guard._policy(root, record["repository"]["id"], supplied)


def _frozen_delivery(root, record, source_tip, supplied):
    if supplied is not None:
        value = supplied(root, record, source_tip) if callable(supplied) else supplied
        return _normalize_delivery(value, record.get("checkout_guard", {}).get("base", {}).get("commit"))
    frozen = record.get("cleanup", {}).get("frozen_delivery")
    if frozen:
        return _normalize_delivery(frozen)
    return _discover_delivery(root, record, source_tip)


def _record_head(root, record):
    cleanup = record["cleanup"]
    frozen = cleanup.get("frozen_binding", {})
    if frozen.get("source_head"):
        return frozen["source_head"]
    branch = record["checkout"].get("branch")
    tip = _local_ref(root, "refs/heads/" + branch) if branch else None
    return tip or record.get("delivery", {}).get("head") or record["checkout"]["commit"]


def _events(record, artifact_id):
    return [row for row in record.get("cleanup", {}).get("operations", []) if row.get("artifact_id") == artifact_id]


def _native_done(record, item):
    return next((row for row in reversed(_events(record, item["id"]))
                 if row.get("event") == "native_ack" and row.get("state") in ("removed", "already_absent")), None)


def _build_plan(checkout, registry, flight, *, delivery=None, policy=None, client_state=None, preservation=None):
    registry, state, record = _read(registry, flight)
    root = _root(checkout, record)
    cleanup = record.get("cleanup")
    report = {"schema": 1, "flight": flight, "status": "blocked", "ready": False, "complete": False,
              "blockers": [], "artifacts": [], "registry_revision": state["revision"]}
    if not isinstance(cleanup, dict) or cleanup.get("protocol") != PROTOCOL:
        report["blockers"].append("Required cleanup protocol is not registered; historical ownership is not a cleanup grant")
        return report
    if not cleanup.get("inventory") or not cleanup.get("reference"):
        report["blockers"].append("Concrete cleanup inventory/authorization is pending")
        return report
    grant = _grant(record, cleanup["reference"])
    if _hash(grant) != cleanup["grant_sha256"]:
        report["blockers"].append("Cleanup grant changed after registration; do not expand the existing plan")
        return report
    try:
        current_policy = _current_policy(root, record, policy)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        report["blockers"].append(str(error))
        return report
    protected = set(current_policy["protected_branches"]) | {current_policy["default_branch"]}
    protected |= set(record["configuration"]["values"].get("protected_branches", []))
    source_tip = _record_head(root, record)
    try:
        actual_delivery = _frozen_delivery(root, record, source_tip, delivery)
        if actual_delivery["repository"].lower() != record["repository"]["id"].lower():
            raise LifecycleError("Merged provider repository differs from the authorized flight")
        target_ref = record["delivery"].get("target") or "refs/heads/" + current_policy["default_branch"]
        if _target_branch(actual_delivery["target"]) != _target_branch(target_ref):
            raise LifecycleError("Merged target differs from the recorded flight target")
        remote_items = [row for row in cleanup["inventory"] if row["kind"] == "remote_branch"]
        remote_observation = None
        if remote_items:
            endpoint = _push_endpoint(root, remote_items[0]["remote"], record["repository"]["id"])
            if endpoint != remote_items[0]["endpoint"]:
                raise LifecycleError("Actual push endpoint changed after launch registration")
            target_tip = _advertised(root, endpoint, "refs/heads/" + _target_branch(target_ref))
            remote_observation = {"available": True, "target_tip": target_tip}
        integration = integration_status(root, source_tip, target_ref, delivery=actual_delivery,
                                         remote_observation=remote_observation)
        report["integration"] = integration
        if not integration["verified"]:
            report["blockers"].extend(integration["blockers"])
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        actual_delivery = None
        report["blockers"].append(str(error))
    head = actual_delivery["head"] if actual_delivery else source_tip
    branch = record["checkout"].get("branch")
    actual_source = _local_ref(root, "refs/heads/" + branch) if branch else None
    if actual_source is not None and actual_source != head:
        report["blockers"].append("Source branch advanced after the frozen merged head")
    worktrees = launch_detection._worktrees(root)
    worktree_by_path = {row["path"]: row for row in worktrees}
    planned_paths = {row["identity"] for row in cleanup["inventory"] if row["kind"] == "worktree"}
    for item in cleanup["inventory"]:
        row = {key: copy.deepcopy(item.get(key)) for key in ["id", "kind", "identity", "remote"]}
        row.update(state="eligible", expected_oid=head, observed_oid=None, blockers=[])
        try:
            completed = any(event.get("state") in ("removed", "already_absent") and event.get("event") in ("outcome", "native_ack")
                            for event in _events(record, item["id"]))
            for other in state["records"]:
                if other["flight"] == flight or other["lifecycle"]["state"] == "closed":
                    continue
                if item["kind"] == "worktree" and any(x["path"] == item["identity"] for x in [other["checkout"], *other["children"]]):
                    raise LifecycleError("Another unfinished flight owns this worktree")
                if item["kind"] != "worktree" and other["repository"]["id"] != record["repository"]["id"]:
                    continue
                if item["kind"] == "local_branch" and other["repository"]["git_common_dir"] != record["repository"]["git_common_dir"]:
                    continue
                if item["kind"] != "worktree" and any(x.get("branch") == item["identity"][len("refs/heads/"):] for x in [other["checkout"], *other["children"]]):
                    raise LifecycleError("Branch is shared with another unfinished flight")
            if item["kind"] == "worktree":
                path = Path(item["identity"])
                admin = worktree_by_path.get(item["identity"])
                if not path.exists() and not admin and not Path(item["git_dir"]).exists():
                    if item["management"] == "native" and not _native_done(record, item):
                        raise LifecycleError("Missing native worktree needs observed native request/ack reconciliation")
                    row["preservation"] = _saved_preservation(record, item)
                    row["state"] = "already_absent"
                else:
                    if completed:
                        raise LifecycleError("Worktree reappeared after completed cleanup; a separate decision is required")
                    if not path.is_dir() or not admin:
                        raise LifecycleError("Worktree path/administrative state is ambiguous")
                    if admin.get("locked") or admin.get("prunable"):
                        raise LifecycleError("Locked or prunable worktree must be preserved")
                    if item["classification"] != "disposable-temporary":
                        raise LifecycleError("Preserved-existing checkout is never a disposable worktree")
                    git_dir = _out(path, "rev-parse", "--path-format=absolute", "--git-dir")
                    common = _out(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
                    if git_dir != item["git_dir"] or common != record["repository"]["git_common_dir"]:
                        raise LifecycleError("Worktree administrative/repository identity changed")
                    if git_dir == common:
                        raise LifecycleError("Repository main checkout must be preserved")
                    observed = launch_detection._state(path, common)
                    if not observed.get("available"):
                        raise LifecycleError(observed.get("reason", "Checkout unavailable"))
                    row["observed_oid"] = observed["commit"]
                    if observed["commit"] != head or observed["branch"] != item["branch"]:
                        raise LifecycleError("Worktree branch/head advanced or changed after the merged head")
                    if observed["branch"] in protected:
                        raise LifecycleError("Protected/shared working branch must be preserved")
                    if observed["dirty"] or observed["untracked"]:
                        raise LifecycleError("Dirty/staged/untracked work must be preserved")
                    row["preservation"] = _preserved(record, item, _ignored(path), preservation)
                    if not isinstance(client_state, dict) or client_state.get("client") != item["client"] or client_state.get("available") is not True or client_state.get("safely_left") is not True:
                        raise LifecycleError("Actual native client availability and safe-leave observation are required")
                    if root == path or path in root.parents or Path.cwd().resolve() == path or path in Path.cwd().resolve().parents:
                        raise LifecycleError("Safely leave the disposable execution checkout before cleanup")
            else:
                name = item["identity"][len("refs/heads/"):]
                if name in protected or name == _target_branch(record["delivery"].get("target") or current_policy["default_branch"]):
                    raise LifecycleError("Protected/default/shared integration branch must be preserved")
                if item["kind"] == "local_branch":
                    observed = _local_ref(root, item["identity"])
                    users = [x["path"] for x in worktrees if x.get("branch") == name]
                    if any(path not in planned_paths for path in users):
                        raise LifecycleError("Branch is checked out in a preserved/other active worktree")
                    row["requires"] = users
                else:
                    endpoint = _push_endpoint(root, item["remote"], record["repository"]["id"])
                    if endpoint != item["endpoint"]:
                        raise LifecycleError("Actual push endpoint drifted after registration")
                    row["endpoint"] = endpoint
                    observed = _advertised(root, endpoint, item["identity"])
                row["observed_oid"] = observed
                if observed is None:
                    row["state"] = "already_absent"
                elif completed:
                    raise LifecycleError("Branch reappeared after completed cleanup; a separate decision is required")
                elif observed != head:
                    raise LifecycleError("Branch advanced or differs from the frozen merged head")
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            row["state"] = "retained"
            row["blockers"].append(str(error))
        report["artifacts"].append(row)
    for row in report["artifacts"]:
        report["blockers"].extend(row["id"] + ": " + reason for reason in row["blockers"])
    binding = {"flight": flight, "repository": record["repository"], "inventory": cleanup["inventory"],
               "grant_sha256": cleanup["grant_sha256"], "configuration": record["configuration"]["revision"],
               "source_head": head, "delivery": actual_delivery}
    report.update(binding=binding, plan_sha256=_hash(binding), delivery=actual_delivery)
    frozen = cleanup.get("frozen_binding")
    if frozen is not None and frozen != binding:
        report["blockers"].append("Interrupted cleanup cannot refresh its frozen identities or leases")
    report["ready"] = not report["blockers"]
    report["complete"] = report["ready"] and all(row["state"] == "already_absent" for row in report["artifacts"])
    report["status"] = "complete" if report["complete"] else "ready" if report["ready"] else "blocked"
    return report


def plan(control_checkout, registry, flight, *, delivery=None, policy=None, client_state=None, preservation=None):
    return _build_plan(control_checkout, registry, flight, delivery=delivery, policy=policy,
                       client_state=client_state, preservation=preservation)


def _persist(registry, flight, binding, event=None, delivery=None):
    registry, state, record = _read(registry, flight)
    cleanup = record["cleanup"]
    if _hash(binding) != _hash(cleanup.get("frozen_binding", binding)):
        raise LifecycleError("Cleanup scope/lease changed during interrupted operation")
    if (cleanup["grant_sha256"] != binding["grant_sha256"] or cleanup["inventory"] != binding["inventory"]
            or _hash(_grant(record, cleanup["reference"])) != binding["grant_sha256"]):
        raise LifecycleError("Cleanup grant/inventory changed during operation")
    cleanup.setdefault("frozen_binding", copy.deepcopy(binding))
    cleanup.setdefault("frozen_delivery", copy.deepcopy(delivery))
    if event is not None:
        cleanup["operations"].append(copy.deepcopy(event))
    cleanup["state"] = "pending"
    registry.save(record, expected_revision=state["revision"])
    return record


def apply(control_checkout, registry, flight, plan, *, artifact_id=None, native_cleanup=None,
          delivery=None, policy=None, client_state=None, preservation=None):
    fresh = _build_plan(control_checkout, registry, flight, delivery=delivery, policy=policy,
                        client_state=client_state, preservation=preservation)
    if not fresh["ready"]:
        return fresh
    if fresh.get("plan_sha256") != plan.get("plan_sha256") or fresh["binding"] != plan.get("binding"):
        raise LifecycleError("Cleanup plan identities changed; no deletion is authorized")
    registry = _registry(registry)
    root = Path(control_checkout).resolve()
    selected = [row for row in fresh["artifacts"] if artifact_id is None or row["id"] == artifact_id]
    if not selected:
        raise LifecycleError("Artifact is outside the frozen authorized inventory")
    order = {"worktree": 0, "remote_branch": 1, "local_branch": 2}
    for row in sorted(selected, key=lambda row: order[row["kind"]]):
        # Observe again immediately before each action, including native absence,
        # actual remote endpoint, source tip and all preservation boundaries.
        current = _build_plan(root, registry, flight, delivery=delivery, policy=policy,
                              client_state=client_state, preservation=preservation)
        if not current["ready"] or current["plan_sha256"] != fresh["plan_sha256"]:
            return current
        row = next(x for x in current["artifacts"] if x["id"] == row["id"])
        operation_id = "cleanup-" + _hash({"plan": current["plan_sha256"], "artifact": row["id"]})[:24]
        event = {"event": "intent", "artifact_id": row["id"], "operation_id": operation_id,
                 "expected_oid": row["expected_oid"], "state": "started"}
        if row["kind"] == "worktree":
            event["preservation"] = copy.deepcopy(row.get("preservation"))
        _, _, record = _read(registry, flight)
        existing = next((x for x in _events(record, row["id"]) if x.get("event") == "intent" and x.get("operation_id") == operation_id), None)
        if existing is None:
            _persist(registry, flight, current["binding"], event, current["delivery"])
        if row["state"] == "already_absent":
            _persist(registry, flight, current["binding"], dict(event, event="outcome", state="already_absent"), current["delivery"])
            continue
        if row["kind"] == "worktree":
            item = next(x for x in record["cleanup"]["inventory"] if x["id"] == row["id"])
            if item["management"] != "native":
                return dict(current, status="blocked", ready=False,
                            blockers=["Manual worktree requires separately recorded supported native/manual disposition; no fallback deletion"])
            request = {"operation_id": operation_id, "artifact_id": row["id"], "client": item["client"],
                       "path": row["identity"], "expected_oid": row["expected_oid"], "git_dir": item["git_dir"],
                       "plan_sha256": current["plan_sha256"], "preservation": row.get("preservation")}
            if native_cleanup is None:
                pending = copy.deepcopy(current)
                next(x for x in pending["artifacts"] if x["id"] == row["id"])["state"] = "native_action_required"
                return dict(pending, status="native_action_required", complete=False, request=request)
            result = native_cleanup(copy.deepcopy(request))
            acknowledged = acknowledge_native(root, registry, flight, plan, row["id"], result)
            if not acknowledged["ready"]:
                return acknowledged
        else:
            if row["kind"] == "local_branch":
                if any(x.get("branch") == row["identity"][len("refs/heads/"):] for x in launch_detection._worktrees(root)):
                    return dict(current, status="blocked", ready=False, blockers=["Branch remains checked out; native leave/removal is pending"])
                command = ("update-ref", "--no-deref", "-d", row["identity"], row["expected_oid"])
            else:
                command = ("push", "--force-with-lease=" + row["identity"] + ":" + row["expected_oid"],
                           row["endpoint"], ":" + row["identity"])
            try:
                result = _git(root, *command, required=False, timeout=30)
                exit_code, stderr = result.returncode, os.fsdecode(result.stderr)
            except LifecycleError as error:
                exit_code, stderr = None, str(error)
            # A timeout or lost response is reconciled by readback, never a
            # refreshed lease. Empty successful advertisement means absence;
            # unavailable state is not absence.
            try:
                after = (_local_ref(root, row["identity"]) if row["kind"] == "local_branch" else
                         _advertised(root, row["endpoint"], row["identity"]))
                absent = after is None
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                after, absent = None, False
                stderr += "; readback unavailable: " + str(error)
            outcome = dict(event, event="outcome", state=("removed" if exit_code == 0 else "already_absent") if absent else "failed",
                           exit_code=exit_code, observed_oid=after, stderr=stderr[-4000:],
                           stderr_sha256=hashlib.sha256(stderr.encode()).hexdigest(), output_truncated=len(stderr) > 4000)
            _persist(registry, flight, current["binding"], outcome, current["delivery"])
            if not absent:
                return dict(current, status="blocked", ready=False, blockers=["Exact old-OID deletion failed or artifact advanced; retain/reconcile it"], outcome=outcome)
    return _build_plan(root, registry, flight, delivery=delivery, policy=policy,
                       client_state=client_state, preservation=preservation)


def acknowledge_native(control_checkout, registry, flight, plan, artifact_id, result):
    registry, state, record = _read(registry, flight)
    root = _root(control_checkout, record)
    cleanup = record.get("cleanup", {})
    binding = cleanup.get("frozen_binding")
    if binding is None or _hash(binding) != plan.get("plan_sha256") or binding != plan.get("binding"):
        raise LifecycleError("Native acknowledgement lacks the existing frozen operation plan")
    item = next((row for row in cleanup["inventory"] if row["id"] == artifact_id and row["kind"] == "worktree"), None)
    if item is None:
        raise LifecycleError("Native acknowledgement is outside worktree cleanup scope")
    intent = next((row for row in reversed(_events(record, artifact_id)) if row.get("event") == "intent"), None)
    blockers = []
    if _hash(_grant(record, cleanup["reference"])) != cleanup["grant_sha256"]:
        blockers.append("Cleanup authority changed during the native action")
    if not intent or not isinstance(result, dict):
        blockers.append("Actual native result/request is unavailable")
    elif (result.get("client") != item["client"] or result.get("path") != item["identity"]
          or result.get("operation_id") != intent["operation_id"] or result.get("success") is not True):
        blockers.append("Native result does not match the observed client, path and operation")
    if Path(item["identity"]).exists() or Path(item["git_dir"]).exists() or any(
            row["path"] == item["identity"] for row in launch_detection._worktrees(root)):
        blockers.append("Native success cannot substitute for actual worktree path/admin removal")
    if not blockers:
        try:
            _saved_preservation(record, item)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            blockers.append(str(error))
    event = {"event": "native_ack", "artifact_id": artifact_id, "operation_id": intent["operation_id"] if intent else None,
             "state": "failed" if blockers else "removed", "result": copy.deepcopy(result), "blockers": blockers}
    _persist(registry, flight, binding, event, cleanup.get("frozen_delivery"))
    return {"schema": 1, "status": "blocked" if blockers else "acknowledged", "flight": flight,
            "ready": not blockers, "complete": False, "blockers": blockers, "artifact_id": artifact_id,
            "artifacts": [{"id": artifact_id, "kind": "worktree", "identity": item["identity"],
                           "state": "retained" if blockers else "removed", "expected_oid": intent.get("expected_oid") if intent else None,
                           "observed_oid": None, "blockers": blockers}]}


def closure_status(control_checkout, registry, flight, *, delivery=None, policy=None, client_state=None, preservation=None):
    _, _, record = _read(registry, flight)
    if not isinstance(record.get("cleanup"), dict) or record["cleanup"].get("protocol") != PROTOCOL:
        return {"schema": 1, "status": "legacy", "flight": flight, "ready": True, "complete": True,
                "blockers": [], "coverage": "Preexisting markerless record; no historical cleanup authority invented"}
    result = _build_plan(control_checkout, registry, flight, delivery=delivery, policy=policy,
                         client_state=client_state, preservation=preservation)
    if not result["complete"] and result["ready"]:
        result.update(status="blocked", ready=False)
        result["blockers"].append("Required disposable cleanup/disposition remains pending inside PR & Merge")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("launch", "register", "plan", "apply", "ack-native", "status"))
    parser.add_argument("--checkout", type=Path, default=Path.cwd())
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--flight")
    parser.add_argument("--repository")
    parser.add_argument("--issue", type=int, action="append", default=[])
    parser.add_argument("--pr", type=int, action="append", default=[])
    parser.add_argument("--current-flight")
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--reference")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--artifact")
    parser.add_argument("--result", type=Path)
    parser.add_argument("--preservation", type=Path)
    parser.add_argument("--client-state", type=Path)
    args = parser.parse_args(argv)
    read = lambda path: json.loads(path.read_bytes()) if path else None
    try:
        if args.action == "launch":
            if not args.repository:
                raise LifecycleError("launch requires --repository")
            result = launch(args.checkout, args.registry, args.repository, issues=args.issue,
                            pull_requests=args.pr, current_flight=args.current_flight)
        else:
            _text(args.flight, "flight")
            if args.action == "register":
                result = register_cleanup(args.checkout, args.registry, args.flight,
                                          inventory=read(args.inventory), reference=args.reference)
            elif args.action == "ack-native":
                result = acknowledge_native(args.checkout, args.registry, args.flight, read(args.plan),
                                            args.artifact, read(args.result))
            elif args.action == "status":
                result = closure_status(args.checkout, args.registry, args.flight,
                                        client_state=read(args.client_state), preservation=read(args.preservation))
            else:
                options = {"client_state": read(args.client_state), "preservation": read(args.preservation)}
                result = (apply(args.checkout, args.registry, args.flight, read(args.plan),
                                artifact_id=args.artifact, **options) if args.action == "apply" else
                          plan(args.checkout, args.registry, args.flight, **options))
        print(json.dumps(result, indent=2))
        return 2 if result.get("ready") is False else 0
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as error:
        print(json.dumps({"schema": 1, "status": "blocked", "ready": False, "complete": False, "blockers": [str(error)]}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
