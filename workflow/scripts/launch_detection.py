"""Read-only, association-first unfinished-work observations for flight launch.

Local ref comparisons are indicators, not cleanup integration proofs. This is a
launch operation, not a repository-wide branch audit or a checkout manager.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess

from flight_associations import AssociationError, Registry, repository_identity, retained_artifacts, reservation_conflicts


def git(checkout, *args):
    return subprocess.run(["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(checkout), *args],
                          capture_output=True, env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))


def _worktrees(checkout):
    result = git(checkout, "worktree", "list", "--porcelain", "-z")
    if result.returncode:
        raise AssociationError("Cannot enumerate worktrees: " + os.fsdecode(result.stderr).strip())
    rows, current = [], {}
    for raw in result.stdout.split(b"\0"):
        if not raw:
            if current:
                rows.append(current)
                current = {}
            continue
        key, _, value = os.fsdecode(raw).partition(" ")
        if key == "worktree":
            current["path"] = str(Path(value).resolve())
        elif key == "HEAD":
            current["commit"] = value
        elif key == "branch":
            current["branch"] = value[len("refs/heads/"):] if value.startswith("refs/heads/") else value
        elif key in ("locked", "prunable", "detached", "bare"):
            current[key] = value or True
    if current:
        rows.append(current)
    return rows


def _state(path, common_dir):
    path = Path(path)
    if not path.is_dir():
        return {"available": False, "reason": "Recorded checkout is missing; reconcile native recovery before resuming"}
    try:
        actual = repository_identity(path, "probe")
    except (AssociationError, OSError) as error:
        return {"available": False, "reason": str(error)}
    if actual["git_common_dir"] != common_dir:
        return {"available": False, "reason": "Checkout repository identity drifted; reconcile the recorded ownership before resuming"}
    top = git(path, "rev-parse", "--show-toplevel")
    if top.returncode or str(Path(os.fsdecode(top.stdout).strip()).resolve()) != str(path.resolve()):
        return {"available": False, "reason": "Recorded path is not the actual checkout root"}
    status = git(path, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if status.returncode:
        return {"available": False, "reason": "Checkout status unavailable: " + os.fsdecode(status.stderr).strip()}
    tracked, untracked = [], []
    entries = status.stdout.split(b"\0")
    index = 0
    while index < len(entries):
        raw = entries[index]
        index += 1
        if not raw:
            continue
        code, filename = raw[:2], os.fsdecode(raw[3:])
        (untracked if code == b"??" else tracked).append(filename)
        if b"R" in code or b"C" in code:
            index += 1  # The second pathname belongs to this rename/copy entry.
    head = git(path, "rev-parse", "HEAD")
    branch = git(path, "symbolic-ref", "--quiet", "--short", "HEAD")
    return {"available": True, "dirty": bool(tracked), "untracked": untracked,
            "tracked_changes": tracked,
            "commit": os.fsdecode(head.stdout).strip() if head.returncode == 0 else None,
            "branch": os.fsdecode(branch.stdout).strip() if branch.returncode == 0 else None}


def _count(checkout, comparison):
    left, _, right = comparison.partition("..")
    resolved = []
    for reference in (left, right):
        result = git(checkout, "rev-parse", "--verify", "--end-of-options", reference + "^{commit}")
        if result.returncode:
            return {"available": False, "reason": "Comparison ref unavailable in local cached state"}
        resolved.append(os.fsdecode(result.stdout).strip())
    result = git(checkout, "rev-list", "--count", resolved[0] + ".." + resolved[1], "--")
    if result.returncode:
        return {"available": False, "reason": "Comparison ref unavailable in local cached state"}
    return {"available": True, "count": int(result.stdout)}


def _branch(checkout, branch, commit, target):
    if not branch:
        return {"branch": None, "detached_commit": commit,
                "unmerged": _count(checkout, target + ".." + commit) if target and commit else
                {"available": False, "reason": "No usable recorded target or detached commit"},
                "unpushed": {"available": False, "reason": "Detached HEAD has no branch upstream"}}
    ref = "refs/heads/" + branch
    observed = git(checkout, "rev-parse", "--verify", ref + "^{commit}")
    if observed.returncode:
        return {"branch": branch, "unmerged": {"available": False, "reason": "Recorded branch is missing"},
                "unpushed": {"available": False, "reason": "Recorded branch is missing"}}
    upstream = git(checkout, "for-each-ref", "--format=%(upstream)", ref)
    upstream_ref = os.fsdecode(upstream.stdout).strip() if upstream.returncode == 0 else ""
    return {"branch": branch, "commit": os.fsdecode(observed.stdout).strip(),
            "unmerged": _count(checkout, target + ".." + ref) if target else
            {"available": False, "reason": "No explicit/default target is recorded"},
            "unpushed": _count(checkout, upstream_ref + ".." + ref) if upstream_ref else
            {"available": False, "reason": "No usable upstream tracking ref; unpushed status is unavailable"}}


def detect(checkout, registry, repository_id, issues=(), pull_requests=(), flights=(), current_flight=None):
    """Observe explicit related work without acquiring authority to resolve it."""
    # Retain one-shot selectors for both validation and repository lookup.
    issues, pull_requests, flights = tuple(issues), tuple(pull_requests), tuple(flights)
    if any(type(number) is not int or number <= 0 for number in [*issues, *pull_requests]):
        raise AssociationError("Issue and PR selectors must be positive repository-qualified numbers")
    if any(not isinstance(flight, str) or not flight.strip() for flight in flights):
        raise AssociationError("Flight selectors must be explicit nonempty identities")
    root = Path(checkout).resolve(strict=True)
    repository = repository_identity(root, repository_id)
    if not isinstance(registry, Registry):
        registry = Registry(registry)
    records = registry.related(repository_id, issues, pull_requests, flights)
    branch_result = git(root, "branch", "--show-current")
    branch = os.fsdecode(branch_result.stdout).strip() if branch_result.returncode == 0 else None
    for owner in registry.read()["records"]:
        if owner["repository"]["id"] != repository_id or any(row["flight"] == owner["flight"] for row in records):
            continue
        same_clone = owner["repository"]["git_common_dir"] == repository["git_common_dir"]
        ref = "refs/heads/" + branch if branch and same_clone else None
        if any(row["kind"] != "remote_branch" for row in reservation_conflicts(owner, path=str(root), ref=ref)):
            records.append(owner)
    worktrees = _worktrees(root)
    by_path = {row["path"]: row for row in worktrees}
    related, owned_paths = [], set()
    for record in records:
        if record["lifecycle"]["state"] == "closed":
            retained = retained_artifacts(record)
            if retained:
                paths = [row["identity"] for row in retained if row["kind"] == "worktree"]
                checkouts = []
                for path in paths:
                    owned_paths.add(path)
                    state = (_state(path, repository["git_common_dir"])
                             if record["repository"]["git_common_dir"] == repository["git_common_dir"] else
                             {"available": False, "reason": "Retained checkout belongs to another clone"})
                    checkouts.append({"path": path, "state": state, "retained": True,
                                      "locked": by_path.get(path, {}).get("locked", False)})
                related.append({"flight": record["flight"], "state": "closed",
                                "issues": record["issues"], "pull_requests": record["pull_requests"],
                                "checkouts": checkouts, "retained_artifacts": retained,
                                "decision": {"action": "wait",
                                    "reason": "Closed flight retains relevant ownership or unresolved operations; reconcile conflicts before mutation",
                                    "alternatives": ["deliberate-dependent-flight"]}})
            continue
        checkouts = []
        for item in [record["checkout"], *record["children"]]:
            owned_paths.add(item["path"])
            observation = {"path": item["path"], "recorded_kind": item["kind"],
                           "recorded_management": item["management"], "recorded_commit": item["commit"]}
            if record["repository"]["git_common_dir"] != repository["git_common_dir"]:
                state = {"available": False, "reason": "Association belongs to another clone; reconcile its recorded checkout explicitly"}
            else:
                state = _state(item["path"], repository["git_common_dir"])
            observation["state"] = state
            actual = by_path.get(item["path"], {})
            observation["locked"] = actual.get("locked", False)
            if state["available"]:
                target = record["delivery"].get("target")
                if not target:
                    default_branch = record["configuration"]["values"].get("default_branch")
                    # Configuration stores a literal branch, not an ambiguous revision.
                    target = "refs/heads/" + default_branch if default_branch else None
                observation["identity_changed"] = (state["commit"] != item["commit"] or state["branch"] != item["branch"])
                observation["branch_drift"] = state["branch"] != item["branch"]
                observation["detached_drift"] = (item["branch"] is None and state["branch"] is None
                                                   and state["commit"] != item["commit"])
                if observation["branch_drift"] or observation["detached_drift"]:
                    observation["branch_state"] = {"available": False,
                        "reason": "Recorded checkout branch/detached identity changed; reconcile before attribution"}
                else:
                    observation["branch_state"] = _branch(root, state["branch"], state["commit"], target)
            checkouts.append(observation)
        unavailable = any(not item["state"]["available"] or item.get("branch_drift")
                          or item.get("detached_drift") for item in checkouts)
        locked = any(item["locked"] for item in checkouts)
        if unavailable or locked:
            action = "wait"
            reason = "Resolve unavailable or locked recorded checkout identity before competing work"
        elif record["flight"] == current_flight:
            action = "resume"
            reason = "Return to this flight's recorded checkout; preserve its unfinished work"
        elif record["lifecycle"]["state"] in ("active", "review", "merged"):
            action = "wait"
            reason = "Related unfinished flight owns the checkout; wait or record a deliberate dependent-flight decision"
        else:
            action = "reuse"
            reason = "Reconcile and reuse the paused related flight instead of creating competing work"
        related.append({"flight": record["flight"], "state": record["lifecycle"]["state"],
                        "issues": record["issues"], "pull_requests": record["pull_requests"],
                        "checkouts": checkouts, "decision": {"action": action, "reason": reason,
                        "alternatives": ["deliberate-dependent-flight"]}})
        obligations = retained_artifacts(record)
        if obligations:
            related[-1]["retained_artifacts"] = obligations
    # A cheap worktree status observation is not a full branch audit. Unknown or
    # unrelated work remains informational and never establishes ownership.
    other = [{**row, "state": _state(row["path"], repository["git_common_dir"])}
             for row in worktrees if row["path"] not in owned_paths and not row.get("bare")]
    return {"schema": 1, "repository": repository, "related": related,
            "decision_required": bool(related), "other_worktrees": other,
            "coverage": {"associations": "explicit repository-qualified flight/issue/PR links only",
                         "branches": "related branches and detached commits only; local cached target/upstream refs",
                         "remote": "Not queried; no fetch or prune performed",
                         "client": "Native session/activity/recovery state is not queried",
                         "limits": "Observations are a point-in-time launch aid, not ownership enforcement or cleanup integration proof"}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, default=Path.cwd())
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--repository", required=True, help="Explicit provider-qualified repository identity")
    parser.add_argument("--issue", type=int, action="append", default=[])
    parser.add_argument("--pr", type=int, action="append", default=[])
    parser.add_argument("--flight", action="append", default=[])
    parser.add_argument("--current-flight")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(detect(args.checkout, args.registry, args.repository, args.issue, args.pr,
                                args.flight, args.current_flight), indent=2))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"schema": 1, "status": "unavailable", "reason": str(error),
                          "decision_required": True}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
