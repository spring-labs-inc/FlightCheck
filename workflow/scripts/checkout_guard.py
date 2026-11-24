"""Verify selected native checkouts using the shared private flight associations.

This module never creates, switches, moves or removes a Git checkout. Native
clients and owners perform those actions; reconciliation records their observed
results. Provider reads and checkout observations are bounded and read-only.
"""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import time
from urllib.parse import urlparse

import launch_detection
from flight_associations import AssociationError, Registry, encoded, repository_identity, validate_record
from project_config import META, normalize, protected


class CheckoutError(ValueError):
    pass


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise CheckoutError(name + " must be explicit nonempty text")
    return value


def _digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def _git(checkout, *args, allow_failure=False):
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(checkout), *args],
            stdin=subprocess.DEVNULL, capture_output=True,
            env=dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0"), timeout=10)
    except (OSError, subprocess.SubprocessError) as error:
        raise CheckoutError("Git checkout observation unavailable: " + str(error)) from error
    if result.returncode and not allow_failure:
        raise CheckoutError("Cannot verify checkout: git " + args[0] + ": " + os.fsdecode(result.stderr).strip())
    return result


def _out(checkout, *args):
    return os.fsdecode(_git(checkout, *args).stdout).rstrip("\n")


def _registry(value):
    return value if isinstance(value, Registry) else Registry(Path(value).expanduser().absolute())


