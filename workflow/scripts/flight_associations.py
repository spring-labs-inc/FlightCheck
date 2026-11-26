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


def _resolved_artifact(cleanup, row):
    # Retain the original closed-flight decision. Later controlled cleanup can
    # release its reservation through the existing append-only operation log.
    # An ordinary removal outcome cannot resolve an uncertain native creation.
    if row.get("kind") == "native_operation":
        return False
    events = cleanup.get("operations", [])
    # The observed last operation belongs to this retention decision, not to a
    # later cleanup. In particular, an old removal cannot discharge a newly
    # retained artifact recreated at the same OID.
    boundary = -1
    if "last_operation" in row:
        matches = [index for index, event in enumerate(events) if event == row["last_operation"]]
        if not matches:
            return False
        boundary = matches[-1]
    for event in reversed(events[boundary + 1:]):
        if (event.get("artifact_id") != row.get("id") or event.get("event") not in ("outcome", "native_ack")
                or event.get("state") not in ("removed", "already_absent") or not event.get("operation_id")):
            continue
        intent = next((item for item in events if item.get("event") == "intent"
                       and item.get("artifact_id") == row.get("id")
                       and item.get("operation_id") == event["operation_id"]), None)
        if intent is not None and intent.get("expected_oid") == row.get("expected_oid"):
            return True
    return False


def retained_artifacts(record):
    """Derive retained/unresolved obligations from existing Registry records.

    Historical markerless closures do not acquire invented retention acceptance.
    Unknown native operations reserve only their explicitly recorded namespace;
    a requested name is not evidence of a physical checkout or successful action.
    """
    cleanup = record.get("cleanup", {})
    if not isinstance(cleanup, dict) or cleanup.get("protocol") != "required-v1":
        return []
    inventory = cleanup.get("inventory", [])
    closure = cleanup.get("closure", {})
    rows = []
    seen = set()
    for original in closure.get("artifacts", []) if isinstance(closure, dict) else []:
        if original.get("disposition") != "retained_accepted" or _resolved_artifact(cleanup, original):
            continue
        row = copy.deepcopy(original)
        text(row.get("id"), "retained artifact id")
        text(row.get("identity"), "retained artifact identity")
        if row.get("kind") not in ("worktree", "local_branch", "remote_branch", "native_operation"):
            raise AssociationError("Retained artifact kind is unsupported")
        if row.get("operation_state") not in ("blocked", "failed", "unknown"):
            raise AssociationError("Retained operation outcome must remain blocked, failed or unknown")
        item = next((value for value in inventory if value.get("id") == row["id"]), None)
        if item is None or any(row.get(key) != item.get(key) for key in ("kind", "identity", "remote")):
            raise AssociationError("Retained identity must match the frozen artifact inventory")
        if row["kind"] == "native_operation":
            for key in ("client", "requested_name", "outcome", "observation_reference"):
                if key in row and row[key] != item.get(key):
                    raise AssociationError("Retained native observation cannot change its frozen identity/outcome")
                row[key] = copy.deepcopy(item.get(key))
            if row["operation_state"] != item.get("outcome"):
                raise AssociationError("Retained native operation must preserve its unresolved outcome")
            reserved = row.get("reservations")
            original_reserved = item.get("reservations")
            if (not isinstance(reserved, dict) or not isinstance(original_reserved, dict)
                    or any(sorted(reserved.get(key, [])) != sorted(original_reserved.get(key, []))
                           for key in ("paths", "refs", "names"))):
                raise AssociationError("Retained native operation must preserve its frozen reserved namespace")
        for key in ("reason", "next_action", "policy_reference"):
            text(row.get(key), "retained artifact " + key)
        rows.append(row)
        seen.add(row["id"])
    for item in inventory:
        if item.get("kind") not in ("native_operation", "unresolved_native_operation") or item.get("id") in seen:
            continue
        row = copy.deepcopy(item)
        row["kind"] = "native_operation"
        text(row.get("identity"), "native operation identity")
        outcome = row.get("outcome")
        if outcome not in ("unknown", "failed"):
            raise AssociationError("Unresolved native operation outcome must remain unknown or failed")
        code = "native_unknown" if outcome == "unknown" else "native_failed"
        policy = cleanup.get("registration", {}).get("retention_policy") or record.get("grants", {}).get("retention", {})
        allowed = policy.get("allowed_reasons", {}).get(code, {}) if isinstance(policy, dict) else {}
        row.update(disposition="retention_pending", operation_state=outcome, reason_code=code,
                   reason="Recorded native operation remains unresolved", next_action=allowed.get("next_action")
                   or "Reconcile the original native operation before any conflicting mutation",
                   policy_reference=policy.get("reference") if isinstance(policy, dict) else None)
        rows.append(row)
    for row in rows:
        reservations = row.setdefault("reservations", {})
        if not isinstance(reservations, dict) or set(reservations) - {"paths", "refs", "names"}:
            raise AssociationError("Retained reservations must identify paths, refs or names")
        for key in ("paths", "refs", "names"):
            values = reservations.setdefault(key, [])
            if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() or "\0" in value for value in values):
                raise AssociationError("Retained reservation identities must be explicit strings")
        if row["kind"] == "worktree":
            reservations["paths"] = sorted(set([*reservations["paths"], row["identity"]]))
            original = next((item for item in inventory if item.get("id") == row.get("id")), {})
            if original.get("branch"):
                reservations["refs"] = sorted(set([*reservations["refs"], "refs/heads/" + original["branch"]]))
        elif row["kind"] in ("local_branch", "remote_branch"):
            reservations["refs"] = sorted(set([*reservations["refs"], row["identity"]]))
        elif row["kind"] == "native_operation" and row.get("requested_name"):
            reservations["names"] = sorted(set([*reservations["names"], row["requested_name"]]))
        row["flight"] = record["flight"]
    return rows


