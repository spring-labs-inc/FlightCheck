"""Common project configuration. Commands are recorded data, never executed checks.

The canonical flat-compatible document is private local project.json. Shared
views are allowlisted projections, never another source of defaults.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

CONFIG = ".flightcheck/project.json"
PRIVATE_FILES = (CONFIG, ".flightcheck/docs/status.md")
META = "_flightcheck"
MUTABLE = {"checkout_policy", "protected_branches", "default_branch", "checks", "resources", "status_sync"}
PUBLIC = {"checkout_policy", "protected_branches", "default_branch", "activation"}
HOST = {"python", "observed_python", "evidence_dir", "checks", "reviewer_access", "delivery",
        "policy_reference", "activation_reference", "nit_tracker"}


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def revision(raw):
    return hashlib.sha256(raw).hexdigest()


def command(root, args):
    result = subprocess.run(args, cwd=root, capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise ValueError("Configuration validation failed: " + " ".join(args) + ": " + result.stderr.strip())
    return result.stdout.strip()


def branch(root, value):
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError("Invalid branch configuration")
    # Stored policy names must be literal refs. --branch alone expands checkout
    # history such as @{-1}, making identical saved bytes change meaning.
    try:
        command(root, ["git", "--no-optional-locks", "check-ref-format", "refs/heads/" + value])
        command(root, ["git", "--no-optional-locks", "check-ref-format", "--branch", value])
    except ValueError as error:
        raise ValueError("Invalid literal branch configuration: " + value) from error
    return value


def text(value, name):
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError("Invalid configuration field: " + name)
    return value


def sync_schema():
    """Load the adjacent schema, verifying installed bytes before execution.

    The installer loads this model by filename rather than changing sys.path;
    use that same small loading boundary for its synchronization adapter.
    """
    path = Path(__file__).with_name("status_sync_config.py")
    if path.is_symlink():
        raise ValueError("Synchronization schema cannot be a symlink")
    raw = path.read_bytes()
    if path.parent.parent.name == ".flightcheck":
        state = json.loads((path.parent.parent / "installation.json").read_bytes())
        expected = state.get("files", {}).get(".flightcheck/scripts/status_sync_config.py", {}).get("sha256")
        if revision(raw) != expected:
            raise ValueError("Modified installed synchronization schema; refusing execution")
    namespace = {"__file__": str(path), "__name__": "flightcheck_status_sync_config"}
    exec(compile(raw, str(path), "exec"), namespace)
    from types import SimpleNamespace
    return SimpleNamespace(**namespace)


def normalize(root, supplied, detected=None, origin="legacy", trusted_metadata=False, probe_runtime=True):
    root = Path(root).resolve()
    if not isinstance(supplied, dict):
        raise ValueError("Configuration must be an object")
    value = copy.deepcopy(supplied)
    detected = detected or {}
    value.setdefault("activation", "opt-in")
    value.setdefault("delivery", "No provider writes without owner approval")
    value.setdefault("python", detected.get("python"))
    value.setdefault("default_branch", detected.get("default_branch"))
    pending = [k for k in ("evidence_dir", "nit_tracker", "checks", "policy_reference", "default_branch") if not value.get(k)]
    if pending:
        raise ValueError("Resolve configuration together before applying: " + ", ".join(pending))
    if value["activation"] not in ("opt-in", "default-for-coding"):
        raise ValueError("activation must be opt-in or default-for-coding")
    if value["activation"] == "default-for-coding" and not value.get("activation_reference"):
        raise ValueError("default-for-coding needs an explicit owner activation_reference")
    for key in ("nit_tracker", "policy_reference", "default_branch", "delivery", "python", "evidence_dir"):
        text(value.get(key), key)
    branch(root, value["default_branch"])
    discovered = detected.get("default_branch")
    if discovered and value["default_branch"] != discovered:
        raise ValueError("Configured default_branch conflicts with discovered repository default " + discovered + "; reconcile the actual default before applying")
    evidence = Path(value["evidence_dir"]).expanduser()
    if not evidence.is_absolute() or evidence.is_symlink():
        raise ValueError("evidence_dir must be an absolute, nonsymlink path outside the checkout")
    evidence = evidence.resolve()
    if evidence == root or root in evidence.parents:
        raise ValueError("Keep evidence outside the checkout")
    if evidence.exists() and (not evidence.is_dir() or evidence.stat().st_uid != os.geteuid() or stat.S_IMODE(evidence.stat().st_mode) & 0o077):
        raise ValueError("Existing evidence directory must be owner-only (0700)")
    value["evidence_dir"] = str(evidence)
    python = Path(value["python"]).expanduser()
    if not python.is_absolute():
        python = root / python
    value["python"] = str(python)
    observed = (json.loads(command(root, [str(python), "-B", "-c", "import json,os,sys,fcntl;print(json.dumps({'platform':os.name,'version_info':list(sys.version_info[:2]),'version':sys.version}))"]))
                if probe_runtime else value.get("observed_python"))
    if (not isinstance(observed, dict) or observed.get("platform") != "posix"
            or not isinstance(observed.get("version_info"), list) or observed["version_info"] < [3, 9]):
        raise ValueError("Receipt/card tools require Python 3.9+ on POSIX")
    value["observed_python"] = observed
    if not isinstance(value["checks"], list) or not value["checks"]:
        raise ValueError("Configure the project's actual non-mutating check commands")
    for check in value["checks"]:
        if (not isinstance(check, dict) or not isinstance(check.get("name"), str) or not check["name"].strip()
                or not isinstance(check.get("command"), list) or not check["command"]
                or any(not isinstance(a, str) or not a or "\x00" in a for a in check["command"])
                or check.get("phase") not in ("cheap", "authoritative")):
            raise ValueError("Each check needs name, command argument array and cheap/authoritative phase")
    policy = value.setdefault("checkout_policy", {"mode": "native-choice", "git_fallback": False})
    if not isinstance(policy, dict) or set(policy) - {"mode", "branch_prefix", "git_fallback", "fallback_reference"}:
        raise ValueError("Invalid checkout_policy fields; protected-branch safeguards cannot be disabled")
    policy.setdefault("mode", "native-choice")
    policy.setdefault("git_fallback", False)
    if policy["mode"] not in ("native-choice", "worktree-required") or not isinstance(policy["git_fallback"], bool):
        raise ValueError("checkout_policy requires native-choice or worktree-required and boolean git_fallback")
    if policy["git_fallback"]:
        text(policy.get("fallback_reference"), "checkout_policy.fallback_reference")
    if "branch_prefix" in policy:
        text(policy["branch_prefix"], "checkout_policy.branch_prefix")
        branch(root, policy["branch_prefix"] + "flight")
    protected = value.setdefault("protected_branches", [])
    if not isinstance(protected, list):
        raise ValueError("protected_branches must be an array")
    value["protected_branches"] = sorted({branch(root, b) for b in protected} | {value["default_branch"]})
    value["status_sync"] = sync_schema().normalize(value.get("status_sync"))
    resources = value.get("resources", {})
    if not isinstance(resources, dict):
        raise ValueError("resources must be an object")
    for key, pointer in resources.items():
        text(key, "resource name")
        text(pointer, "resources." + key)
    old_meta = value.get(META, {}) if trusted_metadata else {}
    if trusted_metadata and META in value and (not isinstance(old_meta, dict) or old_meta.get("schema") != 1 or not isinstance(old_meta.get("fields"), dict)):
        raise ValueError("Unsupported configuration metadata")
    fields = {}
    for key in set(value) - {META}:
        previous = old_meta.get("fields", {}).get(key)
        scope = "project" if key in PUBLIC or key in ("resources", "status_sync") else "host"
        value_sha = revision(encoded(value[key]))
        if previous is not None:
            if (not isinstance(previous, dict) or set(previous) != {"source", "scope", "confirmed", "confirmation_reference", "last_validation", "value_sha256"}
                    or previous["source"] not in ("legacy", "supplied", "discovered", "default", "explicit-update")
                    or previous["scope"] != scope or not isinstance(previous["confirmed"], bool)
                    or not isinstance(previous["last_validation"], dict)
                    or previous["last_validation"] != {"status": "valid", "validator": "project-config-v1"}
                    or not isinstance(previous["value_sha256"], str)
                    or previous["confirmation_reference"] is not None and not isinstance(previous["confirmation_reference"], str)):
                raise ValueError("Invalid field metadata: " + key)
            if previous["value_sha256"] != value_sha:
                previous = None
        source = ("supplied" if key in supplied else "discovered" if key in detected else "default") if origin == "setup" else "legacy"
        fields[key] = previous or {"source": source, "scope": scope,
                                  "confirmed": source == "supplied", "confirmation_reference": value["policy_reference"] if source == "supplied" else None,
                                  "last_validation": {"status": "valid", "validator": "project-config-v1"}, "value_sha256": value_sha}
    value[META] = {"schema": 1, "fields": fields}
    encoded(value)  # Refuse nonfinite or unserializable extension values.
    return value


def protected(config):
    return sorted(set(config.get("protected_branches", [])) | {config["default_branch"]})


def shared(config):
    # Free-form references/commands can contain host paths or credentials. The
    # foundation shares only typed policy values; resource pointers are local
    # until their separate publishing validation is defined.
    result = {k: copy.deepcopy(config[k]) for k in PUBLIC if k in config}
    if "checkout_policy" in result:
        result["checkout_policy"].pop("fallback_reference", None)
    result[META] = {"schema": 1, "fields": {k: {"source": config.get(META, {}).get("fields", {}).get(k, {}).get("source", "legacy"),
                    "scope": "project", "confirmed": config.get(META, {}).get("fields", {}).get(k, {}).get("confirmed", False),
                    "last_validation": {"status": "valid", "validator": "project-config-v1"}} for k in result}}
    return result


def snapshot(root):
    path = Path(root).resolve() / CONFIG
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Configuration path cannot traverse symlinks")
    raw = path.read_bytes()
    return {"revision": revision(raw), "values": normalize(Path(root), json.loads(raw), trusted_metadata=True, probe_runtime=False)}


def propose(root, current, changes, expected_revision, reference):
    if current["revision"] != expected_revision:
        raise ValueError("Stale configuration revision; read current configuration and preview again")
    text(reference, "update confirmation reference")
    if not isinstance(changes, dict) or not changes:
        raise ValueError("Configuration update requires a nonempty changes object")
    unsupported = set(changes) - MUTABLE
    if unsupported:
        raise ValueError("Unsupported configuration reconciliation for: " + ", ".join(sorted(unsupported)) + "; runtime, evidence, activation and authority remain pinned")
    if "default_branch" in changes and changes["default_branch"] != current["values"].get("default_branch"):
        observed = command(root, ["git", "--no-optional-locks", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"])
        if observed.removeprefix("origin/") != changes["default_branch"]:
            raise ValueError("Changed default_branch does not match discovered repository default; reconcile actual default before updating")
    value = copy.deepcopy(current["values"])
    for key, change in changes.items():
        value[key] = copy.deepcopy(change)
        value.setdefault(META, {"schema": 1, "fields": {}})["fields"].pop(key, None)
    result = normalize(root, value, trusted_metadata=True)
    for key in changes:
        result[META]["fields"][key].update(source="explicit-update", confirmed=True, confirmation_reference=reference)
    return result