def default_registry(checkout):
    """Match maintainer.state_dir's namespace without creating any directory."""
    root = Path(checkout).resolve(strict=True)
    common = Path(_out(root, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve(strict=True)
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "flightcheck"
    base = Path(os.environ.get("FLIGHTCHECK_STATE_DIR") or base).expanduser()
    if not base.is_absolute() or root in (base.resolve(), *base.resolve().parents):
        raise CheckoutError("FlightCheck state must be absolute and outside the checkout")
    base = base.resolve()
    namespace = hashlib.sha256(os.fsencode(common)).hexdigest()[:24]
    return Registry(base / namespace / "flight-associations")


def _unfinished(checkout, state):
    """A preservation digest, never a content snapshot or cleanup proof."""
    digest = hashlib.sha256()
    for data in (state["commit"].encode(),
                 _git(checkout, "diff", "--no-ext-diff", "--no-textconv", "--binary", "HEAD", "--").stdout,
                 _git(checkout, "diff", "--cached", "--no-ext-diff", "--no-textconv", "--binary", "HEAD", "--").stdout):
        digest.update(data + b"\0")
    for name in sorted(state["untracked"]):
        path = Path(checkout) / name
        digest.update(os.fsencode(name) + b"\0")
        digest.update(str(stat.S_IMODE(path.lstat().st_mode)).encode() + b"\0")
        if path.is_symlink():
            digest.update(b"link\0" + os.fsencode(os.readlink(path)))
        elif path.is_file():
            digest.update(b"file\0")
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(65536), b""):
                    digest.update(chunk)
        else:
            raise CheckoutError("Cannot identify unfinished untracked work: " + name)
        digest.update(b"\0")
    return digest.hexdigest()


def observe(checkout):
    try:
        root = Path(checkout).resolve(strict=True)
    except OSError as error:
        raise CheckoutError("Recorded checkout is missing or unavailable; explicitly reconcile native recovery") from error
    actual = Path(_out(root, "rev-parse", "--show-toplevel")).resolve(strict=True)
    if actual != root:
        raise CheckoutError("Execution path must be the actual checkout root")
    common = Path(_out(root, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve(strict=True)
    git_dir = Path(_out(root, "rev-parse", "--path-format=absolute", "--git-dir")).resolve(strict=True)
    rows = launch_detection._worktrees(root)
    row = next((item for item in rows if item["path"] == str(root)), None)
    if row is None or row.get("bare") or row.get("locked") or row.get("prunable"):
        raise CheckoutError("Checkout is unavailable, bare, locked or prunable; reconcile it explicitly")
    state = launch_detection._state(str(root), str(common))
    if not state.get("available") or not state.get("commit"):
        raise CheckoutError(state.get("reason", "Checkout HEAD is unavailable"))
    try:
        execution_host = _text(socket.gethostname(), "actual execution host")
    except OSError as error:
        raise CheckoutError("Actual execution host is unavailable") from error
    result = {"path": str(root), "execution_host": execution_host,
              "git_dir": str(git_dir), "git_common_dir": str(common),
              "branch": state["branch"], "commit": state["commit"], "isolated": git_dir != common,
              "dirty": state["dirty"], "tracked_changes": state["tracked_changes"], "untracked": state["untracked"]}
    result["unfinished_identity"] = _unfinished(root, result)
    return result


def _remote_repository(checkout):
    remote = _out(checkout, "remote", "get-url", "origin")
    match = re.fullmatch(r"git@github\.com:([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", remote)
    path = match.group(1) if match else None
    if path is None:
        parsed = urlparse(remote)
        try:
            port = parsed.port
        except ValueError as error:
            raise CheckoutError("Malformed repository origin port") from error
        if (parsed.hostname != "github.com" or parsed.scheme not in ("https", "ssh")
                or parsed.password is not None or parsed.query or parsed.fragment
                or parsed.username is not None
                or port not in (None, 443 if parsed.scheme == "https" else 22)):
            raise CheckoutError("Unsupported or credential-bearing GitHub origin; reconcile repository identity")
        path = parsed.path.removeprefix("/")
    if path.endswith(".git"):
        path = path[:-4]
    if (not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", path)
            or any(part in (".", "..") for part in path.split("/"))):
        raise CheckoutError("Malformed origin repository owner/name")
    return path


def _provider_json(arguments, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise CheckoutError("Authoritative provider policy discovery deadline exceeded")
    try:
        result = subprocess.run(
            ["gh", "api", *arguments, "--hostname", "github.com", "--header",
             "Accept: application/vnd.github+json"],
            stdin=subprocess.DEVNULL, capture_output=True,
            env=dict(os.environ, GH_PROMPT_DISABLED="1", GH_PAGER="cat"), timeout=min(10, remaining))
        if result.returncode:
            raise CheckoutError("Authoritative provider policy is unavailable; reconcile GitHub read access")
        return json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        if isinstance(error, CheckoutError):
            raise
        raise CheckoutError("Authoritative provider policy is unavailable: " + str(error)) from error


def _gh(endpoint, deadline):
    return _provider_json([endpoint, "--method", "GET"], deadline)


_CLASSIC_QUERY = ("query FlightCheckBranchProtection($owner:String!, $name:String!, $cursor:String){"
                  "repository(owner:$owner,name:$name){nameWithOwner "
                  "branchProtectionRules(first:100,after:$cursor){nodes{pattern} "
                  "pageInfo{hasNextPage endCursor}}}}")


def _classic_patterns(repository, deadline):
    # GitHub REST cannot enumerate classic protection's wildcard patterns. This
    # fixed GraphQL query has read semantics despite its required HTTP POST.
    owner, name = repository.split("/")
    cursor, patterns, seen = None, [], set()
    for _ in range(10):
        value = _provider_json(["graphql", "--method", "POST", "-f", "query=" + _CLASSIC_QUERY,
                                "-f", "owner=" + owner, "-f", "name=" + name,
                                "-F", "cursor=" + (cursor or "null")], deadline)
        data = value.get("data", {}).get("repository") if isinstance(value, dict) else None
        if (not isinstance(data, dict) or data.get("nameWithOwner", "").lower() != repository.lower()
                or value.get("errors")):
            raise CheckoutError("Authoritative classic branch-protection policy is unavailable")
        connection = data.get("branchProtectionRules", {})
        nodes, page = connection.get("nodes"), connection.get("pageInfo")
        if (not isinstance(nodes, list) or not isinstance(page, dict)
                or not isinstance(page.get("hasNextPage"), bool)
                or any(not isinstance(item, dict) or not isinstance(item.get("pattern"), str) for item in nodes)):
            raise CheckoutError("Malformed authoritative classic branch-protection policy")
        patterns.extend(item["pattern"] for item in nodes)
        if not page["hasNextPage"]:
            return sorted(set(patterns))
        cursor = page.get("endCursor")
        if not isinstance(cursor, str) or not cursor or cursor in seen:
            raise CheckoutError("Malformed authoritative classic protection pagination")
        seen.add(cursor)
    raise CheckoutError("Classic branch protection exceeds bounded discovery; reconcile explicitly")


def _pages(endpoint, deadline):
    values = []
    separator = "&" if "?" in endpoint else "?"
    for page in range(1, 11):
        rows = _gh(endpoint + separator + "per_page=100&page=" + str(page), deadline)
        if not isinstance(rows, list):
            raise CheckoutError("Malformed authoritative provider policy response")
        values.extend(rows)
        if len(rows) < 100:
            return values
    raise CheckoutError("Authoritative policy exceeds bounded discovery; explicit reconciliation required")


def _pattern(pattern, branch, default):
    """GitHub ref-name fnmatch: ordinary stars do not consume slashes."""
    if pattern == "~ALL":
        return True
    if pattern == "~DEFAULT_BRANCH":
        return branch == default
    _text(pattern, "provider ref pattern")
    expression, index = "", 0
    while index < len(pattern):
        char = pattern[index]
        if pattern[index:index + 3] == "**/":
            expression += "(?:.*/)?"
            index += 3
            continue
        if pattern[index:index + 2] == "**":
            expression += ".*"
            index += 2
            continue
        if char == "*":
            expression += "[^/]*"
        elif char == "?":
            expression += "[^/]"
        elif char == "[":
            end = pattern.find("]", index + 1)
            if end == -1:
                raise CheckoutError("Unsupported provider ref pattern; reconcile protection before implementation")
            content = pattern[index + 1:end]
            if not content or "/" in content or "\\" in content:
                raise CheckoutError("Unsupported provider ref pattern; reconcile protection before implementation")
            expression += "[" + ("^" + content[1:] if content.startswith("!") else content) + "]"
            index = end
        elif char == "\\":
            index += 1
            if index == len(pattern):
                raise CheckoutError("Unsupported provider ref pattern")
            expression += re.escape(pattern[index])
        else:
            expression += re.escape(char)
        index += 1
    try:
        return re.fullmatch(expression, "refs/heads/" + branch) is not None
    except re.error as error:
        raise CheckoutError("Unsupported provider ref pattern") from error


def resolve_policy(checkout, repository_id):
    """Read current GitHub defaults/protection, including unpublished branch rules.

    REST GETs and one fixed read-only GraphQL query each have a deadline;
    discovery has a whole-operation deadline and finite pages. Cached origin/HEAD
    is no proof.
    """
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository_id):
        raise CheckoutError("Unsupported provider repository identity; reconcile explicitly")
    remote = _remote_repository(checkout)
    if remote.lower() != repository_id.lower():
        raise CheckoutError("Actual origin repository does not match the flight repository identity")
    deadline = time.monotonic() + 45
    endpoint = "repos/" + repository_id
    repository = _gh(endpoint, deadline)
    if (not isinstance(repository, dict) or repository.get("full_name", "").lower() != repository_id.lower()
            or not repository.get("default_branch")):
        raise CheckoutError("Authoritative repository identity/default is unavailable")
    default = repository["default_branch"]
    branches = _pages(endpoint + "/branches", deadline)
    if any(not isinstance(item, dict) or not isinstance(item.get("name"), str)
           or not isinstance(item.get("protected"), bool) for item in branches):
        raise CheckoutError("Cannot establish complete authoritative branch protection")
    protected_names = {item["name"] for item in branches if item["protected"]}
    # Rulesets can protect an unpublished working branch. Query ruleset patterns
    # rather than requiring that branch to exist on the provider.
    rulesets = _pages(endpoint + "/rulesets?includes_parents=true", deadline)
    branch = observe(checkout)["branch"]
    applied = []
    classic_patterns = _classic_patterns(repository_id, deadline)
    if branch and any(_pattern("refs/heads/" + pattern, branch, default) for pattern in classic_patterns):
        protected_names.add(branch)
    for summary in rulesets:
        if not isinstance(summary, dict) or not isinstance(summary.get("id"), int):
            raise CheckoutError("Malformed authoritative ruleset response")
        if summary.get("enforcement") != "active" or summary.get("target") != "branch":
            continue
        detail = _gh(endpoint + "/rulesets/" + str(summary["id"]) + "?includes_parents=true", deadline)
        condition = detail.get("conditions", {}).get("ref_name") if isinstance(detail, dict) else None
        if (not isinstance(condition, dict) or not isinstance(condition.get("include"), list)
                or not isinstance(condition.get("exclude"), list)):
            raise CheckoutError("Cannot establish authoritative ruleset branch applicability")
        if branch and any(_pattern(pattern, branch, default) for pattern in condition["include"]) and not any(
                _pattern(pattern, branch, default) for pattern in condition["exclude"]):
            protected_names.add(branch)
            applied.append(summary["id"])
    return {"repository": repository_id, "default_branch": default,
            "protected_branches": sorted(protected_names | {default}),
            "source": "github-api-current", "applied_rulesets": sorted(applied), "classic_patterns": classic_patterns}


def _policy(checkout, repository, supplied):
    value = supplied(checkout, repository) if callable(supplied) else supplied
    if value is None:
        value = resolve_policy(checkout, repository)
    if (not isinstance(value, dict) or value.get("repository") != repository
            or not isinstance(value.get("default_branch"), str)
            or not isinstance(value.get("protected_branches"), list)
            or any(not isinstance(branch, str) or not branch for branch in value["protected_branches"])
            or not value.get("source")):
        raise CheckoutError("Authoritative repository/default/protected policy is unavailable or mismatched")
    if value.get("available") is False:
        raise CheckoutError("Authoritative repository policy is unavailable")
    return copy.deepcopy(value)


def _ancestor(checkout, previous, current):
    result = _git(checkout, "merge-base", "--is-ancestor", previous, current, allow_failure=True)
    return result.returncode == 0


def _base(checkout, value):
    if isinstance(value, dict):
        reference = value.get("ref") or value.get("commit")
        expected = value.get("commit")
    else:
        reference, expected = value, None
    _text(reference, "base")
    commit = _out(checkout, "rev-parse", "--verify", "--end-of-options", reference + "^{commit}")
    if expected and commit != expected:
        raise CheckoutError("Pinned base does not match the observed base reference")
    return {"ref": reference, "commit": commit}


def _decision(value):
    if value is None:
        return {}
    if isinstance(value, str):
        return {"reference": _text(value, "owner decision")}
    if not isinstance(value, dict):
        raise CheckoutError("Owner decision must be an explicit reference object")
    _text(value.get("reference"), "owner decision reference")
    return copy.deepcopy(value)


def _client(observation, fallback):
    if not isinstance(observation, dict):
        raise CheckoutError("Explicit client observation is required")
    name = observation.get("client") or observation.get("name") or fallback.get("name")
    sessions = observation.get("sessions")
    if sessions is None:
        session = observation.get("session")
        sessions = [session] if session else fallback.get("sessions", [])
    _text(name, "client name")
    if not isinstance(sessions, list) or not sessions or any(not isinstance(item, str) or not item for item in sessions):
        raise CheckoutError("Explicit client/session observation is required")
    capabilities = observation.get("capabilities", {})
    if not isinstance(capabilities, dict):
        raise CheckoutError("Client capabilities must distinguish observations from unavailable capabilities")
    selection = observation.get("selection", "native")
    if selection not in ("native", "manual") or not isinstance(observation.get("available", True), bool):
        raise CheckoutError("Client observation must identify actual native/manual selection and availability")
    return {"name": name, "sessions": sorted(set(sessions)),
            "available": observation.get("available", True),
            "selection": selection, "capabilities": copy.deepcopy(capabilities),
            "provenance": {key: copy.deepcopy(value) for key, value in observation.items()
                           if key not in {"client", "name", "session", "sessions", "available", "selection", "capabilities"}}}


def _configuration(checkout, record):
    config = normalize(checkout, record["configuration"]["values"], trusted_metadata=True, probe_runtime=False)
    metadata = config.get(META, {}).get("fields", {})
    if not metadata.get("default_branch", {}).get("confirmed"):
        raise CheckoutError("Default branch configuration must be explicitly confirmed before checkout adoption")
    return config


def _validate_checkout(state, item, record, base, policy, phase, check_identity=True):
    config = _configuration(state["path"], record)
    if state["git_common_dir"] != record["repository"]["git_common_dir"]:
        raise CheckoutError("Checkout repository/common Git directory does not match flight ownership")
    if config.get("default_branch") != policy["default_branch"]:
        raise CheckoutError("Confirmed default branch differs from current authoritative default; explicitly reconfigure")
    effective = set(protected(config)) | set(policy["protected_branches"]) | {policy["default_branch"]}
    branch = state["branch"]
    if branch in effective:
        raise CheckoutError("Implementation/delivery is forbidden on protected branch " + branch)
    mode = config.get("checkout_policy", {}).get("mode", "native-choice")
    if mode == "worktree-required" and not state["isolated"]:
        raise CheckoutError("worktree-required policy requires a separate linked flight worktree; no fallback")
    if branch is None and (not state["isolated"] or item["management"] != "native"):
        raise CheckoutError("Detached execution requires an isolated native checkout")
    if phase == "delivery" and branch is None:
        raise CheckoutError("Delivery requires a dedicated unprotected branch; reconcile the native branch first")
    if branch is not None:
        _git(state["path"], "check-ref-format", "refs/heads/" + branch)
        prefix = config.get("checkout_policy", {}).get("branch_prefix")
        if prefix and not branch.startswith(prefix):
            raise CheckoutError("Checkout branch does not match the confirmed branch-prefix policy")
        duplicates = [row for row in launch_detection._worktrees(state["path"])
                      if row.get("branch") == branch and row["path"] != state["path"]]
        if duplicates:
            raise CheckoutError("Working branch is checked out elsewhere; exclusive flight ownership is unavailable")
    fallback = config.get("checkout_policy", {})
    if item["management"] == "manual" and (fallback.get("git_fallback") is not True or not fallback.get("fallback_reference")):
        raise CheckoutError("Manual Git fallback requires explicitly confirmed scoped fallback policy")
    if not _ancestor(state["path"], base["commit"], state["commit"]):
        raise CheckoutError("Checkout does not descend from the pinned flight base")
    if check_identity:
        if state["execution_host"] != item.get("execution_host"):
            raise CheckoutError("Actual execution host differs from recorded ownership; explicitly reconcile the native context")
        if state["branch"] != item["branch"]:
            raise CheckoutError("Checkout branch identity drifted; explicitly reconcile native action before execution")
        if not _ancestor(state["path"], item["commit"], state["commit"]):
            raise CheckoutError("Checkout commit no longer preserves the recorded unfinished commit; explicit recovery required")
    return sorted(effective)


def _anchor(state, item):
    return {"unfinished_identity": state["unfinished_identity"], "git_dir": state["git_dir"],
            "execution_host": state["execution_host"],
            "branch": item["branch"], "commit": item["commit"],
            "kind": item["kind"], "management": item["management"]}


def _report(registry, revision, record, state, phase, policy):
    guard = record["checkout_guard"]
    main = state["path"] == record["checkout"]["path"]
    binding = {"registry": str(registry.directory), "flight": record["flight"]}
    identity = {"checkout_binding": binding, "repository": record["repository"],
                "path": state["path"], "execution_host": state["execution_host"],
                "git_dir": state["git_dir"], "branch": state["branch"],
                "role": "main" if main else "child",
                "classification": {key: next(item for item in [record["checkout"], *record["children"]]
                                              if item["path"] == state["path"])[key] for key in ("kind", "management")},
                "configuration": record["configuration"],
                "grants": record["grants"], "delivery": record["delivery"], "base": guard["base"],
                "client": guard["client_observation"], "generation": guard["generation"],
                "policy": policy, "execution_open": record["lifecycle"]["state"] in ("active", "review")}
    binding_digest = _digest(identity)
    return {"schema": 1, "status": "verified", "flight": record["flight"],
            "registry": str(registry.directory), "registry_revision": revision,
            "checkout_binding": binding, "phase": phase, "repository": copy.deepcopy(record["repository"]),
            "checkout": copy.deepcopy(state), "role": identity["role"],
            "configuration_revision": record["configuration"]["revision"], "base": copy.deepcopy(guard["base"]),
            "policy": policy, "binding_digest": binding_digest,
            "head_binding": _digest({"binding_digest": binding_digest, "commit": state["commit"]}),
            "unfinished_identity": state["unfinished_identity"], "generation": guard["generation"],
            "limits": ["Point-in-time verification; native selection/recovery is observed, never performed",
                       "No universal interception of external Git, native-client or provider commands",
                       "No cleanup, retention, snapshot or provider-write authority",
                       "Unfinished identity covers HEAD, tracked diffs and nonignored untracked bytes/modes; ignored files are outside that proof"]}


def adopt(checkout, registry, record, *, base, client_observation, decision=None, policy=None):
    registry = _registry(registry)
    record = validate_record(record)
    previous = registry.read()
    decision = _decision(decision)
    existing = next((item for item in previous["records"] if item["flight"] == record["flight"]), None)
    if existing:
        if existing.get("checkout_guard") or existing["lifecycle"]["state"] == "closed" or decision.get("current_flight") is not True:
            raise CheckoutError("Flight already exists; verify/resume or explicitly reconcile it")
        for key in ("task", "card", "repository", "configuration", "grants", "delivery", "checkout", "children", "client"):
            if existing[key] != record[key]:
                raise CheckoutError("Current-flight verifier adoption must preserve existing association " + key)
        record = copy.deepcopy(existing)
    state = observe(checkout)
    if state["path"] != record["checkout"]["path"]:
        raise CheckoutError("Proposed main checkout is not the actual execution checkout")
    identity = repository_identity(checkout, record["repository"]["id"])
    if identity != record["repository"]:
        raise CheckoutError("Proposed repository identity does not match the actual common Git directory")
    client = _client(client_observation, record["client"])
    if client["name"] != record["client"]["name"]:
        raise CheckoutError("Observed native client does not match the proposed flight client")
    if client["selection"] != record["checkout"]["management"]:
        raise CheckoutError("Observed native/manual selection does not match checkout management provenance")
    record["client"] = {"name": client["name"], "sessions": client["sessions"]}
    pinned = _base(checkout, base)
    report = launch_detection.detect(checkout, registry, identity["id"], record["issues"], record["pull_requests"],
                                     current_flight=record["flight"])
    other_related = [item for item in report["related"] if item["flight"] != record["flight"]]
    if other_related and not decision.get("dependent_flight"):
        raise CheckoutError("Related unfinished flight requires explicit resume/reuse/wait or deliberate dependent-flight decision")
    anchors = {}
    main_policy = None
    for item in [record["checkout"], *record["children"]]:
        actual = state if item["path"] == state["path"] else observe(item["path"])
        if actual["branch"] != item["branch"] or actual["commit"] != item["commit"]:
            raise CheckoutError("Proposed checkout branch/commit differs from actual native selection; refresh the explicit adoption record")
        observed_policy = _policy(actual["path"], identity["id"], policy)
        _validate_checkout(actual, item, record, pinned, observed_policy, "implementation", check_identity=False)
        if (actual["dirty"] or actual["untracked"]) and decision.get("adopt_existing") is not True:
            raise CheckoutError("Dirty/untracked existing work has unknown ownership; explicitly reconcile adoption before edits")
        item.update(branch=actual["branch"], commit=actual["commit"], execution_host=actual["execution_host"])
        anchors[item["path"]] = _anchor(actual, item)
        if item is record["checkout"]:
            main_policy = observed_policy
    for item in [record["checkout"], *record["children"]]:
        fresh = observe(item["path"])
        if (fresh["branch"] != item["branch"] or fresh["commit"] != item["commit"]
                or fresh["git_dir"] != anchors[item["path"]]["git_dir"]
                or fresh["execution_host"] != anchors[item["path"]]["execution_host"]
                or fresh["unfinished_identity"] != anchors[item["path"]]["unfinished_identity"]):
            raise CheckoutError("Checkout changed during adoption; refresh the explicit native observation")
        if item["path"] == state["path"]:
            state = fresh
    record["checkout_guard"] = {"version": 1, "base": pinned, "generation": 1,
                                "configuration_revision": record["configuration"]["revision"],
                                "client_observation": client, "anchors": anchors,
                                "history": [{"action": "adopt", "decision": decision, "checkout": copy.deepcopy(record["checkout"]),
                                             "children": copy.deepcopy(record["children"]), "client": client}]}
    saved = registry.save(record, expected_revision=previous["revision"])
    return _report(registry, saved["revision"], saved["record"], state, "implementation", main_policy)


def verify(checkout, registry, flight=None, *, phase="implementation", session=None, policy=None):
    registry = _registry(registry)
    state = observe(checkout)
    previous = registry.read()
    owners = [record for record in previous["records"] if record["lifecycle"]["state"] != "closed"
              and any(item["path"] == state["path"] for item in [record["checkout"], *record["children"]])]
    if flight is None:
        if len(owners) != 1:
            raise CheckoutError("Actual execution checkout has no unique active flight owner")
        record = owners[0]
    else:
        record = next((item for item in previous["records"] if item["flight"] == flight), None)
        if record is None or record["lifecycle"]["state"] == "closed":
            raise CheckoutError("Selected flight is missing or closed; explicit context cannot become unbound")
        if not owners or owners[0]["flight"] != flight:
            raise CheckoutError("Actual execution checkout is not owned by the selected flight")
    guard = record.get("checkout_guard")
    if not isinstance(guard, dict) or guard.get("version") != 1:
        raise CheckoutError("Existing association lacks verified checkout binding; explicitly reconcile it")
    expected_client = {"name": guard["client_observation"]["name"], "sessions": guard["client_observation"]["sessions"]}
    if record["client"] != expected_client:
        raise CheckoutError("Recorded client association changed without explicit checkout reconciliation")
    if guard.get("configuration_revision") != record["configuration"]["revision"]:
        raise CheckoutError("Flight configuration revision changed; explicitly reconcile required checkout/check/evidence revalidation")
    if record["lifecycle"]["state"] not in ("active", "review"):
        raise CheckoutError("Flight is paused or completed; explicitly reconcile resume before execution")
    if session is not None:
        if isinstance(session, dict):
            client = session.get("client") or session.get("name")
            session_id = session.get("session")
            if client and client != guard["client_observation"]["name"]:
                raise CheckoutError("Native client changed; explicit cross-client reconciliation required")
        else:
            session_id = session
        if session_id not in guard["client_observation"]["sessions"]:
            raise CheckoutError("Native session is not associated with this flight; explicitly reconcile resume")
    observed_policy = None
    for item in [record["checkout"], *record["children"]]:
        actual = state if item["path"] == state["path"] else observe(item["path"])
        current_policy = _policy(actual["path"], record["repository"]["id"], policy)
        item_phase = phase if item["path"] == state["path"] else "implementation"
        _validate_checkout(actual, item, record, guard["base"], current_policy, item_phase)
        anchor = guard["anchors"].get(item["path"], {})
        if (actual["git_dir"] != anchor.get("git_dir") or actual["execution_host"] != anchor.get("execution_host")) or any(anchor.get(key) != item[key] for key in ("branch", "commit", "kind", "management")):
            raise CheckoutError("Checkout recorded/administrative identity drifted; explicitly reconcile restore/move")
        if item["path"] == state["path"]:
            observed_policy = current_policy
    if phase == "delivery" and state["path"] != record["checkout"]["path"]:
        raise CheckoutError("Only the main flight checkout may deliver; preserve child ownership")
    fresh = observe(checkout)
    if any(fresh[key] != state[key] for key in ("path", "execution_host", "git_dir", "git_common_dir", "branch")):
        raise CheckoutError("Checkout identity changed during verification; reconcile the actual native context")
    selected = next(item for item in [record["checkout"], *record["children"]] if item["path"] == fresh["path"])
    _validate_checkout(fresh, selected, record, guard["base"], observed_policy, phase)
    if registry.read()["revision"] != previous["revision"]:
        raise CheckoutError("Flight associations changed during verification; reread the current ownership")
    state = fresh
    return _report(registry, previous["revision"], record, state, phase, observed_policy)


def reconcile(registry, flight, checkout, reference, *, previous_path=None, client_observation=None,
              session=None, previous_observation=None, policy=None):
    registry = _registry(registry)
    _text(reference, "explicit reconciliation reference")
    previous = registry.read()
    record = next((item for item in previous["records"] if item["flight"] == flight), None)
    if record is None or record["lifecycle"]["state"] == "closed":
        raise CheckoutError("Cannot resume a missing or closed flight")
    record = copy.deepcopy(record)
    guard = record.get("checkout_guard")
    if not isinstance(guard, dict) or guard.get("version") != 1:
        raise CheckoutError("Unverified legacy association requires explicit adoption/reconfiguration, not guessed recovery")
    old_path = str(Path(previous_path).resolve()) if previous_path else record["checkout"]["path"]
    item = next((item for item in [record["checkout"], *record["children"]] if item["path"] == old_path), None)
    if item is None:
        raise CheckoutError("Reconciliation must name an existing owned main/child checkout")
    state = observe(checkout)
    if state["git_common_dir"] != record["repository"]["git_common_dir"]:
        raise CheckoutError("Cross-clone recovery cannot silently change repository ownership")
    if not _ancestor(checkout, item["commit"], state["commit"]):
        raise CheckoutError("Reconciliation cannot establish preservation of the prior unfinished commit")
    moved = state["path"] != old_path
    old_anchor = guard["anchors"].get(old_path, {})
    restored = (state["git_dir"] != old_anchor.get("git_dir")
                or old_anchor.get("execution_host") is not None and state["execution_host"] != old_anchor["execution_host"])
    if moved and Path(old_path).exists():
        raise CheckoutError("Prior checkout still exists; preserve its unfinished ownership instead of replacing it")
    if moved or restored:
        expected = guard["anchors"].get(old_path, {}).get("unfinished_identity")
        if previous_observation is not None:
            if (not isinstance(previous_observation, dict) or previous_observation.get("flight") != flight
                    or previous_observation.get("generation") != guard["generation"]
                    or previous_observation.get("checkout", {}).get("path") != old_path
                    or previous_observation.get("checkout_binding") != {"registry": str(registry.directory), "flight": flight}):
                raise CheckoutError("Prior native move observation does not bind the current flight/checkout generation")
            expected = previous_observation.get("unfinished_identity")
        if not expected or expected != state["unfinished_identity"]:
            raise CheckoutError("Moved/restored unfinished work identity is uncertain; retain the prior checkout and reconcile evidence")
    current_policy = _policy(checkout, record["repository"]["id"], policy)
    _validate_checkout(state, item, record, guard["base"], current_policy, "implementation", check_identity=False)
    for other in [record["checkout"], *record["children"]]:
        if other is item:
            continue
        other_state = observe(other["path"])
        other_policy = _policy(other["path"], record["repository"]["id"], policy)
        _validate_checkout(other_state, other, record, guard["base"], other_policy, "implementation")
        anchor = guard["anchors"].get(other["path"], {})
        if (other_state["git_dir"] != anchor.get("git_dir") or other_state["execution_host"] != anchor.get("execution_host")) or any(anchor.get(key) != other[key] for key in ("branch", "commit", "kind", "management")):
            raise CheckoutError("Another owned checkout needs explicit reconciliation before accepting flight-wide reconfiguration")
    fresh = observe(checkout)
    if any(fresh[key] != state[key] for key in ("path", "execution_host", "git_dir", "git_common_dir", "branch", "commit", "unfinished_identity")):
        raise CheckoutError("Native checkout changed during reconciliation; retain and refresh its actual observation")
    old = {"checkout": copy.deepcopy(item), "client": copy.deepcopy(record["client"]),
           "client_observation": copy.deepcopy(guard["client_observation"]), "lifecycle": copy.deepcopy(record["lifecycle"])}
    if client_observation is not None:
        client = _client(client_observation, record["client"])
    elif session is not None:
        observation = copy.deepcopy(guard["client_observation"])
        observation["sessions"] = [_text(session, "reconciled client session")]
        client = _client(observation, record["client"])
    else:
        client = guard["client_observation"]
    item.update(path=state["path"], branch=state["branch"], commit=state["commit"], execution_host=state["execution_host"])
    guard["anchors"].pop(old_path, None)
    guard["anchors"][state["path"]] = _anchor(state, item)
    guard["client_observation"] = client
    guard["configuration_revision"] = record["configuration"]["revision"]
    record["client"] = {"name": client["name"], "sessions": client["sessions"]}
    guard["generation"] += 1
    guard["history"].append({"action": "reconcile", "reference": reference, "previous": old,
                             "checkout": copy.deepcopy(item), "client_observation": client,
                             "unfinished_identity": state["unfinished_identity"],
                             "required_revalidation": ["checkout", "checks", "evidence", "review"]})
    record["lifecycle"]["state"] = "active"
    saved = registry.save(record, expected_revision=previous["revision"])
    return _report(registry, saved["revision"], saved["record"], state, "implementation", current_policy)


def release(registry, flight, reference, *, policy=None):
    registry = _registry(registry)
    _text(reference, "closeout/handoff reference")
    previous = registry.read()
    record = next((item for item in previous["records"] if item["flight"] == flight), None)
    if record is None or record["lifecycle"]["state"] == "closed":
        raise CheckoutError("Flight is missing or already closed")
    record = copy.deepcopy(record)
    guard = record.get("checkout_guard")
    if not isinstance(guard, dict):
        raise CheckoutError("Unverified association needs explicit closeout reconciliation")
    guard["history"].append({"action": "release", "reference": reference,
                             "checkout": copy.deepcopy(record["checkout"]), "children": copy.deepcopy(record["children"]),
                             "previous_lifecycle": copy.deepcopy(record["lifecycle"]),
                             "disposition": "Execution ownership released; files, refs and child provenance retained"})
    guard["generation"] += 1
    record["lifecycle"]["state"] = "closed"
    saved = registry.save(record, expected_revision=previous["revision"])
    return {"schema": 1, "status": "released", "flight": flight, "registry": str(registry.directory),
            "registry_revision": saved["revision"], "record": saved["record"],
            "limits": ["No files, refs, worktrees, evidence or child records removed"]}


def _binding(value):
    if not isinstance(value, dict) or set(value) != {"registry", "flight"}:
        raise CheckoutError("Selected checkout_binding requires exactly registry and flight")
    return {"registry": str(_registry(value["registry"]).directory), "flight": _text(value["flight"], "selected flight")}


def guard_context(checkout, task=None, phase="implementation", *, policy=None):
    task_binding = _binding(task["checkout_binding"]) if isinstance(task, dict) and "checkout_binding" in task else None
    registry_env, flight_env = os.environ.get("FLIGHTCHECK_REGISTRY"), os.environ.get("FLIGHTCHECK_FLIGHT")
    if bool(registry_env) != bool(flight_env):
        raise CheckoutError("Explicit flight environment requires both FLIGHTCHECK_REGISTRY and FLIGHTCHECK_FLIGHT")
    env_binding = _binding({"registry": registry_env, "flight": flight_env}) if registry_env else None
    if task_binding and env_binding and task_binding != env_binding:
        raise CheckoutError("Task and environment checkout bindings disagree; reconcile the selected context")
    binding = task_binding or env_binding
    session_id = os.environ.get("FLIGHTCHECK_SESSION") or os.environ.get("CODEX_THREAD_ID") or os.environ.get("CLAUDE_SESSION_ID")
    client = os.environ.get("FLIGHTCHECK_CLIENT")
    if not client and not os.environ.get("FLIGHTCHECK_SESSION"):
        if os.environ.get("CODEX_THREAD_ID") and os.environ.get("CLAUDE_SESSION_ID"):
            raise CheckoutError("Ambiguous native client/session context; explicitly select and reconcile the actual client")
        client = "codex" if os.environ.get("CODEX_THREAD_ID") else "claude" if os.environ.get("CLAUDE_SESSION_ID") else None
    session = {"client": client, "session": session_id} if session_id or client else None
    if binding:
        return verify(checkout, binding["registry"], binding["flight"], phase=phase, session=session, policy=policy)
    try:
        registry = default_registry(checkout)
    except CheckoutError:
        # Standalone legacy evidence helpers also run outside Git repositories.
        probe = _git(checkout, "rev-parse", "--show-toplevel", allow_failure=True)
        if probe.returncode:
            return {"schema": 1, "status": "unbound", "checkout": {"path": str(Path(checkout).resolve())},
                    "limits": ["Standalone legacy context; no selected flight checkout protection"]}
        raise
    root = str(Path(_out(checkout, "rev-parse", "--show-toplevel")).resolve())
    owners = [record for record in registry.read()["records"] if record["lifecycle"]["state"] != "closed"
              and any(item["path"] == root for item in [record["checkout"], *record["children"]])]
    if owners:
        return verify(checkout, registry, owners[0]["flight"], phase=phase, session=session, policy=policy)
    return {"schema": 1, "status": "unbound", "checkout": {"path": str(Path(checkout).resolve())},
            "limits": ["Standalone legacy context; no selected flight checkout protection"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("adopt", "verify", "reconcile", "release"))
    parser.add_argument("--checkout", type=Path, default=Path.cwd())
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--flight")
    parser.add_argument("--phase", default="implementation", choices=("implementation", "check", "review", "delivery"))
    parser.add_argument("--record", type=Path, help="Private complete foundation association JSON")
    parser.add_argument("--base")
    parser.add_argument("--client-observation", type=Path, help="Private actual native/manual observation JSON")
    parser.add_argument("--decision", type=Path, help="Private explicit owner decision JSON")
    parser.add_argument("--reference")
    parser.add_argument("--previous-path", type=Path)
    parser.add_argument("--previous-observation", type=Path)
    parser.add_argument("--session")
    args = parser.parse_args(argv)
    try:
        registry = _registry(args.registry) if args.registry else default_registry(args.checkout)
        read = lambda path: json.loads(path.read_bytes()) if path else None
        if args.action == "adopt":
            if not args.record or not args.base or not args.client_observation:
                raise CheckoutError("adopt requires --record, --base and --client-observation")
            result = adopt(args.checkout, registry, read(args.record), base=args.base,
                           client_observation=read(args.client_observation), decision=read(args.decision))
        elif args.action == "verify":
            result = verify(args.checkout, registry, args.flight, phase=args.phase, session=args.session)
        elif args.action == "reconcile":
            result = reconcile(registry, args.flight, args.checkout, args.reference,
                               previous_path=args.previous_path, client_observation=read(args.client_observation),
                               session=args.session, previous_observation=read(args.previous_observation))
        else:
            result = release(registry, args.flight, args.reference)
        print(json.dumps(result, indent=2))
        return 0
    except (AssociationError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({"schema": 1, "status": "blocked", "reason": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