def reservation_conflicts(record, *, path=None, ref=None, name=None, endpoint=None):
    """Return matching obligations; callers qualify clone/repository resources.

    Remote ref ownership is repository-qualified by the caller, not discarded
    because the same endpoint uses a different SSH/HTTPS transport spelling.
    """
    proposed = Path(path).resolve() if path is not None else None
    names = {name.casefold()} if isinstance(name, str) else set()
    if proposed is not None:
        names.update((proposed.name.casefold(), proposed.parent.name.casefold()))
    result = []
    for row in retained_artifacts(record):
        reserved = row["reservations"]
        paths = [Path(value).resolve() for value in reserved["paths"]]
        overlaps = proposed is not None and any(proposed == value or value in proposed.parents
                                                 or proposed in value.parents for value in paths)
        if (overlaps or ref is not None and ref in reserved["refs"]
                or names & {value.casefold() for value in reserved["names"]}):
            result.append(row)
    return result


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
    cleanup = value.get("cleanup")
    if isinstance(cleanup, dict) and cleanup.get("protocol") == "required-v1":
        if not isinstance(cleanup.get("inventory"), list) or not isinstance(cleanup.get("operations"), list):
            raise AssociationError("Required cleanup inventory/history must remain structured")
        text(cleanup.get("state"), "cleanup.state")
        retained_artifacts(value)  # Reject malformed new obligations, not legacy archives.
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
    # Status authority captures the entire configuration revision, even when
    # the mapping itself is unchanged. Never silently rebind its grant.
    enabled = new["values"].get("status_sync", {}).get("mode", "disabled") != "disabled"
    if "status_sync" in changed or enabled and old["revision"] != new["revision"]:
        affected.append("status_sync")
    if changed or old["revision"] != new["revision"]:
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
            if old and isinstance(old.get("cleanup"), dict) and old["cleanup"].get("protocol") == "required-v1":
                prior = old["cleanup"]
                current = record.get("cleanup", {})
                if not isinstance(current, dict) or current.get("protocol") != "required-v1":
                    raise AssociationError("Required cleanup protocol cannot be removed or downgraded")
                if not isinstance(current.get("operations"), list) or current["operations"][:len(prior.get("operations", []))] != prior.get("operations", []):
                    raise AssociationError("Preserve original cleanup intents and outcomes")
                for key in ("inventory", "reference", "grant_sha256", "registration"):
                    if prior.get("registration") and current.get(key) != prior.get(key):
                        raise AssociationError("Registered cleanup scope cannot silently change: " + key)
                for key in ("frozen_binding", "frozen_delivery"):
                    if key in prior and current.get(key) != prior[key]:
                        raise AssociationError("Interrupted cleanup must preserve frozen identities and leases")
                if old["lifecycle"]["state"] == "closed":
                    prior_closure = prior.get("closure") or {}
                    current_closure = current.get("closure") or {}
                    retained = [row for row in prior_closure.get("artifacts", [])
                                if row.get("disposition") == "retained_accepted"]
                    current_rows = {row.get("id"): row for row in current_closure.get("artifacts", [])}
                    if any(current_rows.get(row.get("id")) != row for row in retained):
                        raise AssociationError("Preserve closed retained decisions; reconcile through append-only operations")
            if record["lifecycle"]["state"] != "closed":
                for item in [record["checkout"], *record["children"]]:
                    ref = "refs/heads/" + item["branch"] if item["branch"] else None
                    for owner in records:
                        if owner["flight"] == record["flight"]:
                            continue
                        same_clone = owner["repository"] == record["repository"]
                        matches = reservation_conflicts(owner, path=item["path"], ref=ref if same_clone else None)
                        if any(row["kind"] != "remote_branch" for row in matches):
                            raise AssociationError("Checkout/ref is reserved by retained flight " + owner["flight"])
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
