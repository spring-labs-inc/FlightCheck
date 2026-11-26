"""Explicit lifecycle-driven status reconciliation using the existing Registry.

One event is invoked by the workflow at a real lifecycle boundary. Reading cards,
checking a checkout, planning work and ordinary replies never call this module.
"""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import time

from flight_associations import AssociationError, Registry, repository_identity
from status_sync_config import authorize, normalize
from status_sync_github import GitHubProjects, ProviderError, status_identity


EVENTS = {"start", "resume", "review", "repair", "accepted_completion"}
NON_EVENTS = {"plan", "inspect", "card_poll", "message", "early_code"}


def resolve(repository, configuration):
    """Use configured provider identity, without adding a service or store."""
    policy = normalize(configuration["values"].get("status_sync"))
    if policy["mode"] == "disabled":
        return None
    if policy["provider"] != GitHubProjects.name:
        raise ProviderError("unsupported_provider", "No adapter for the configured provider; keep its policy disabled or select a supported existing tracker explicitly.")
    return GitHubProjects(repository, policy)


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and "\x00" not in value


def _save(registry, record, sync):
    """Preserve other flights and refuse a changed same-flight preimage."""
    for _ in range(2):
        state = registry.read()
        current = next((r for r in state["records"] if r["flight"] == record["flight"]), None)
        if current != record:
            raise ProviderError("association_conflict", "The flight changed concurrently; inspect its current ownership and sync outcome before retry.")
        updated = copy.deepcopy(record)
        updated["status_sync"] = copy.deepcopy(sync)
        try:
            return registry.save(updated, expected_revision=state["revision"])["record"]
        except AssociationError as error:
            if "Stale association revision" not in str(error):
                raise
    raise ProviderError("association_conflict", "Another Registry writer is active; retry after fresh observation.")


def _verify(checkout, registry, record, event):
    if event["kind"] != "accepted_completion":
        import checkout_guard
        return checkout_guard.verify(checkout, registry, record["flight"], phase="check")
    # Completion must work from stable same-clone control after execution release
    # and removal. Never adopt/revive the historical execution checkout.
    import flight_lifecycle
    if repository_identity(checkout, record["repository"]["id"]) != record["repository"]:
        raise ProviderError("ownership_unverified", "Completion control checkout belongs to another repository/clone.")
    cleanup = record.get("cleanup", {})
    closure = cleanup.get("closure", {})
    if (record["lifecycle"]["state"] != "closed" or cleanup.get("protocol") != "required-v1"
            or closure.get("complete") is not True or closure.get("blockers")):
        raise ProviderError("completion_unverified", "Accepted completion requires released execution and complete verified disposition, including policy-accepted retention.")
    frozen = cleanup.get("frozen_delivery", {})
    binding = cleanup.get("frozen_binding", {})
    if (not frozen.get("merged") or frozen.get("head") != binding.get("source_head")
            or frozen.get("repository") != record["repository"]["id"]):
        raise ProviderError("completion_unverified", "Closed flight lacks its bound actual merged delivery.")
    actual = flight_lifecycle._discover_delivery(Path(checkout), record, frozen["head"])
    if any(actual.get(k) != frozen.get(k) for k in ("repository", "source_base", "head", "merge_commit", "target", "pull_request")):
        raise ProviderError("completion_unverified", "Actual provider delivery differs from the closed flight binding.")
    endpoint = flight_lifecycle._push_endpoint(Path(checkout), "origin", record["repository"]["id"])
    target = flight_lifecycle._advertised(Path(checkout), endpoint, "refs/heads/" + frozen["target"])
    proof = flight_lifecycle.integration_status(checkout, frozen["head"], frozen["target"], delivery=actual,
                                              remote_observation={"available": True, "target_tip": target})
    if proof.get("verified") is not True:
        raise ProviderError("completion_unverified", "Actual integration is unavailable: " + "; ".join(proof.get("blockers", [])))
    return {"status": "verified", "integration": proof, "closed": True}


