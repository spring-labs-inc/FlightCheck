"""Private flight associations; records are evidence of ownership, never inferred grants.

This module records identities. It neither selects/enforces checkouts nor performs
cleanup, provider synchronization, native-client recovery, or delivery.
"""

import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile


class AssociationError(ValueError):
    pass


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def text(value, name):
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise AssociationError(name + " must be nonempty text")
    return value


def no_links(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink():
            raise AssociationError("Symlink association path is unsupported: " + str(part))
    return path


def absolute(value, name):
    text(value, name)
    path = Path(value)
    if not path.is_absolute():
        raise AssociationError(name + " must be absolute")
    return str(path.resolve())


def repository_identity(checkout, repository_id):
    """Qualify provider identity with this clone's actual common Git directory."""
    text(repository_id, "repository id")
    root = Path(checkout).resolve(strict=True)
    result = subprocess.run(["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(root),
                             "rev-parse", "--git-common-dir"], capture_output=True, text=True)
    if result.returncode:
        raise AssociationError("Cannot identify repository: " + result.stderr.strip())
    common = Path(result.stdout.strip())
    if not common.is_absolute():
        common = root / common
    return {"id": repository_id, "git_common_dir": str(common.resolve(strict=True))}


def _checkout(value):
    if not isinstance(value, dict):
        raise AssociationError("checkout must be an object")
    path = absolute(value.get("path"), "checkout.path")
    if value.get("kind") not in ("preserved-existing", "disposable-temporary"):
        raise AssociationError("checkout.kind must distinguish preserved and disposable")
    if value.get("management") not in ("native", "manual"):
        raise AssociationError("checkout.management must be native or manual")
    branch = value.get("branch")
    if branch is not None:
        text(branch, "checkout.branch")
    if not isinstance(value.get("commit"), str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value["commit"]):
        raise AssociationError("checkout.commit must identify the recorded commit")
    return dict(value, path=path)


def _snapshot(value):
    if (not isinstance(value, dict) or not isinstance(value.get("revision"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", value["revision"])
            or not isinstance(value.get("values"), dict)):
        raise AssociationError("configuration must contain a SHA-256 revision and values")
    policy = value["values"].get("checkout_policy", {"mode": "native-choice"})
    if not isinstance(policy, dict) or policy.get("mode") not in ("native-choice", "worktree-required"):
        raise AssociationError("configuration.checkout_policy is unsupported")
    return copy.deepcopy(value)


def validate_record(record):
    """Validate recorded facts, without claiming current checkout verification."""
    if not isinstance(record, dict) or record.get("schema") != 1:
        raise AssociationError("Expected flight association schema 1")
    value = copy.deepcopy(record)
    for name in ("flight", "task", "card"):
        text(value.get(name), name)
    repository = value.get("repository")
    if not isinstance(repository, dict):
        raise AssociationError("repository must be an explicit identity object")
    text(repository.get("id"), "repository.id")
    repository["git_common_dir"] = absolute(repository.get("git_common_dir"), "repository.git_common_dir")
    for name in ("issues", "pull_requests"):
        numbers = value.get(name)
        if (not isinstance(numbers, list) or any(type(n) is not int or n <= 0 for n in numbers)
                or len(set(numbers)) != len(numbers)):
            raise AssociationError(name + " must be unique positive numbers qualified by repository")
    client = value.get("client")
    if not isinstance(client, dict) or not isinstance(client.get("sessions"), list):
        raise AssociationError("client must identify its name and sessions")
    text(client.get("name"), "client.name")
    for session in client["sessions"]:
        text(session, "client session")
    if not isinstance(value.get("children"), list):
        raise AssociationError("children must be a checkout array")
    value["checkout"] = _checkout(value.get("checkout"))
    value["children"] = [_checkout(child) for child in value["children"]]
    paths = [child["path"] for child in [value["checkout"], *value["children"]]]
    if len(set(paths)) != len(paths):
        raise AssociationError("A checkout cannot be both main and child or appear twice")
    value["configuration"] = _snapshot(value.get("configuration"))
    if not isinstance(value.get("grants"), dict) or not isinstance(value.get("delivery"), dict):
        raise AssociationError("grants and delivery must be separately scoped objects")
    if value["delivery"].get("target") is not None:
        text(value["delivery"]["target"], "delivery.target")
    lifecycle = value.get("lifecycle")
    if (not isinstance(lifecycle, dict) or lifecycle.get("state") not in
            ("active", "paused", "review", "merged", "closed")):
        raise AssociationError("lifecycle.state must be active, paused, review, merged or closed")
    text(lifecycle.get("disposition"), "lifecycle.disposition")
    encoded(value)  # Reject non-JSON or nonfinite input before persistence.
    return value


def reconfigure(record, configuration, reference):
    """Explicitly bind new defaults; return required revalidation, never a grant."""
    value = validate_record(record)
    text(reference, "reconfiguration reference")
    new = _snapshot(configuration)
    old = value["configuration"]
    changed = sorted(key for key in old["values"].keys() | new["values"].keys()
                     if old["values"].get(key) != new["values"].get(key))
    affected = []
    if set(changed) & {"checkout_policy", "default_branch", "protected_branches", "branch_prefix", "git_fallback"}:
        affected.append("checkout")
    if set(changed) & {"checks", "python", "observed_python", "required_runtimes", "preview"}:
        affected.append("checks")
    if changed:
        affected.append("evidence")
    value.setdefault("configuration_history", []).append(copy.deepcopy(old))
    value["configuration"] = new
    value["reconfiguration"] = {"reference": reference, "from_revision": old["revision"],
                                "to_revision": new["revision"], "changed_fields": changed,
                                "required_revalidation": affected}
    return value


class Registry:
    """One cooperating lock and atomic JSON publication in private external storage."""

    def __init__(self, directory):
        if not Path(directory).is_absolute():
            raise AssociationError("Association directory must be absolute")
        self.directory = no_links(directory)
        self.path = self.directory / "associations.json"

    def _private(self, create=False):
        no_links(self.directory)
        if create:
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.exists():
            info = self.directory.stat()
            if not self.directory.is_dir() or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
                raise AssociationError("Association directory must be owner-only (0700)")
        return self.directory

    def read(self):
        """Read-only: an absent registry stays absent."""
        self._private()
        path = no_links(self.path)
        if not path.exists():
            return {"revision": None, "records": []}
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise AssociationError("Association file must be owner-only (0600)")
        raw = path.read_bytes()
        value = json.loads(raw)
        if value.get("schema") != 1 or not isinstance(value.get("records"), list):
            raise AssociationError("Unsupported association registry")
        records = [validate_record(record) for record in value["records"]]
        self._unique(records)
        return {"revision": digest(raw), "records": records}

    @staticmethod
    def _unique(records):
        flights, owners = set(), {}
        for record in records:
            if record["flight"] in flights:
                raise AssociationError("Duplicate flight identity")
            flights.add(record["flight"])
            if record["lifecycle"]["state"] == "closed":
                continue
            for checkout in [record["checkout"], *record["children"]]:
                path = checkout["path"]
                if path in owners:
                    raise AssociationError("Checkout already owned by unfinished flight " + owners[path])
                owners[path] = record["flight"]

    def save(self, record, expected_revision=None):
        record = validate_record(record)
        for checkout in [record["checkout"], *record["children"]]:
            root = Path(checkout["path"])
            if self.directory == root or root in self.directory.parents:
                raise AssociationError("Keep associations outside execution checkouts")
        self._private(create=True)
        lock_path = no_links(self.directory / "lock")
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            previous = self.read()
            if previous["revision"] != expected_revision:
                raise AssociationError("Stale association revision; reread before updating")
            records = previous["records"]
            old = next((item for item in records if item["flight"] == record["flight"]), None)
            if old and old["repository"] != record["repository"]:
                raise AssociationError("A flight cannot silently change repository identity")
            if old and record.get("configuration_history", [])[:len(old.get("configuration_history", []))] != old.get("configuration_history", []):
                raise AssociationError("Preserve the prior configuration history")
            if old and old["configuration"] != record["configuration"]:
                decision = record.get("reconfiguration", {})
                reference = decision.get("reference")
                text(reference, "explicit reconfiguration reference")
                expected = reconfigure(old, record["configuration"], reference)
                if (decision != expected["reconfiguration"]
                        or record.get("configuration_history") != expected["configuration_history"]
                        or record["grants"] != old["grants"]):
                    raise AssociationError("Configuration changes require explicit reconfigure history and unchanged grants")
            elif old and record["grants"] != old["grants"]:
                text(record.get("grant_reference"), "explicit grant decision reference")
            records = [item for item in records if item["flight"] != record["flight"]] + [record]
            self._unique(records)
            raw = encoded({"schema": 1, "records": records})
            fd, pending = tempfile.mkstemp(prefix=".associations-", dir=self.directory)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(pending, self.path)
                directory_fd = os.open(self.directory, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                Path(pending).unlink(missing_ok=True)
            return {"revision": digest(raw), "record": copy.deepcopy(record)}

    def get(self, flight):
        return next((record for record in self.read()["records"] if record["flight"] == flight), None)

    def related(self, repository_id, issues=(), pull_requests=(), flights=()):
        """Only explicit repository-qualified associations establish relatedness."""
        return [record for record in self.read()["records"]
                if record["repository"]["id"] == repository_id
                and (record["flight"] in flights or set(issues) & set(record["issues"])
                     or set(pull_requests) & set(record["pull_requests"]))]
