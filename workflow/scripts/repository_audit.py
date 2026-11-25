"""Explicit read-only branch/worktree audit; recommendations grant no authority.

The audit observes metadata. It does not start a flight, create a Registry, fetch
objects, prune refs, run configured checks, or invoke native client actions.
Keep its output private: locations and recorded session associations are local
operational information, even though file contents and credentials are omitted.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
from urllib.parse import unquote, urlsplit

from flight_associations import AssociationError, Registry, retained_artifacts, reservation_conflicts
from project_config import PRIVATE_FILES

COMMAND_SECONDS = 10
AUDIT_SECONDS = 120
MAX_OUTPUT = 8 * 1024 * 1024
MAX_REFS = 10000
MAX_ARTIFACTS = 20000
MAX_WORKTREES = 1000
MAX_REMOTE_ENDPOINTS = 50
MAX_PATHS = 5000
_READ_COMMANDS = {"rev-parse", "symbolic-ref", "worktree", "status", "ls-files",
                  "for-each-ref", "rev-list", "merge-base", "cat-file", "config",
                  "remote", "ls-remote"}
_OID = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


class AuditUnavailable(ValueError):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def _ssh_command():
    """Ignore SSH configuration and disable its state-changing conveniences."""
    binary = Path("/usr/bin/ssh")
    if not binary.is_file():
        return None
    known = str(Path.home() / ".ssh/known_hosts")
    options = [str(binary), "-F", "/dev/null", "-o", "BatchMode=yes", "-o",
               "StrictHostKeyChecking=yes", "-o", "UpdateHostKeys=no", "-o",
               "ControlMaster=no", "-o", "ControlPath=none", "-o",
               "ControlPersist=no", "-o", "PermitLocalCommand=no", "-o",
               "ProxyCommand=none", "-o", "ProxyJump=none", "-o",
               "ForwardAgent=no", "-o", "AddKeysToAgent=no", "-o",
               "IdentitiesOnly=yes", "-o", "GSSAPIAuthentication=no", "-o",
               "UserKnownHostsFile=" + known]
    return " ".join(shlex.quote(item) for item in options)


def _environment():
    env = dict(os.environ)
    for name in list(env):
        if (name in {"GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
                     "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                     "GIT_NAMESPACE", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT",
                     "GIT_SSH", "GIT_SSH_COMMAND", "GIT_EXTERNAL_DIFF", "GIT_DIFF_OPTS",
                     "GIT_CURL_VERBOSE", "GIT_PROXY_COMMAND", "GIT_SSH_VARIANT",
                     "GIT_ASKPASS", "SSH_ASKPASS"}
                or name.startswith(("GIT_TRACE", "GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))):
            env.pop(name, None)
    env.update(GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0",
               GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null",
               GIT_ALLOW_PROTOCOL="https:ssh:file", GIT_NO_REPLACE_OBJECTS="1",
               GIT_NO_LAZY_FETCH="1",
               GIT_GRAFT_FILE="/dev/null", GIT_ASKPASS="/usr/bin/false",
               SSH_ASKPASS="/usr/bin/false", SSH_ASKPASS_REQUIRE="never",
               PYTHONDONTWRITEBYTECODE="1")
    # These also constrain the shared read-only policy/integration subprocesses.
    settings = [("core.fsmonitor", "false"), ("core.untrackedCache", "false"),
                ("core.preloadIndex", "false"), ("gc.auto", "0"),
                ("maintenance.auto", "false"), ("credential.helper", ""),
                ("credential.interactive", "false"), ("core.askPass", "/usr/bin/false"),
                ("http.extraHeader", ""), ("http.cookieFile", ""),
                ("http.saveCookies", "false"), ("protocol.ext.allow", "never"),
                ("protocol.allow", "never"), ("protocol.https.allow", "always"),
                ("protocol.ssh.allow", "always"), ("protocol.file.allow", "always"),
                ("submodule.recurse", "false")]
    ssh = _ssh_command()
    if ssh:
        settings.append(("core.sshCommand", ssh))
    env["GIT_CONFIG_COUNT"] = str(len(settings))
    for number, (key, value) in enumerate(settings):
        env["GIT_CONFIG_KEY_" + str(number)] = key
        env["GIT_CONFIG_VALUE_" + str(number)] = value
    return env


class _Reader:
    def __init__(self):
        self.deadline = time.monotonic() + AUDIT_SECONDS
        self.env = _environment()
        self.commands = {}
        self.limits = []

    def run(self, argv, label, *, seconds=COMMAND_SECONDS, allow_failure=False):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise AuditUnavailable("Audit observation deadline exhausted")
        self.commands[label] = self.commands.get(label, 0) + 1
        try:
            result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True,
                                    env=self.env, timeout=min(seconds, remaining))
        except (OSError, subprocess.SubprocessError) as error:
            raise AuditUnavailable(label + " unavailable (" + type(error).__name__ + ")") from error
        if len(result.stdout) + len(result.stderr) > MAX_OUTPUT:
            raise AuditUnavailable(label + " exceeds bounded output coverage")
        if result.returncode and not allow_failure:
            # Transport stderr can contain private URLs or credentials.
            raise AuditUnavailable(label + " unavailable (exit " + str(result.returncode) + ")")
        return result

    def git(self, checkout, *args, allow_failure=False):
        if not args or args[0] not in _READ_COMMANDS:
            raise AuditUnavailable("Non-read-only Git command refused")
        if args[0] == "worktree" and tuple(args[1:]) != ("list", "--porcelain", "-z"):
            raise AuditUnavailable("Only worktree listing is permitted")
        if args[0] == "remote" and (len(args) < 2 or args[1] != "get-url"):
            raise AuditUnavailable("Only remote URL observation is permitted")
        if args[0] == "config" and not any(flag in args for flag in ("--get-regexp", "--get-all")):
            raise AuditUnavailable("Only configuration queries are permitted")
        if args[0] == "cat-file" and (len(args) < 2 or args[1] not in ("-e", "-t")):
            raise AuditUnavailable("File-content reads are outside metadata audit")
        return self.run(["git", "--no-optional-locks", "--no-replace-objects",
                         "-c", "core.fsmonitor=false", "-C", "/" if args[0] == "ls-remote" else str(checkout), *args],
                        "git " + args[0], allow_failure=allow_failure)

    def text(self, checkout, *args, allow_failure=False):
        return os.fsdecode(self.git(checkout, *args, allow_failure=allow_failure).stdout).rstrip("\n")

    def limit(self, values, maximum, label):
        if len(values) > maximum:
            self.limits.append(label + " truncated: observed " + str(len(values))
                               + ", reported " + str(maximum))
        return values[:maximum]


def _unknown(reason):
    return {"verified": False, "status": "unavailable", "blockers": [reason],
            "coverage": "No objects fetched and no missing evidence invented"}


def _ref_oid(reader, root, ref):
    result = reader.git(root, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}",
                        allow_failure=True)
    value = os.fsdecode(result.stdout).strip()
    return value if result.returncode == 0 and _OID.fullmatch(value) else None


def _object_available(reader, root, oid):
    if not isinstance(oid, str) or not _OID.fullmatch(oid):
        return False
    return reader.git(root, "cat-file", "-e", oid + "^{commit}", allow_failure=True).returncode == 0


def _count(reader, root, left, right):
    a, b = _ref_oid(reader, root, left), _ref_oid(reader, root, right)
    if not a or not b:
        return {"available": False, "reason": "Comparison object unavailable locally; no fetch"}
    value = reader.text(root, "rev-list", "--count", a + ".." + b, "--")
    return {"available": True, "count": int(value), "basis": "locally available object graph"}


def _worktrees(reader, root):
    raw = reader.git(root, "worktree", "list", "--porcelain", "-z").stdout
    rows, row = [], {}
    for entry in raw.split(b"\0"):
        if not entry:
            if row:
                rows.append(row)
                row = {}
            continue
        key, _, value = os.fsdecode(entry).partition(" ")
        if key == "worktree":
            row["path"] = str(Path(value).resolve())
        elif key == "HEAD":
            row["oid"] = value
        elif key == "branch":
            row["ref"] = value
        elif key in ("locked", "prunable", "bare", "detached"):
            row[key] = value or True
    if row:
        rows.append(row)
    return reader.limit(rows, MAX_WORKTREES, "Worktree enumeration")


def _worktree_state(reader, path, common):
    if not Path(path).is_dir():
        return {"available": False, "reason": "Checkout path absent; native recovery/disposition must be reconciled"}
    observed = Path(reader.text(path, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()
    top = Path(reader.text(path, "rev-parse", "--show-toplevel")).resolve()
    if str(observed) != common or str(top) != str(Path(path).resolve()):
        return {"available": False, "reason": "Checkout/common repository identity mismatch"}
    result = reader.git(path, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignored=matching")
    tracked, untracked, ignored = [], [], []
    entries = result.stdout.split(b"\0")
    index = 0
    while index < len(entries):
        raw = entries[index]
        index += 1
        if not raw:
            continue
        code, name = raw[:2], os.fsdecode(raw[3:])
        (untracked if code == b"??" else ignored if code == b"!!" else tracked).append(name)
        if b"R" in code or b"C" in code:
            index += 1
    private = [name for name in PRIVATE_FILES if (Path(path) / name).exists()]
    return {"available": True, "dirty": bool(tracked),
            "tracked_changes": reader.limit(tracked, MAX_PATHS, "Tracked checkout paths"),
            "untracked": reader.limit(untracked, MAX_PATHS, "Untracked checkout paths"),
            "untracked_count": len(untracked), "ignored_count": len(ignored),
            "ignored": reader.limit(ignored, MAX_PATHS, "Ignored checkout entries"),
            "ignored_count_kind": "Git-reported entries; ignored directories may be collapsed",
            "ignored_preservation": "unknown" if ignored else "no ignored entries reported",
            "private_data_count": len(private), "known_private_paths": private,
            "metadata_only": True, "truncated": max(len(tracked), len(untracked), len(ignored)) > MAX_PATHS}


def _refs(reader, root):
    output = reader.text(root, "for-each-ref", "--count=" + str(MAX_REFS + 1),
                         "--format=%(refname)%00%(objectname)%00%(upstream)%00%(symref)",
                         "refs/heads/", "refs/remotes/")
    values = []
    for line in output.splitlines():
        fields = line.split("\0")
        if len(fields) != 4 or not _OID.fullmatch(fields[1]):
            raise AuditUnavailable("Malformed local ref metadata")
        values.append({"ref": fields[0], "oid": fields[1], "upstream": fields[2] or None,
                       "symbolic_target": fields[3] or None})
    return reader.limit(values, MAX_REFS, "Local ref enumeration")


def _endpoint(value):
    """Return a safe, credential-free literal endpoint or an honest limitation."""
    if not isinstance(value, str) or not value or any(ord(char) < 32 for char in value):
        return None, "Invalid configured endpoint"
    scp = re.fullmatch(r"([A-Za-z0-9_.-]+)@([A-Za-z0-9][A-Za-z0-9.-]*):([A-Za-z0-9_./-]+)", value)
    if scp:
        if not _ssh_command():
            return None, "Safe noninteractive SSH is unavailable"
        return {"url": value, "transport": "ssh", "repository": _github_repository(value)}, None
    if value.startswith("/"):
        return {"url": str(Path(value).resolve()), "transport": "file", "repository": None}, None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None, "Malformed configured endpoint; value omitted"
    if parsed.password is not None or (parsed.username is not None and parsed.scheme != "ssh"):
        return None, "Embedded endpoint credentials are unsupported and omitted"
    if parsed.query or parsed.fragment:
        return None, "Endpoint queries/fragments are unsupported and omitted"
    if parsed.scheme == "https" and parsed.hostname and parsed.path:
        return {"url": value, "transport": "https", "repository": _github_repository(value)}, None
    if parsed.scheme == "file" and parsed.netloc in ("", "localhost") and parsed.path.startswith("/"):
        decoded = unquote(parsed.path)
        if any(ord(char) < 32 for char in decoded):
            return None, "Invalid encoded file endpoint; value omitted"
        return {"url": str(Path(decoded).resolve()), "transport": "file", "repository": None}, None
    if (parsed.scheme == "ssh" and parsed.hostname and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", parsed.hostname)
            and (parsed.username is None or re.fullmatch(r"[A-Za-z0-9_.-]+", parsed.username))
            and re.fullmatch(r"/[A-Za-z0-9_./-]+", parsed.path or "")):
        if not _ssh_command():
            return None, "Safe noninteractive SSH is unavailable"
        return {"url": value, "transport": "ssh", "repository": _github_repository(value)}, None
    return None, "Unsupported/custom remote transport; no helper was executed"


def _github_repository(value):
    scp = re.fullmatch(r"git@github\.com:([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?", value)
    if scp:
        return scp[1]
    parsed = urlsplit(value)
    if parsed.hostname == "github.com" and parsed.scheme in ("https", "ssh"):
        path = parsed.path.lstrip("/")
        if path.endswith(".git"):
            path = path[:-4]
        return path if _REPOSITORY.fullmatch(path) else None
    return None


def _remotes(reader, root, enabled):
    # Configuration is read, never applied. Detect rewrites before transport.
    names_result = reader.git(root, "config", "--includes", "--get-regexp", r"^remote\..*\.url$", allow_failure=True)
    if names_result.returncode not in (0, 1):
        raise AuditUnavailable("Effective remote configuration is unavailable")
    names = os.fsdecode(names_result.stdout).rstrip("\n")
    aliases = []
    for line in names.splitlines():
        key, _, _value = line.partition(" ")
        if key.startswith("remote.") and key.endswith(".url"):
            aliases.append(key[len("remote."):-len(".url")])
    dangerous_result = reader.git(root, "config", "--includes", "--get-regexp",
                                  r"^(url\..*\.(insteadof|pushinsteadof)|remote\..*\.(uploadpack|receivepack|proxy)|core\.gitproxy)$",
                                  allow_failure=True)
    if dangerous_result.returncode not in (0, 1):
        raise AuditUnavailable("Effective transport configuration is unavailable")
    dangerous = os.fsdecode(dangerous_result.stdout).rstrip("\n")
    rows = []
    for alias in sorted(set(aliases)):
        for role, extra in (("fetch", []), ("push", ["--push"])):
            try:
                urls = reader.text(root, "remote", "get-url", *extra, "--all", "--", alias).splitlines()
            except AuditUnavailable as error:
                rows.append({"remote": alias, "roles": [role], "endpoint": None,
                             "repository": None, "transport": "unknown", "available": False,
                             "heads": {}, "observed_at": None, "reason": str(error)})
                continue
            if not urls:
                rows.append({"remote": alias, "roles": [role], "endpoint": None,
                             "repository": None, "transport": "unknown", "available": False,
                             "heads": {}, "observed_at": None, "reason": "Configured endpoint is empty"})
            for value in urls:
                safe, reason = _endpoint(value)
                row = {"remote": alias, "roles": [role], "endpoint": safe["url"] if safe else None,
                       "repository": safe.get("repository") if safe else None,
                       "transport": safe.get("transport") if safe else "unsupported", "available": False,
                       "heads": {}, "observed_at": None}
                existing = next((item for item in rows if safe is not None and item["remote"] == alias and item["endpoint"] == row["endpoint"]
                                 and item["transport"] == row["transport"]), None)
                if existing:
                    existing["roles"].append(role)
                    continue
                if reason:
                    row["reason"] = reason
                elif dangerous.strip():
                    row["reason"] = "Configured transport/URL helper override is outside safe audit coverage"
                elif not enabled:
                    row["reason"] = "Offline audit: only cached remote metadata is available"
                elif len(rows) >= MAX_REMOTE_ENDPOINTS:
                    row["reason"] = "Remote endpoint observation limit reached"
                    reader.limits.append("Remote endpoint observation truncated")
                else:
                    try:
                        observed = reader.git(root, "ls-remote", "--heads", "--upload-pack=git-upload-pack", "--", safe["url"])
                        for line in os.fsdecode(observed.stdout).splitlines():
                            fields = line.split("\t")
                            if len(fields) != 2 or not _OID.fullmatch(fields[0]) or not fields[1].startswith("refs/heads/"):
                                raise AuditUnavailable("Malformed advertised remote head")
                            row["heads"][fields[1]] = fields[0]
                        if len(row["heads"]) > MAX_REFS:
                            row["heads"] = dict(sorted(row["heads"].items())[:MAX_REFS])
                            row["truncated"] = True
                            reader.limits.append("Advertised remote heads truncated")
                        row.update(available=True, observed_at=_now())
                    except AuditUnavailable as error:
                        row["reason"] = str(error)
                rows.append(row)
    return rows


def _policy(reader, root, repository_id, branch_names, supplied, enabled):
    try:
        if supplied is not None:
            value = supplied(root, repository_id) if callable(supplied) else supplied
        elif enabled:
            code = ("import sys,json;sys.path.insert(0,sys.argv[1]);from checkout_guard import resolve_policy;"
                    "print(json.dumps(resolve_policy(sys.argv[2],sys.argv[3],branch_names=json.loads(sys.argv[4]))))")
            result = reader.run([sys.executable, "-I", "-B", "-c", code, str(Path(__file__).resolve().parent),
                                 str(root), repository_id, json.dumps(sorted(branch_names))],
                                "provider policy", seconds=45)
            value = json.loads(result.stdout)
        else:
            raise AuditUnavailable("Offline audit has no fresh authoritative protection observation")
        if (not isinstance(value, dict) or value.get("repository", "").lower() != repository_id.lower()
                or not isinstance(value.get("default_branch"), str) or not value.get("default_branch")
                or not isinstance(value.get("protected_branches"), list)
                or any(not isinstance(name, str) for name in value["protected_branches"])):
            raise AuditUnavailable("Malformed authoritative protection observation")
        return dict(value, available=True)
    except (AuditUnavailable, ValueError, TypeError, OSError):
        return {"available": False, "reason": "Authoritative protection unavailable within the read-only boundary"}


def _minimal_owner(record, identity_match=None):
    result = {"flight": record["flight"], "issues": record["issues"], "pull_requests": record["pull_requests"],
            "client": record["client"], "lifecycle": record["lifecycle"]["state"],
            "identity_match": identity_match, "source": "explicit repository-qualified Registry association"}
    exception = record.get("cleanup", {}).get("owner_accepted_disposition")
    if isinstance(exception, dict):
        result["owner_accepted_disposition"] = {key: exception.get(key) for key in
                                               ("reference", "disposition", "cleanup_complete")}
        result["owner_accepted_disposition"]["normal_policy_binding"] = False
    return result


def _owners(records, *, path=None, ref=None):
    result = []
    for record in records:
        for item in [record["checkout"], *record["children"]]:
            matches = item["path"] == path if path is not None else (
                ref is not None and item["branch"] is not None and ref == "refs/heads/" + item["branch"])
            if matches:
                result.append(record)
                break
        else:
            # Explicit accepted artifact identities retain ownership after
            # session release. An uncertain native name/ref is a reservation,
            # not proof that a newly observed physical artifact belongs to it.
            if any((path is not None and row["kind"] == "worktree" and row["identity"] == path)
                   or (ref is not None and row["kind"] == "local_branch" and row["identity"] == ref)
                   for row in retained_artifacts(record)):
                result.append(record)
    return result


def _provider_delivery(reader, root, repository_id, record, remotes, enabled):
    if not _REPOSITORY.fullmatch(repository_id) or not enabled or not any(row.get("repository", "").lower() == repository_id.lower()
                              for row in remotes if row.get("repository")):
        raise AuditUnavailable("Fresh provider delivery metadata is unavailable")
    base = record.get("checkout_guard", {}).get("base", {}).get("commit")
    if not isinstance(base, str) or not _OID.fullmatch(base):
        raise AuditUnavailable("Pinned source base is unavailable")
    for number in record["pull_requests"]:
        if type(number) is not int or number <= 0:
            continue
        response = reader.run(["gh", "api", "repos/" + repository_id + "/pulls/" + str(number),
                               "--method", "GET", "--hostname", "github.com",
                               "--header", "Accept: application/vnd.github+json"], "provider PR metadata")
        value = json.loads(response.stdout)
        if not isinstance(value, dict):
            raise AuditUnavailable("Malformed provider PR metadata")
        head_data = value.get("head") or {}
        base_data = value.get("base") or {}
        if not isinstance(head_data, dict) or not isinstance(base_data, dict):
            raise AuditUnavailable("Malformed provider head/base metadata")
        base_repo = base_data.get("repo") or {}
        head_repo = head_data.get("repo") or {}
        if not all(isinstance(item, dict) for item in (head_data, base_data, base_repo, head_repo)):
            raise AuditUnavailable("Malformed provider repository metadata")
        head = head_data.get("sha")
        target = base_data.get("ref")
        repository = base_repo.get("full_name", "")
        expected = record.get("delivery", {}).get("head")
        if (value.get("merged") is True and repository.lower() == repository_id.lower()
                and head_repo.get("full_name", "").lower() == repository_id.lower()
                and isinstance(head, str) and _OID.fullmatch(head)
                and head == expected and isinstance(target, str)
                and _OID.fullmatch(value.get("merge_commit_sha") or "")):
            return {"repository": repository_id, "merged": True, "source_base": base,
                    "head": head, "merge_commit": value["merge_commit_sha"], "target": target,
                    "pull_request": number, "head_ref": head_data.get("ref"),
                    "head_repository": head_repo.get("full_name"),
                    "method": "provider-confirmed integration", "source": "fresh bounded GitHub GET"}
    raise AuditUnavailable("No actual merged PR matches the recorded delivered source head")


def _target(reader, root, target, remotes):
    if not target:
        return {"ref": None, "oid": None, "freshness": "unavailable", "reason": "No target recorded or observed"}
    if target.startswith("refs/remotes/"):
        pieces = target[len("refs/remotes/"):].split("/", 1)
        if len(pieces) == 2:
            remote, branch = pieces
            endpoints = [row for row in remotes if row["remote"] == remote and "fetch" in row["roles"]]
            if len(endpoints) > 1:
                return {"ref": target, "oid": None, "freshness": "unavailable",
                        "reason": "Multiple fetch endpoints need explicit target identity reconciliation"}
            endpoint = endpoints[0] if endpoints else None
            if endpoint and endpoint["available"]:
                oid = endpoint["heads"].get("refs/heads/" + branch)
                return {"ref": target, "oid": oid, "freshness": "actual-remote",
                        "reason": None if oid else "Actual remote target is absent"}
            return {"ref": target, "oid": _ref_oid(reader, root, target), "freshness": "cached",
                    "reason": "Fresh remote target unavailable; cached ref is not current remote proof"}
    return {"ref": target, "oid": _ref_oid(reader, root, target), "freshness": "local-current"}


def _integration(reader, root, oid, record, target, delivery):
    if not _object_available(reader, root, oid):
        return _unknown("Source object is absent locally; audit does not fetch")
    if not record or not delivery:
        return _unknown("No uniquely associated, fresh verified delivery metadata")
    if not target.get("oid") or target.get("freshness") == "cached":
        return _unknown(target.get("reason") or "Actual target object unavailable")
    try:
        # Isolate inherited Git configuration/environment without changing the
        # caller's process state. The shared function is a read-only assessor.
        code = ("import sys,json;sys.path.insert(0,sys.argv[1]);from flight_lifecycle import integration_status;"
                "print(json.dumps(integration_status(sys.argv[2],sys.argv[3],sys.argv[4],"
                "delivery=json.loads(sys.argv[5]),remote_observation=json.loads(sys.argv[6]))))")
        response = reader.run([sys.executable, "-I", "-B", "-c", code, str(Path(__file__).resolve().parent),
                               str(root), oid, target["ref"], json.dumps(delivery),
                               json.dumps({"available": True, "target_tip": target["oid"]})],
                              "integration metadata", seconds=30)
        value = json.loads(response.stdout)
        if not isinstance(value, dict) or not isinstance(value.get("verified"), bool):
            raise AuditUnavailable("Shared integration result malformed")
        return value
    except (AuditUnavailable, ValueError, TypeError):
        return _unknown("Shared integration assessment unavailable within read-only coverage")


def _protection(branch, policy, configured):
    if branch and branch in configured:
        return {"status": "protected", "source": "confirmed recorded configuration/default/target"}
    if policy.get("available"):
        return {"status": "protected" if branch in policy["protected_branches"] else "unprotected",
                "source": policy.get("source", "supplied protection observation")}
    return {"status": "unknown", "source": "authoritative protection unavailable"}


def _activity(owners, observations, path):
    known = [row for row in owners if row["lifecycle"]["state"] != "closed"]
    value = observations.get(path) if isinstance(observations, dict) else None
    native = "unknown"
    if (isinstance(value, dict) and value.get("available") is True
            and type(value.get("active")) is bool and value.get("source") and value.get("observed_at")):
        try:
            age = time.time() - datetime.fromisoformat(value["observed_at"].replace("Z", "+00:00")).timestamp()
            if -5 <= age <= AUDIT_SECONDS:
                native = "active" if value["active"] else "inactive"
        except (AttributeError, TypeError, ValueError):
            pass
    return {"recorded_unfinished_owner": bool(known), "native": native,
            "source": value.get("source") if isinstance(value, dict) else "Native client activity unavailable"}


def _recommendation(row):
    state, active, protected = row["state"], row["active"], row["protected"]
    identity = row["identity"]
    label = identity.get("path") or identity.get("ref") or row["id"]
    prerequisites = ["A separate explicit grant naming this exact artifact and repository",
                     "Fresh ownership, identity, protection, integration and checkout-state revalidation"]
    if protected["status"] == "protected" or row.get("repository_main"):
        classification, reason, action = "preserve", "Repository main/default/protected/shared artifact", "Preserve " + label
    elif row.get("retained_obligations"):
        classification, reason = "preserve", "Retained ownership or unresolved native operation remains recorded"
        action = "; ".join(dict.fromkeys(item["next_action"] for item in row["retained_obligations"]))
    elif active["recorded_unfinished_owner"] or active["native"] == "active" or row.get("checked_out_in"):
        classification, reason, action = "preserve", "Unfinished owner, active client or checked-out branch", "Resume or coordinate the recorded owner of " + label
    elif state.get("locked") or state.get("dirty") or state.get("untracked_count"):
        classification, reason, action = "preserve", "Locked, dirty or untracked work must be preserved", "Preserve unfinished work at " + label
    elif state.get("ignored_count") or state.get("private_data_count"):
        classification, reason, action = "preserve", "Ignored/private data lacks established preservation proof", "Investigate private-data preservation before any action on " + label
    elif not row["owners"] or len(row["owners"]) != 1:
        classification, reason, action = "investigate", "Ownership is unknown or ambiguous; naming supplies no grant", "Identify the owner and intended disposition of " + label
    elif not state.get("available", True) or state.get("truncated") or protected["status"] == "unknown":
        classification, reason, action = "investigate", "Required state/protection coverage is unavailable", "Resolve the reported observation limits for " + label
    elif active["native"] == "unknown" and row["kind"] in ("worktree", "recorded_checkout"):
        classification, reason, action = "investigate", "Native session activity is unavailable", "Confirm native inactivity and preservation for " + label
    elif row["kind"] == "remote_tracking_ref":
        classification, reason, action = "investigate", "Cached tracking metadata is not an actual remote branch", "Reconcile cached versus actual remote observations for " + label
    elif not row["integration"].get("verified"):
        classification, reason, action = "investigate", "Integration/preservation is not established", "Resolve integration evidence for " + label
    else:
        classification, reason, action = "cleanup_candidate", "Known closed ownership and integration; not an execution grant", "Consider separately authorized cleanup of " + label
    return {"classification": classification, "action": action, "reason": reason,
            "prerequisites": prerequisites, "cleanup_authorized": False}


def audit(checkout, registry, repository_id, remote=True, policy=None, client_observations=None):
    """Report current metadata and recommendations without granting or doing cleanup."""
    if not isinstance(repository_id, str) or not repository_id.strip():
        raise AuditUnavailable("Explicit repository identity is required")
    root = Path(checkout).resolve(strict=True)
    reader = _Reader()
    common = str(Path(reader.text(root, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve())
    top = Path(reader.text(root, "rev-parse", "--show-toplevel")).resolve()
    if top != root:
        raise AuditUnavailable("Audit checkout must be the actual repository root")
    registry_reader = None
    try:
        registry_reader = registry if isinstance(registry, Registry) else Registry(Path(registry))
        saved = registry_reader.read()
        records = [row for row in saved["records"] if row["repository"]["id"] == repository_id
                   and row["repository"]["git_common_dir"] == common]
        foreign = [row for row in saved["records"] if row["repository"]["id"] == repository_id
                   and row["repository"]["git_common_dir"] != common]
        association_coverage = {"status": "observed", "records": len(records), "foreign_clone_records": len(foreign)}
    except (OSError, ValueError):
        saved, records, foreign = {"revision": None, "records": []}, [], []
        association_coverage = {"status": "unavailable", "reason": "Private Registry unavailable; no ownership inferred"}
    worktrees = _worktrees(reader, root)
    refs = _refs(reader, root)
    try:
        remotes = _remotes(reader, root, remote)
    except (AuditUnavailable, OSError, ValueError):
        reader.limits.append("Remote configuration/endpoint collection unavailable within bounded coverage")
        remotes = []
    names = {row["ref"][len("refs/heads/"):] for row in refs if row["ref"].startswith("refs/heads/")}
    names.update(ref[len("refs/heads/"):] for row in remotes for ref in row["heads"])
    protection = _policy(reader, root, repository_id, names, policy, remote)
    configured = set()
    for record in records:
        values = record["configuration"]["values"]
        configured.update(values.get("protected_branches", []))
        if values.get("default_branch"):
            configured.add(values["default_branch"])
    if protection.get("available"):
        configured.add(protection["default_branch"])
    deliveries = {}
    for record in records:
        try:
            deliveries[record["flight"]] = _provider_delivery(reader, root, repository_id, record, remotes, remote)
        except (AuditUnavailable, ValueError, TypeError):
            deliveries[record["flight"]] = None
    artifacts, states, integration_cache = [], {}, {}
    omitted_artifacts = [0]
    checked = {}
    for row in worktrees:
        if row.get("ref"):
            checked.setdefault(row["ref"], []).append(row["path"])
    default_target = "refs/heads/" + protection["default_branch"] if protection.get("available") else None

    def make(kind, identity, matching, state, *, branch=None, checked_paths=None, primary=False,
             origin_policy=True, retained_rows=None):
        if len(artifacts) >= MAX_ARTIFACTS:
            omitted_artifacts[0] += 1
            return None
        target_ref = matching[0]["delivery"].get("target") if len(matching) == 1 else default_target
        if not target_ref and len(matching) == 1:
            value = matching[0]["configuration"]["values"].get("default_branch")
            target_ref = "refs/heads/" + value if value else default_target
        try:
            target = _target(reader, root, target_ref, remotes)
        except AuditUnavailable as error:
            target = {"ref": target_ref, "oid": None, "freshness": "unavailable", "reason": str(error)}
        owner = matching[0] if len(matching) == 1 else None
        delivered = deliveries.get(owner["flight"]) if owner else None
        oid = identity.get("oid")
        key = (oid, owner["flight"] if owner else None, target.get("oid"), target.get("freshness"))
        if key not in integration_cache:
            try:
                integration_cache[key] = _integration(reader, root, oid, owner, target, delivered)
            except AuditUnavailable as error:
                integration_cache[key] = _unknown(str(error))
        indicator = {"unmerged": {"available": False, "reason": "No usable local target/source"},
                     "unpushed": {"available": False, "reason": "No usable upstream comparison"}}
        if oid and target_ref:
            try:
                comparison = target.get("oid") if target.get("freshness") != "cached" else target_ref
                if comparison:
                    indicator["unmerged"] = dict(_count(reader, root, comparison, oid), freshness=target.get("freshness"))
            except (AuditUnavailable, ValueError):
                pass
        upstream = state.get("upstream")
        if oid and upstream:
            try:
                upstream_state = _target(reader, root, upstream, remotes)
                comparison = upstream_state.get("oid") if upstream_state.get("freshness") != "cached" else upstream
                if comparison:
                    indicator["unpushed"] = dict(_count(reader, root, comparison, oid), freshness=upstream_state.get("freshness"))
            except (AuditUnavailable, ValueError):
                pass
        row = {"id": ":".join(str(item) for item in [kind, identity.get("remote"), identity.get("endpoint"),
                                                   identity.get("path") or identity.get("ref") or identity.get("operation") or identity.get("artifact_id")] if item),
               "kind": kind, "identity": identity,
               "owners": [_minimal_owner(item, oid in [entry["commit"] for entry in [item["checkout"], *item["children"]]] + [item["delivery"].get("head")]) for item in matching],
               "state": state, "checked_out_in": checked_paths or [], "repository_main": primary,
               "active": _activity(matching, client_observations, identity.get("path")),
               "protected": _protection(branch, protection if origin_policy else {}, configured if origin_policy else set()),
               "target": target, "integration": integration_cache[key], "branch_indicators": indicator,
               "cleanup_authorized": False}
        obligations = list(retained_rows) if retained_rows is not None else []
        if retained_rows is None:
            for item in records:
                for obligation in reservation_conflicts(item, path=identity.get("path"), ref=identity.get("ref"),
                                                        endpoint=identity.get("endpoint")):
                    if obligation["kind"] == "remote_branch" and (kind != "remote_branch" or not origin_policy):
                        continue
                    if kind == "remote_branch" and obligation["kind"] not in ("remote_branch", "native_operation"):
                        continue
                    obligations.append(obligation)
        if obligations:
            row["retained_obligations"] = obligations
        row["recorded_cleanup_scopes"] = [{"flight": item["flight"], "artifact_id": artifact.get("id"),
                                            "authority": "Recorded scope only; not ownership or a current execution grant"}
                                           for item in records for artifact in item.get("cleanup", {}).get("inventory", [])
                                           if artifact.get("kind") == kind and artifact.get("identity") == (identity.get("path") or identity.get("ref"))
                                           and (kind != "remote_branch" or artifact.get("remote") == identity.get("remote"))]
        row["recommendation"] = _recommendation(row)
        artifacts.append(row)
        return row

    for number, worktree in enumerate(worktrees):
        path = worktree["path"]
        if worktree.get("bare"):
            state = {"available": True, "bare": True}
        else:
            try:
                state = _worktree_state(reader, path, common)
            except AuditUnavailable as error:
                state = {"available": False, "reason": str(error)}
        state.update(locked=worktree.get("locked", False), prunable=worktree.get("prunable", False))
        states[path] = state
        branch = worktree.get("ref", "").removeprefix("refs/heads/") or None
        make("worktree", {"path": path, "ref": worktree.get("ref"), "oid": worktree.get("oid")},
             _owners(records, path=path), state, branch=branch, primary=number == 0)
    present = {row["path"] for row in worktrees}
    for record in records + foreign:
        for item in [record["checkout"], *record["children"]]:
            if item["path"] not in present:
                present.add(item["path"])
                make("recorded_checkout", {"path": item["path"], "ref": "refs/heads/" + item["branch"] if item["branch"] else None,
                                          "oid": item["commit"]}, [record],
                     {"available": False, "reason": "Recorded checkout is absent from this clone's native worktree inventory"},
                     branch=item["branch"])
    for ref in refs:
        if ref["ref"].startswith("refs/heads/"):
            branch = ref["ref"][len("refs/heads/"):]
            paths = checked.get(ref["ref"], [])
            state = {"available": True, "upstream": ref["upstream"], "object_available": True}
            state["checkout_observation_ids"] = ["worktree:" + path for path in paths]
            # Uncommitted/ignored work belongs to its checkout, never the ref.
            make("local_branch", {"ref": ref["ref"], "oid": ref["oid"]}, _owners(records, ref=ref["ref"]),
                 state, branch=branch, checked_paths=paths)
        else:
            suffix = ref["ref"][len("refs/remotes/"):]
            alias, _, branch = suffix.partition("/")
            endpoint = next((row for row in remotes if row["remote"] == alias and "fetch" in row["roles"]), None)
            advertised = endpoint["heads"].get("refs/heads/" + branch) if endpoint and endpoint["available"] else None
            make("remote_tracking_ref", {"ref": ref["ref"], "oid": ref["oid"], "remote": alias}, [],
                 {"available": True, "cached": True, "upstream": None, "symbolic_target": ref["symbolic_target"],
                  "advertised_oid": advertised, "actual_remote_available": bool(endpoint and endpoint["available"]),
                  "stale": advertised != ref["oid"] if endpoint and endpoint["available"] and not ref["symbolic_target"] else None}, branch=branch)
    for endpoint in remotes:
        for ref, oid in endpoint["heads"].items():
            if len(artifacts) >= MAX_ARTIFACTS:
                omitted_artifacts[0] += 1
                continue
            matching = []
            for record in records:
                delivery = deliveries.get(record["flight"])
                if (delivery and delivery.get("head_ref") == ref[len("refs/heads/"):]
                        and (delivery.get("head_repository") or "").lower() == (endpoint.get("repository") or "").lower()):
                    matching.append(record)
            if (endpoint.get("repository") or "").lower() == repository_id.lower():
                for record in records:
                    if record in matching:
                        continue
                    if any(row["kind"] == "remote_branch" and row["identity"] == ref
                           for row in retained_artifacts(record)):
                        matching.append(record)
            try:
                available = _object_available(reader, root, oid)
            except AuditUnavailable:
                available = False
            make("remote_branch", {"remote": endpoint["remote"], "endpoint": endpoint["endpoint"],
                                   "roles": endpoint["roles"], "ref": ref, "oid": oid}, matching,
                 {"available": True, "object_available": available, "fresh": True},
                 branch=ref[len("refs/heads/"):],
                 origin_policy=endpoint.get("repository", "").lower() == repository_id.lower()
                 if endpoint.get("repository") else False)
    # Keep every retained obligation visible, including operations whose actual
    # checkout identity/existence is unknown or absent from this observation.
    represented = {(row["flight"], row.get("id")) for artifact in artifacts
                   for row in artifact.get("retained_obligations", [])}
    for record in records + foreign:
        for obligation in retained_artifacts(record):
            if obligation["kind"] != "native_operation" and (record["flight"], obligation.get("id")) in represented:
                continue
            kind = obligation["kind"]
            identity = {"artifact_id": obligation.get("id"), "recorded_kind": kind,
                        "recorded_identity": obligation["identity"]}
            if kind == "native_operation":
                identity.update(operation=obligation["identity"], requested_name=obligation.get("requested_name"))
            elif kind == "worktree":
                identity["path"] = obligation["identity"]
            else:
                identity.update(ref=obligation["identity"], remote=obligation.get("remote"),
                                endpoint=obligation.get("endpoint"))
            make("native_operation" if kind == "native_operation" else "retained_artifact", identity, [record],
                 {"available": False, "existence": "unknown", "operation_state": obligation.get("operation_state"),
                  "reason": "Retained obligation has no authoritative physical artifact observation in this bounded inventory"},
                 retained_rows=[obligation])
    try:
        after = registry_reader.read()["revision"] if registry_reader is not None else None
    except (OSError, ValueError):
        after = None
    if after != saved["revision"]:
        reader.limits.append("Registry changed during audit; ownership observations need fresh reconciliation")
        for row in artifacts:
            row["recommendation"] = {"classification": "investigate", "action": "Re-audit current ownership for " + row["id"],
                                     "reason": "Registry observation changed", "prerequisites": ["Fresh separate authorized action"],
                                     "cleanup_authorized": False}
    if omitted_artifacts[0]:
        reader.limits.append("Artifact report truncated: " + str(omitted_artifacts[0]) + " additional observations omitted")
    return {"schema": 1, "status": "reported", "read_only": True, "cleanup_authorized": False,
            "repository": {"id": repository_id, "git_common_dir": common}, "registry_revision": saved["revision"],
            "observed_at": _now(), "privacy": "Local paths and associations: retain report privately; file contents and credentials omitted",
            "coverage": {"local_branches": {"count": sum(row["kind"] == "local_branch" for row in artifacts)},
                         "worktrees": {"count": len(worktrees)}, "associations": association_coverage,
                         "remotes": [{key: value for key, value in row.items() if key != "heads"} | {"head_count": len(row["heads"])} for row in remotes],
                         "policy": {key: value for key, value in protection.items() if key in ("available", "reason", "source", "default_branch")},
                         "client": "Recorded associations only; native activity unknown unless an available sourced observation falls within this audit window",
                         "limits": reader.limits, "truncated": any("truncat" in value.lower() for value in reader.limits), "commands": reader.commands,
                         "command_timeout_seconds": COMMAND_SECONDS, "operation_timeout_seconds": AUDIT_SECONDS,
                         "artifact_limit": MAX_ARTIFACTS, "omitted_artifacts": omitted_artifacts[0],
                         "remote_tracking": "Cached refs are reported separately and never substituted for actual remote observations",
                         "integration": "Local objects and fresh recorded-PR provider metadata only; missing objects remain unavailable",
                         "git_configuration": "Global/system Git configuration ignored; safe explicit endpoints only. Configured executable/URL helpers are not invoked"},
            "artifacts": artifacts,
            "retention_policies": [{"flight": record["flight"],
                                    "policy": record.get("cleanup", {}).get("registration", {}).get("retention_policy")}
                                   for record in records + foreign
                                   if record.get("cleanup", {}).get("registration", {}).get("retention_policy")],
            "recommendations": [{"artifact_id": row["id"], **row["recommendation"]} for row in artifacts]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, default=Path.cwd())
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--offline", action="store_true", help="Report cached remote limits without network queries")
    args = parser.parse_args(argv)
    try:
        result = audit(args.checkout, args.registry, args.repository, remote=not args.offline)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"schema": 1, "status": "unavailable", "read_only": True,
                          "cleanup_authorized": False, "reason": str(error)}))
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