def _target(record, work, event, observation, prior):
    kind = event["kind"]
    if observation.get("state") == "CLOSED" and observation.get("state_reason") != "COMPLETED":
        raise ProviderError("cancelled", "Cancelled/not-planned closure is not accepted completion; no Done update is warranted.")
    if kind == "accepted_completion":
        completion = event.get("completion", {})
        if (work.get("scope") != "full" or not isinstance(completion, dict)
                or completion.get("accepted") is not True or completion.get("full_scope") is not True
                or not _text(completion.get("reference"))):
            raise ProviderError("partial_delivery", "A subtask, accepted partial flight or merge does not establish full issue acceptance.")
        if observation.get("state") != "CLOSED" or observation.get("state_reason") != "COMPLETED":
            raise ProviderError("closure_required", "Status-only authority cannot implicitly close an open issue through native automation. Complete separately authorized accepted issue closure, then reconcile its actual state.")
        return "done"
    if record["lifecycle"]["state"] == "closed" or observation.get("state") == "CLOSED":
        raise ProviderError("completed_work", "Completed work cannot be restarted by resume; an explicit new scoped decision and appropriate issue state are required.")
    if kind == "review":
        if event.get("ready") is not True:
            raise ProviderError("not_ready", "Review requires actual scoped full-work readiness; schema/early CODE alone is not that event.")
        return "review"
    if kind == "resume" and prior and prior.get("logical") == "review":
        return "review"
    return "in_progress"


def synchronize(registry, flight, event, *, checkout, provider=None, verifier=None, pause=time.sleep):
    """Read, reconcile, mutate only Status when authorized, and verify readback.

    Provider/verifier injection is a trusted adapter/test boundary. Public CLI
    always uses actual checkout, provider and closed-delivery observations.
    """
    registry = registry if isinstance(registry, Registry) else Registry(registry)
    record = registry.get(flight)
    if record is None:
        raise ValueError("No recorded flight; establish verified ownership first")
    policy = normalize(record["configuration"]["values"].get("status_sync"))
    required = policy["mode"] == "required"
    result = {"flight": flight, "event": event.get("kind") if isinstance(event, dict) else None,
              "mode": policy["mode"], "blocked": False, "outcomes": []}
    if policy["mode"] == "disabled":
        return dict(result, state="disabled", detail="Synchronization is disabled; no provider operation.")
    if isinstance(event, dict) and event.get("kind") in NON_EVENTS:
        return dict(result, state="not_an_event", detail="Planning, inspection and card polling do not synchronize status.")
    if not isinstance(event, dict) or event.get("kind") not in EVENTS:
        raise ValueError("Unknown lifecycle event; use an explicit supported lifecycle boundary")
    issues = event.get("issues")
    if (not _text(event.get("reference")) or not isinstance(issues, list) or not issues
            or any(type(n) is not int or n <= 0 for n in issues) or len(set(issues)) != len(issues)
            or not set(issues) <= set(record["issues"])):
        raise ValueError("Event needs an explicit decision reference and exact changed-issue subset of the recorded flight")
    sync = copy.deepcopy(record.get("status_sync", {}))
    if not isinstance(sync, dict):
        raise ValueError("Recorded synchronization state must be an object")
    work = sync.get("work", [])
    if not isinstance(work, list):
        raise ValueError("Recorded synchronization work must identify owned issue scopes")
    owned = {}
    for row in work:
        if (not isinstance(row, dict) or type(row.get("issue")) is not int or row["issue"] in owned
                or row.get("role") not in ("implementation", "implementation_epic", "roadmap")
                or row.get("scope") not in ("partial", "full") or not _text(row.get("reference"))):
            raise ValueError("Recorded synchronization work has invalid or duplicate explicit ownership")
        owned[row["issue"]] = row
    sync.setdefault("observations", {})
    sync.setdefault("pending", {})
    sync.setdefault("outcomes", [])
    if (not isinstance(sync["observations"], dict) or not isinstance(sync["pending"], dict)
            or not isinstance(sync["outcomes"], list)):
        raise ValueError("Recorded synchronization observations/intents/outcomes are invalid; preserve and reconcile them")
    try:
        proof = (verifier or _verify)(checkout, registry, record, event)
        if proof.get("status") != "verified":
            raise ProviderError("ownership_unverified", "Actual selected ownership or completion could not be verified.")
        provider = provider or resolve(record["repository"]["id"], record["configuration"])
        if getattr(provider, "name", None) != policy["provider"]:
            raise ProviderError("unsupported_provider", "Resolved provider does not match the confirmed configuration.")
    except (ProviderError, ValueError, OSError) as error:
        reason = getattr(error, "reason", "ownership_unverified")
        return dict(result, state="unsynchronized", blocked=required,
                    outcomes=[{"state": "unsynchronized", "reason": reason, "detail": str(error)}])
    automation = provider.automation()
    result.update(automation=automation, concurrency=getattr(provider, "concurrency", "Provider-specific conditional status update"))
    for issue in issues:
        key = str(issue)
        row = {"issue": issue, "state": "unsynchronized"}
        try:
            scope = owned.get(issue)
            if scope is None:
                raise ProviderError("work_scope_missing", "An associated link is not owned work; record its explicit scoped implementation decision.")
            if scope["role"] == "roadmap":
                row.update(state="not_applicable", reason="roadmap", detail="Roadmap/parent links confer no implementation or status authority.")
                result["outcomes"].append(row)
                continue
            peers = [r for r in registry.read()["records"]
                     if r["flight"] != flight and r["repository"]["id"] == record["repository"]["id"]
                     and r["lifecycle"]["state"] != "closed"
                     and isinstance(r.get("status_sync"), dict)
                     and isinstance(r["status_sync"].get("work"), list)
                     and any(isinstance(w, dict) and w.get("issue") == issue
                             and w.get("role") in ("implementation", "implementation_epic")
                             for w in r["status_sync"]["work"])]
            if peers:
                raise ProviderError("concurrent_flight", "Another unfinished flight explicitly owns this issue's work. Coordinate one status writer or wait; associated roadmap links alone do not block.")
            decision = authorize(record["grants"].get("tracker_status"), record["repository"]["id"], record["configuration"], issue)
            if not decision["authorized"]:
                raise ProviderError(decision["reason"], "Status write is not authorized for this exact issue/configuration/project/field; reconcile the actual scoped grant.")
            current = provider.observe(issue)
            if (current.get("repository") != record["repository"]["id"] or current.get("issue") != issue
                    or current.get("project_id") != policy["project_id"] or current.get("field_id") != policy["field_id"]):
                raise ProviderError("identity_conflict", "Provider observation does not match the exact scoped issue and mapping.")
            prior = sync["observations"].get(key)
            if prior is not None and (not isinstance(prior, dict) or not isinstance(prior.get("observation"), dict)):
                raise ProviderError("reconciliation_required", "Prior Status observation is malformed; inspect its retained original.")
            logical = _target(record, scope, event, current, prior)
            target = policy["options"][logical]
            pending = sync["pending"].get(key)
            if pending is not None and (not isinstance(pending, dict) or not isinstance(pending.get("before"), dict)
                    or not _text(pending.get("operation")) or type(pending.get("attempts")) is not int
                    or not 0 <= pending["attempts"] <= 2):
                raise ProviderError("pending_reconciliation", "Prior uncertain operation is malformed; preserve and reconcile its original intent.")
            if pending and (pending.get("configuration_revision") != record["configuration"]["revision"]
                            or pending.get("logical") != logical):
                raise ProviderError("pending_reconciliation", "An earlier uncertain status event remains reserved; reconcile its original target/scope first.")
            if current.get("option_id") == target:
                row.update(state="synchronized", reason="already_aligned", observation=current)
            else:
                expected = event.get("expected", {}).get(key) if isinstance(event.get("expected", {}), dict) else None
                if expected is not None and not _text(event.get("reconciliation_reference")):
                    raise ProviderError("reconciliation_required", "Explicit observed-state reconciliation needs its scoped owner decision reference.")
                if expected is not None and not isinstance(expected, dict):
                    raise ProviderError("reconciliation_required", "Expected Status must be a fresh complete provider observation.")
                if pending:
                    expected = pending["before"]
                elif expected is None and prior and prior.get("configuration_revision") == record["configuration"]["revision"]:
                    expected = prior["observation"]
                elif expected is None and event["kind"] == "start" and current.get("option_id") in (
                        None, policy["options"]["todo"], policy["options"]["ready"]):
                    expected = current
                if expected is None or status_identity(current) != status_identity(expected):
                    raise ProviderError("conflict", "Current Status differs from the last verified/explicit expected observation; preserve the manual/native decision and reconcile explicitly.")
                if current.get("writable") is not True:
                    raise ProviderError("permission_denied", "Required project write capability is unavailable; no status mutation.")
                operation = pending["operation"] if pending else hashlib.sha256(json.dumps(
                    [flight, issue, event["kind"], event["reference"], status_identity(current)], sort_keys=True).encode()).hexdigest()
                attempts = pending.get("attempts", 0) if pending else 0
                while attempts < 2:
                    attempts += 1
                    sync["pending"][key] = {"operation": operation, "before": current, "logical": logical,
                                            "configuration_revision": record["configuration"]["revision"], "attempts": attempts}
                    record = _save(registry, record, sync)  # Intent precedes mutation.
                    try:
                        written = provider.write(issue, target, current, operation)
                        actual = written["observation"]
                        if written["state"] == "conflict":
                            raise ProviderError("conflict", "Status changed between planning and apply; preserved the newer provider decision.")
                    except ProviderError as error:
                        if not error.ambiguous:
                            sync["pending"].pop(key, None)
                            raise
                        try:
                            actual = provider.observe(issue)
                        except ProviderError:
                            raise ProviderError("ambiguous", "Write outcome remains unknown; retained its intent. Reconcile actual state before retry.") from error
                        if actual.get("option_id") != target:
                            if status_identity(actual) != status_identity(current):
                                sync["pending"].pop(key, None)
                                raise ProviderError("conflict", "A newer manual/native status follows the uncertain write; preserved it without replay.") from error
                            if attempts < 2:
                                pause(0.05 * attempts)
                                continue
                            raise ProviderError("retry_exhausted", "Two bounded attempts remain unverified; retained intent requires explicit reconciliation.") from error
                    if (actual.get("option_id") != target
                            or any(actual.get(k) != current.get(k) for k in ("repository", "issue", "project_id", "field_id", "item_id", "state", "state_reason"))):
                        sync["pending"].pop(key, None)
                        raise ProviderError("conflict", "Readback differs from the warranted status/issue state; preserve the observed result and inspect automation/concurrent changes.")
                    row.update(state="synchronized", reason="verified_write", before=status_identity(current),
                               observation=actual, operation=operation, attempts=attempts)
                    break
                else:
                    raise ProviderError("retry_exhausted", "Prior attempts exhausted; reconcile the retained uncertain operation without a blind retry.")
            if row["state"] == "synchronized":
                sync["pending"].pop(key, None)
                sync["observations"][key] = {"configuration_revision": record["configuration"]["revision"],
                                              "logical": logical, "observation": row["observation"]}
        except (ProviderError, ValueError, OSError) as error:
            row.update(reason=getattr(error, "reason", "provider_unavailable"), detail=str(error))
        sync["outcomes"] = (sync["outcomes"] + [{**row, "event": event["kind"], "reference": event["reference"]}])[-32:]
        try:
            record = _save(registry, record, sync)
        except (ProviderError, AssociationError) as error:
            row = {"issue": issue, "state": "unsynchronized", "reason": "association_conflict",
                   "detail": str(error) + "; reconcile provider state before retrying any mutation."}
        result["outcomes"].append(row)
    failed = any(r["state"] == "unsynchronized" for r in result["outcomes"])
    result.update(state="unsynchronized" if failed else "synchronized", blocked=required and failed)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, default=Path.cwd())
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--flight", required=True)
    parser.add_argument("--event", type=Path, required=True, help="Private exact lifecycle event/changed-issue decision JSON")
    args = parser.parse_args(argv)
    try:
        if args.event.is_symlink() or not args.event.is_file() or args.event.stat().st_mode & 0o077:
            raise ValueError("Lifecycle event must be a private regular file, not a shared card or symlink")
        event = json.loads(args.event.read_text())
        result = synchronize(args.registry, args.flight, event, checkout=args.checkout)
        print(json.dumps(result, indent=2))
        return 1 if result["blocked"] else 0
    except (OSError, ValueError, AssociationError) as error:
        print(json.dumps({"state": "unsynchronized", "blocked": True, "error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
